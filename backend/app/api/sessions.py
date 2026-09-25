"""Phase-9 routes: upload, status, schema, profile, data-quality, cleaning,
KPI headline/breakdown serving, reset.

Handlers validate transport, call the ingestion/session services, and map
domain errors to the typed error envelope. No supply-chain math lives here:
headline KPIs are read from the derived artifact; filtered/grouped serving
recomputes synchronously through the `app.kpis` domain service, never
inline.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, File, Query, Request, UploadFile

from app import sessions as session_store
from app.config import settings
from app.ingestion import (
    SNIFF_LIMIT_BYTES,
    check_duplicate_headers,
    declared_size_exceeds,
    detect_encoding,
    has_csv_extension,
    mime_is_csv_plausible,
    parse_header,
    sanitize_filename,
    stream_upload_to_temp,
)
from app.ingestion_errors import (
    EMPTY_FILE,
    FILE_TOO_LARGE,
    INTERNAL_STAGE_ERROR,
    INVALID_EXTENSION,
    INVALID_FILTER_VALUE,
    INVALID_GROUPING,
    INVALID_SEVERITY_FILTER,
    MALFORMED_CSV,
    NOT_READY,
    SCHEMA_MISSING_COLUMN,
    SESSION_EXPIRED,
    SESSION_NOT_FOUND,
    STAGE_ANALYZING,
    STAGE_CLEANING,
    STAGE_PROFILING,
    STAGE_VALIDATING,
    IngestionError,
)
from app.schema_validation import run_schema_validation
from app.schemas import (
    STATE_CANONICALIZING,
    STATE_EXPIRED,
    STATE_FAILED,
    STATE_PROFILING,
    STATE_READY,
    STATE_VALIDATING,
    ApiErrorModel,
    CleaningArtifact,
    CleaningReportData,
    CleaningReportResponse,
    DataQualityData,
    DataQualityResponse,
    DataQualitySummary,
    EnvelopeMeta,
    ErrorResponse,
    KpiArtifact,
    KpiCommercialData,
    KpiCommercialResponse,
    KpiDeliveryData,
    KpiDeliveryResponse,
    KpiGroup,
    KpiOverviewData,
    KpiOverviewResponse,
    KpiTotals,
    KpiWeightedRates,
    ProfileResponse,
    ProfilingArtifact,
    SchemaMappingView,
    SchemaReportData,
    SchemaReportResponse,
    SessionDeletedData,
    SessionDeletedResponse,
    SessionManifest,
    SessionStatusData,
    SessionStatusResponse,
    UploadAcceptedData,
    UploadAcceptedResponse,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.kpis import KpiFilters, KpiTables

router = APIRouter(prefix="/api/v1")


def _base_meta(
    *,
    session_id: str | None = None,
    session_state: str | None = None,
    filters: dict[str, str] | None = None,
) -> EnvelopeMeta:
    """Envelope metadata stamped per response (versions read live)."""
    return EnvelopeMeta(
        appVersion=settings.app_version,
        schemaVersion=settings.schema_version,
        generatedAt=session_store.utcnow_naive_iso(),
        sessionId=session_id,
        sessionState=session_state,
        filters=filters or {},
    )


def _status_url(session_id: str) -> str:
    return f"/api/v1/sessions/{session_id}/status"


def _declared_content_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@router.post(
    "/sessions/uploads",
    response_model=UploadAcceptedResponse,
    status_code=202,
)
async def upload_session(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(default=None),
) -> UploadAcceptedResponse:
    """Run cheap sync guards, store the immutable raw, return 202.

    Phase-5 schema validation is scheduled as a framework-local
    post-response task: the 202 is composed and sent before validation
    executes, so POST never waits for it.
    """
    byte_limit = settings.max_upload_bytes

    # Cheap transport checks run before any session tree exists.
    if file is None or not file.filename:
        raise IngestionError(
            INVALID_EXTENSION,
            STAGE_VALIDATING,
            "No file was uploaded. Attach a .csv file to the 'file' field.",
            400,
            {},
        )
    filename_safe = sanitize_filename(file.filename)
    if not has_csv_extension(filename_safe):
        raise IngestionError(
            INVALID_EXTENSION,
            STAGE_VALIDATING,
            "Only .csv files are accepted. Rename or convert the file.",
            400,
            {"filenameSafe": filename_safe},
        )
    if not mime_is_csv_plausible(file.content_type):
        raise IngestionError(
            INVALID_EXTENSION,
            STAGE_VALIDATING,
            "The upload does not look like a CSV file. "
            "Upload a .csv file saved as CSV.",
            400,
            {
                "filenameSafe": filename_safe,
                "mime": (file.content_type or ""),
            },
        )
    if declared_size_exceeds(_declared_content_length(request), byte_limit):
        raise IngestionError(
            FILE_TOO_LARGE,
            STAGE_VALIDATING,
            f"The file exceeds the {settings.max_upload_mb} MB upload limit. "
            "Choose a smaller file and try again.",
            413,
            {"maxBytes": byte_limit},
        )

    session_id = session_store.new_session_id()
    paths = session_store.session_paths(settings.session_root, session_id)
    try:
        session_store.create_session_layout(paths)
        streamed = await stream_upload_to_temp(file, paths.partial, byte_limit)
        if streamed.size_bytes == 0:
            raise IngestionError(
                EMPTY_FILE,
                STAGE_VALIDATING,
                "The file is empty (0 bytes). "
                "Upload a CSV with a header row and at least one data row.",
                400,
                {"filenameSafe": filename_safe},
            )
        with open(paths.partial, "rb") as handle:
            sniff = handle.read(SNIFF_LIMIT_BYTES)
        encoding = detect_encoding(sniff)
        header = parse_header(encoding.text)
        check_duplicate_headers(header.names)
        # Header-only proof comes from the fused stream scan, not a second
        # file pass: a syntactically present row (even all-empty fields)
        # counts as a record. Missing-value semantics belong to Phase 5+.
        if not streamed.has_data:
            raise IngestionError(
                EMPTY_FILE,
                STAGE_VALIDATING,
                "The file has a header row but no data rows. "
                "Upload a CSV with at least one data row.",
                400,
                {
                    "filenameSafe": filename_safe,
                    "columnCount": len(header.names),
                },
            )
        # All guards passed: atomically promote bytes to the immutable raw.
        os.replace(paths.partial, paths.raw)
        session_store.mark_raw_read_only(paths.raw)
        now = session_store.utcnow_naive_iso()
        manifest = session_store.build_manifest(
            session_id=session_id,
            filename_safe=filename_safe,
            size_bytes=streamed.size_bytes,
            sha256_hex=streamed.sha256_hex,
            encoding=encoding.name,
            now=now,
        )
        session_store.write_manifest(paths, manifest)
    except IngestionError:
        session_store.remove_session_tree(paths)
        raise
    except Exception as exc:  # never leak tracebacks or paths to clients
        session_store.remove_session_tree(paths)
        logger.warning("upload_internal_error stage=%s", STAGE_VALIDATING)
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_VALIDATING,
            "The upload could not be processed. Try again with a valid CSV.",
            500,
            {},
        ) from exc
    finally:
        if file is not None:
            await file.close()

    logger.info(
        "upload_accepted bytes=%d encoding=%s",
        streamed.size_bytes,
        encoding.name,
    )
    # Scheduled, not awaited: runs after the 202 response is sent.
    background_tasks.add_task(run_schema_validation, session_id)
    data = UploadAcceptedData(
        sessionId=session_id,
        statusUrl=_status_url(session_id),
        filenameSafe=filename_safe,
        bytes=streamed.size_bytes,
        sha256=streamed.sha256_hex,
        encoding=encoding.name,
    )
    return UploadAcceptedResponse(
        data=data,
        meta=_base_meta(session_id=session_id, session_state=STATE_VALIDATING),
        error=None,
    )


@router.get("/sessions/{session_id}/status", response_model=SessionStatusResponse)
async def session_status(session_id: str) -> SessionStatusResponse:
    """Report session state. Purely observational: never executes validation.

    Terminal FAILED sessions answer 200 with their stored error and are
    never refreshed.
    """
    if not session_store.is_valid_session_id(session_id):
        raise IngestionError(
            SESSION_NOT_FOUND,
            STAGE_VALIDATING,
            "No upload session matches this identifier.",
            404,
            {},
        )
    paths = session_store.session_paths(settings.session_root, session_id)
    manifest = session_store.read_manifest(paths)
    if manifest is None:
        raise IngestionError(
            SESSION_NOT_FOUND,
            STAGE_VALIDATING,
            "No upload session matches this identifier.",
            404,
            {},
        )
    now = datetime.now()
    if session_store.is_expired(manifest, now):
        session_store.remove_session_tree(paths)
        logger.info("session_expired")
        raise IngestionError(
            SESSION_EXPIRED,
            STAGE_VALIDATING,
            "This upload session has expired. Upload the file again.",
            410,
            {},
            session_id=session_id,
            session_state=STATE_EXPIRED,
        )
    if manifest.state == STATE_FAILED:
        data = SessionStatusData(
            state=manifest.state,
            stage=manifest.stage,
            progress=manifest.progress,
            startedAt=manifest.createdAt,
            updatedAt=manifest.updatedAt,
            error=manifest.error,
        )
        return SessionStatusResponse(
            data=data,
            meta=_base_meta(session_id=session_id, session_state=manifest.state),
            error=None,
        )
    now_iso = session_store.utcnow_naive_iso()
    # Sliding-TTL touch that can never regress a concurrent transition:
    # compare-and-swap (fresh state served on mismatch), terminal FAILED
    # manifests never rewritten.
    manifest = session_store.touch_manifest_if_current(paths, manifest, now_iso)
    data = SessionStatusData(
        state=manifest.state,
        stage=manifest.stage,
        progress=manifest.progress,
        startedAt=manifest.createdAt,
        updatedAt=manifest.updatedAt,
        error=manifest.error,
    )
    return SessionStatusResponse(
        data=data,
        meta=_base_meta(session_id=session_id, session_state=manifest.state),
        error=None,
    )


@router.get("/sessions/{session_id}/schema", response_model=SchemaReportResponse)
async def session_schema(session_id: str) -> SchemaReportResponse:
    """Return the schema report (`docs/api-contract.md` shape exactly).

    Purely observational. While validation has not completed the endpoint
    returns the contract's 409 NOT_READY; missing critical columns surface
    as 422 SCHEMA_MISSING_COLUMN once a decision exists.
    """
    if not session_store.is_valid_session_id(session_id):
        raise IngestionError(
            SESSION_NOT_FOUND,
            STAGE_VALIDATING,
            "No upload session matches this identifier.",
            404,
            {},
        )
    paths = session_store.session_paths(settings.session_root, session_id)
    manifest = session_store.read_manifest(paths)
    if manifest is None:
        raise IngestionError(
            SESSION_NOT_FOUND,
            STAGE_VALIDATING,
            "No upload session matches this identifier.",
            404,
            {},
        )
    if session_store.is_expired(manifest, datetime.now()):
        session_store.remove_session_tree(paths)
        logger.info("session_expired")
        raise IngestionError(
            SESSION_EXPIRED,
            STAGE_VALIDATING,
            "This upload session has expired. Upload the file again.",
            410,
            {},
            session_id=session_id,
            session_state=STATE_EXPIRED,
        )
    if manifest.state == STATE_VALIDATING:
        raise IngestionError(
            NOT_READY,
            STAGE_VALIDATING,
            "Schema validation has not completed yet. "
            "Check the session status and try again shortly.",
            409,
            {"state": manifest.state},
            session_id=session_id,
            session_state=manifest.state,
        )
    if manifest.state == STATE_FAILED:
        missing: list[str] = []
        if manifest.error is not None:
            raw_missing = manifest.error.details.get("missing", [])
            if isinstance(raw_missing, list):
                missing = [str(name) for name in raw_missing]
        count = len(missing)
        noun = "column" if count == 1 else "columns"
        raise IngestionError(
            SCHEMA_MISSING_COLUMN,
            STAGE_VALIDATING,
            f"The file is missing {count} required {noun}: "
            + ", ".join(missing)
            + ". V1 supports DataCo-compatible CSV files.",
            422,
            {"missing": missing},
        )
    report = session_store.read_schema_report(paths)
    if report is None:  # pragma: no cover - artifact written with PROFILING
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_VALIDATING,
            "The schema report could not be read. Upload the file again.",
            500,
            {},
        )
    data = SchemaReportData(
        sourceColumns=report.sourceColumns,
        mapping=[
            SchemaMappingView(
                source=entry.source,
                canonical=entry.canonical,
                fieldClass=entry.fieldClass,
            )
            for entry in report.mapping
        ],
        missingCritical=[],
    )
    return SchemaReportResponse(
        data=data,
        meta=_base_meta(session_id=session_id, session_state=manifest.state),
        error=None,
    )


# HTTP status for re-surfaced terminal errors (stored without a status code).
_TERMINAL_STATUS: dict[str, int] = {
    SCHEMA_MISSING_COLUMN: 422,
    MALFORMED_CSV: 422,
    INTERNAL_STAGE_ERROR: 500,
}

_SEVERITIES: tuple[str, ...] = ("ERROR", "WARNING", "INFO")


def _resolve_session(
    session_id: str,
) -> tuple[SessionManifest, session_store.SessionPaths]:
    """Load a session or raise the contract 404/410 (no work executed)."""
    if not session_store.is_valid_session_id(session_id):
        raise IngestionError(
            SESSION_NOT_FOUND,
            STAGE_PROFILING,
            "No upload session matches this identifier.",
            404,
            {},
        )
    paths = session_store.session_paths(settings.session_root, session_id)
    manifest = session_store.read_manifest(paths)
    if manifest is None:
        raise IngestionError(
            SESSION_NOT_FOUND,
            STAGE_PROFILING,
            "No upload session matches this identifier.",
            404,
            {},
        )
    if session_store.is_expired(manifest, datetime.now()):
        session_store.remove_session_tree(paths)
        logger.info("session_expired")
        raise IngestionError(
            SESSION_EXPIRED,
            STAGE_PROFILING,
            "This upload session has expired. Upload the file again.",
            410,
            {},
            session_id=session_id,
            session_state=STATE_EXPIRED,
        )
    return manifest, paths


def _profiling_artifact_or_raise(
    session_id: str,
) -> tuple[SessionManifest, ProfilingArtifact]:
    """Return the stored profiling artifact for CLEANING+ sessions.

    Purely observational: never executes profiling. Pending sessions get
    the contract 409 NOT_READY; terminal sessions re-surface their stored
    error without leaking values.
    """
    manifest, paths = _resolve_session(session_id)
    if manifest.state == STATE_FAILED:
        stored = manifest.error
        code = stored.code if stored is not None else INTERNAL_STAGE_ERROR
        raise IngestionError(
            code,
            stored.stage if stored is not None else STAGE_PROFILING,
            stored.message
            if stored is not None
            else "Profiling could not be completed. Upload the file again.",
            _TERMINAL_STATUS.get(code, 500),
            dict(stored.details) if stored is not None else {},
            session_id=session_id,
            session_state=manifest.state,
        )
    if manifest.state in (STATE_VALIDATING, STATE_PROFILING) or (
        manifest.profileArtifact is None
    ):
        raise IngestionError(
            NOT_READY,
            STAGE_PROFILING,
            "Value-level profiling has not completed yet. "
            "Check the session status and try again shortly.",
            409,
            {"state": manifest.state},
            session_id=session_id,
            session_state=manifest.state,
        )
    artifact = session_store.read_profiling_report(paths)
    if artifact is None:  # pragma: no cover - written with the transition
        logger.warning("profiling_artifact_unreadable")
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_PROFILING,
            "The profiling report could not be read. Upload the file again.",
            500,
            {},
            session_id=session_id,
            session_state=manifest.state,
        )
    return manifest, artifact


@router.get("/sessions/{session_id}/profile", response_model=ProfileResponse)
async def session_profile(session_id: str) -> ProfileResponse:
    """Return the read-only pre-cleaning profile (contract shape exactly)."""
    manifest, artifact = _profiling_artifact_or_raise(session_id)
    return ProfileResponse(
        data=artifact.profile,
        meta=_base_meta(session_id=session_id, session_state=manifest.state),
        error=None,
    )


@router.get("/sessions/{session_id}/data-quality", response_model=DataQualityResponse)
async def session_data_quality(
    session_id: str,
    severity: str | None = None,
) -> DataQualityResponse:
    """Return DQ issues by rule, optionally filtered to one severity.

    The summary always describes the full evaluated set; only the issue
    list is narrowed by `?severity=`. Unknown severity values are rejected
    (never silently mapped) with 422 INVALID_SEVERITY_FILTER.
    """
    manifest, artifact = _profiling_artifact_or_raise(session_id)
    wanted: str | None = None
    if severity is not None:
        normalized = severity.strip().upper()
        if normalized not in _SEVERITIES:
            raise IngestionError(
                INVALID_SEVERITY_FILTER,
                STAGE_PROFILING,
                "Unknown severity filter. Use one of: ERROR, WARNING, INFO.",
                422,
                {"severity": severity},
                session_id=session_id,
                session_state=manifest.state,
            )
        wanted = normalized
    issues = [
        issue for issue in artifact.issues if wanted is None or issue.severity == wanted
    ]
    summary = DataQualitySummary(
        rulesEvaluated=len(artifact.rulesEvaluated),
        rulesTriggered=len(artifact.issues),
        errors=sum(1 for issue in artifact.issues if issue.severity == "ERROR"),
        warnings=sum(1 for issue in artifact.issues if issue.severity == "WARNING"),
        infos=sum(1 for issue in artifact.issues if issue.severity == "INFO"),
        blockingIssues=sum(
            1 for issue in artifact.issues if issue.blockedStage is not None
        ),
    )
    return DataQualityResponse(
        data=DataQualityData(summary=summary, issues=issues),
        meta=_base_meta(session_id=session_id, session_state=manifest.state),
        error=None,
    )


def _cleaning_artifact_or_raise(
    session_id: str,
) -> tuple[SessionManifest, CleaningArtifact]:
    """Return the stored cleaning report for CANONICALIZING sessions.

    Purely observational: never executes cleaning. Pending sessions get
    the contract 409 NOT_READY; terminal sessions re-surface their stored
    error without leaking values.
    """
    manifest, paths = _resolve_session(session_id)
    if manifest.state == STATE_FAILED:
        stored = manifest.error
        code = stored.code if stored is not None else INTERNAL_STAGE_ERROR
        raise IngestionError(
            code,
            stored.stage if stored is not None else STAGE_CLEANING,
            stored.message
            if stored is not None
            else "Cleaning could not be completed. Upload the file again.",
            _TERMINAL_STATUS.get(code, 500),
            dict(stored.details) if stored is not None else {},
            session_id=session_id,
            session_state=manifest.state,
        )
    if manifest.state != STATE_CANONICALIZING or manifest.cleaningArtifact is None:
        raise IngestionError(
            NOT_READY,
            STAGE_CLEANING,
            "Auditable cleaning has not completed yet. "
            "Check the session status and try again shortly.",
            409,
            {"state": manifest.state},
            session_id=session_id,
            session_state=manifest.state,
        )
    artifact = session_store.read_cleaning_report(paths)
    if artifact is None:  # pragma: no cover - written with the transition
        logger.warning("cleaning_artifact_unreadable")
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_CLEANING,
            "The cleaning report could not be read. Upload the file again.",
            500,
            {},
            session_id=session_id,
            session_state=manifest.state,
        )
    return manifest, artifact


@router.get(
    "/sessions/{session_id}/cleaning-report", response_model=CleaningReportResponse
)
async def session_cleaning_report(session_id: str) -> CleaningReportResponse:
    """Return the audited cleaning log (contract shape exactly)."""
    manifest, artifact = _cleaning_artifact_or_raise(session_id)
    return CleaningReportResponse(
        data=CleaningReportData(steps=artifact.steps),
        meta=_base_meta(session_id=session_id, session_state=manifest.state),
        error=None,
    )


@router.delete("/sessions/{session_id}", response_model=SessionDeletedResponse)
async def delete_session(session_id: str) -> SessionDeletedResponse:
    """Idempotent reset: delete the whole session tree, UUID-gated."""
    if not session_store.is_valid_session_id(session_id):
        raise IngestionError(
            SESSION_NOT_FOUND,
            STAGE_VALIDATING,
            "No upload session matches this identifier.",
            404,
            {},
        )
    paths = session_store.session_paths(settings.session_root, session_id)
    session_store.remove_session_tree(paths)
    logger.info("session_deleted")
    return SessionDeletedResponse(
        data=SessionDeletedData(deleted=True),
        meta=_base_meta(session_id=session_id, session_state=None),
        error=None,
    )


def ingestion_error_envelope(exc: IngestionError) -> ErrorResponse:
    """Map a domain error to the contract error envelope (no raw contents)."""
    return ErrorResponse(
        data=None,
        meta=_base_meta(session_id=exc.session_id, session_state=exc.session_state),
        error=ApiErrorModel(
            code=exc.code,
            stage=exc.stage,
            message=exc.message,
            details=exc.details,
        ),
    )


# ---------------------------------------------------------------------------
# KPI serving (Phase 9; api-contract sections 3/5/6)
# ---------------------------------------------------------------------------

# Accepted filter tokens are the canonical enum values (exact match, never
# silently mapped) plus the UNKNOWN_FLAGGED sentinel, which is a reported
# canonical value. Anything else is rejected with 422 INVALID_FILTER_VALUE.
_KPI_ENUM_SETS: dict[str, set[str]] = {}


def _kpi_enum_sets() -> dict[str, set[str]]:
    """Canonical filter vocabularies (local import: maps own the source)."""
    from app.canonicalization import (
        CUSTOMER_SEGMENT_MAP,
        ORDER_STATUS_MAP,
        SHIPPING_MODE_MAP,
        UNKNOWN_FLAGGED,
    )

    global _KPI_ENUM_SETS
    if not _KPI_ENUM_SETS:
        _KPI_ENUM_SETS = {
            "shipping_mode": set(SHIPPING_MODE_MAP.values()) | {UNKNOWN_FLAGGED},
            "order_status": set(ORDER_STATUS_MAP.values()) | {UNKNOWN_FLAGGED},
            "customer_segment": set(CUSTOMER_SEGMENT_MAP.values()) | {UNKNOWN_FLAGGED},
            "shipment_outcome": {
                "LATE",
                "EARLY",
                "ON_SCHEDULE",
                "SHIPPING_CANCELED",
            },
        }
    return _KPI_ENUM_SETS


def _parse_date_bound(
    raw: str | None, name: str, session_id: str, state: str | None
) -> date | None:
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise IngestionError(
            INVALID_FILTER_VALUE,
            STAGE_ANALYZING,
            f"Unknown date filter '{name}'. Use ISO YYYY-MM-DD on order date.",
            422,
            {name: raw},
            session_id=session_id,
            session_state=state,
        ) from None


def _parse_enum_filter(
    raw: str | None, name: str, session_id: str, state: str | None
) -> str | None:
    if raw is None:
        return None
    wanted = raw.strip()
    if wanted in _kpi_enum_sets()[name]:
        return wanted
    raise IngestionError(
        INVALID_FILTER_VALUE,
        STAGE_ANALYZING,
        f"Unknown {name} filter value. It was rejected, never mapped.",
        422,
        {name: raw},
        session_id=session_id,
        session_state=state,
    )


def _parse_kpi_filters(
    *,
    session_id: str,
    state: str | None,
    date_from: str | None,
    date_to: str | None,
    market: str | None,
    region: str | None,
    category: str | None,
    department: str | None,
    shipping_mode: str | None,
    order_status: str | None,
    shipment_outcome: str | None,
    customer_segment: str | None,
) -> KpiFilters:
    """Validate serving filters (unknown enums rejected, never mapped)."""
    from app.kpis import KpiFilters

    parsed_from = _parse_date_bound(date_from, "from", session_id, state)
    parsed_to = _parse_date_bound(date_to, "to", session_id, state)

    def text(raw: str | None) -> str | None:
        if raw is None:
            return None
        stripped = raw.strip()
        return stripped or None

    return KpiFilters(
        date_from=parsed_from,
        date_to=parsed_to,
        market=text(market),
        region=text(region),
        category=text(category),
        department=text(department),
        shipping_mode=_parse_enum_filter(
            shipping_mode, "shipping_mode", session_id, state
        ),
        order_status=_parse_enum_filter(
            order_status, "order_status", session_id, state
        ),
        shipment_outcome=_parse_enum_filter(
            shipment_outcome, "shipment_outcome", session_id, state
        ),
        customer_segment=_parse_enum_filter(
            customer_segment, "customer_segment", session_id, state
        ),
    )


def _kpi_or_raise(
    session_id: str,
) -> tuple[SessionManifest, KpiArtifact, KpiTables]:
    """Return the stored KPI artifact plus parsed canonical tables.

    Purely observational: never executes analysis. Sessions that have not
    reached READY (including canonical-blocked sessions parked behind a
    governed gate) get the contract 409 NOT_READY; terminal sessions
    re-surface their stored error without leaking values.
    """
    from app.kpis import load_canonical_tables

    manifest, paths = _resolve_session(session_id)
    if manifest.state == STATE_FAILED:
        stored = manifest.error
        code = stored.code if stored is not None else INTERNAL_STAGE_ERROR
        raise IngestionError(
            code,
            stored.stage if stored is not None else STAGE_ANALYZING,
            stored.message
            if stored is not None
            else "KPI analysis could not be completed. Upload the file again.",
            _TERMINAL_STATUS.get(code, 500),
            dict(stored.details) if stored is not None else {},
            session_id=session_id,
            session_state=manifest.state,
        )
    if manifest.state != STATE_READY or manifest.kpiArtifact is None:
        raise IngestionError(
            NOT_READY,
            STAGE_ANALYZING,
            "KPI analysis has not completed yet. "
            "Check the session status and try again shortly.",
            409,
            {"state": manifest.state},
            session_id=session_id,
            session_state=manifest.state,
        )
    artifact = session_store.read_kpi_report(paths)
    if artifact is None:  # pragma: no cover - written with the transition
        logger.warning("kpi_artifact_unreadable")
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_ANALYZING,
            "The KPI report could not be read. Upload the file again.",
            500,
            {},
            session_id=session_id,
            session_state=manifest.state,
        )
    try:
        tables = load_canonical_tables(paths)
    except OSError:  # pragma: no cover - written with the transition
        logger.warning("kpi_tables_unreadable")
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_ANALYZING,
            "The canonical tables could not be read. Upload the file again.",
            500,
            {},
            session_id=session_id,
            session_state=manifest.state,
        )
    return manifest, artifact, tables


@router.get("/sessions/{session_id}/kpis/overview", response_model=KpiOverviewResponse)
async def session_kpis_overview(
    session_id: str,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    market: str | None = None,
    region: str | None = None,
    category: str | None = None,
    department: str | None = None,
    shipping_mode: str | None = None,
    order_status: str | None = None,
    shipment_outcome: str | None = None,
    customer_segment: str | None = None,
) -> KpiOverviewResponse:
    """Headline commercial + shipment KPIs (contract shape exactly).

    Unfiltered responses serve the stored headline set; filtered
    recomputation from the cached canonical tables is synchronous.
    """
    from app.kpis import compute_headline, headline_totals

    manifest, artifact, tables = _kpi_or_raise(session_id)
    filters = _parse_kpi_filters(
        session_id=session_id,
        state=manifest.state,
        date_from=date_from,
        date_to=date_to,
        market=market,
        region=region,
        category=category,
        department=department,
        shipping_mode=shipping_mode,
        order_status=order_status,
        shipment_outcome=shipment_outcome,
        customer_segment=customer_segment,
    )
    if filters.is_active():
        kpis = compute_headline(tables, filters)
    else:
        kpis = artifact.kpis
    raw_totals = headline_totals(tables, filters)
    totals = KpiTotals(
        items=int(raw_totals["items"]),
        orders=int(raw_totals["orders"]),
        eligibleOrders=int(raw_totals["eligibleOrders"]),
        grossValue=str(raw_totals["grossValue"]),
        discountTotal=str(raw_totals["discountTotal"]),
        netValue=str(raw_totals["netValue"]),
        profitTotal=str(raw_totals["profitTotal"]),
        units=int(raw_totals["units"]),
    )
    return KpiOverviewResponse(
        data=KpiOverviewData(kpis=kpis, totals=totals),
        meta=_base_meta(
            session_id=session_id,
            session_state=manifest.state,
            filters=filters.as_meta(),
        ),
        error=None,
    )


@router.get("/sessions/{session_id}/kpis/delivery", response_model=KpiDeliveryResponse)
async def session_kpis_delivery(
    session_id: str,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    market: str | None = None,
    region: str | None = None,
    category: str | None = None,
    department: str | None = None,
    shipping_mode: str | None = None,
    order_status: str | None = None,
    shipment_outcome: str | None = None,
    customer_segment: str | None = None,
    by: str | None = None,
) -> KpiDeliveryResponse:
    """Shipment breakdowns with `by=` grouping (contract shape exactly)."""
    from app.kpis import (
        BY_COLUMN,
        apply_filters,
        canceled_shipment_count,
        compute_groups,
        eligible_shipments,
    )

    manifest, _, tables = _kpi_or_raise(session_id)
    filters = _parse_kpi_filters(
        session_id=session_id,
        state=manifest.state,
        date_from=date_from,
        date_to=date_to,
        market=market,
        region=region,
        category=category,
        department=department,
        shipping_mode=shipping_mode,
        order_status=order_status,
        shipment_outcome=shipment_outcome,
        customer_segment=customer_segment,
    )
    grouping: str | None = None
    if by is not None:
        grouping = by.strip()
        if grouping not in BY_COLUMN:
            raise IngestionError(
                INVALID_GROUPING,
                STAGE_ANALYZING,
                "Unknown breakdown dimension. Use one of the governed grouping fields.",
                422,
                {"by": by},
                session_id=session_id,
                session_state=manifest.state,
            )
    _, orders = apply_filters(tables, filters)
    eligible = eligible_shipments(orders)
    n_cancelled = canceled_shipment_count(orders)
    exclusions = (
        f"{n_cancelled} shipping-cancelled orders excluded"
        f"{'; ' + filters.describe() if filters.is_active() else ''}"
    )
    groups = [
        KpiGroup(key=key, kpis=kpis)
        for key, kpis in (
            compute_groups(tables, grouping, filters, delivery=True)
            if grouping is not None
            else []
        )
    ]
    return KpiDeliveryResponse(
        data=KpiDeliveryData(
            groups=groups,
            eligibleOrders=int(len(eligible)),
            exclusions=exclusions,
        ),
        meta=_base_meta(
            session_id=session_id,
            session_state=manifest.state,
            filters=filters.as_meta(),
        ),
        error=None,
    )


@router.get(
    "/sessions/{session_id}/kpis/commercial", response_model=KpiCommercialResponse
)
async def session_kpis_commercial(
    session_id: str,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    market: str | None = None,
    region: str | None = None,
    category: str | None = None,
    department: str | None = None,
    shipping_mode: str | None = None,
    order_status: str | None = None,
    shipment_outcome: str | None = None,
    customer_segment: str | None = None,
    by: str | None = None,
) -> KpiCommercialResponse:
    """Value/profit/discount/units breakdowns (contract shape exactly)."""
    from app.kpis import (
        BY_COLUMN,
        apply_filters,
        compute_commercial,
        compute_groups,
    )

    manifest, _, tables = _kpi_or_raise(session_id)
    filters = _parse_kpi_filters(
        session_id=session_id,
        state=manifest.state,
        date_from=date_from,
        date_to=date_to,
        market=market,
        region=region,
        category=category,
        department=department,
        shipping_mode=shipping_mode,
        order_status=order_status,
        shipment_outcome=shipment_outcome,
        customer_segment=customer_segment,
    )
    grouping: str | None = None
    if by is not None:
        grouping = by.strip()
        if grouping not in BY_COLUMN:
            raise IngestionError(
                INVALID_GROUPING,
                STAGE_ANALYZING,
                "Unknown breakdown dimension. Use one of the governed grouping fields.",
                422,
                {"by": by},
                session_id=session_id,
                session_state=manifest.state,
            )
    items, orders = apply_filters(tables, filters)
    scoped = compute_commercial(items, orders, filters)
    by_id = {kpi.id: kpi for kpi in scoped}
    weighted = KpiWeightedRates(
        profitMargin=by_id["kpi.margin.profit"].value
        if isinstance(by_id["kpi.margin.profit"].value, str)
        else None,
        discountRate=by_id["kpi.rate.discount"].value
        if isinstance(by_id["kpi.rate.discount"].value, str)
        else None,
    )
    if filters.order_status is not None:
        status_scope = f"order_status={filters.order_status}"
    else:
        status_scope = "all-status"
    groups = [
        KpiGroup(key=key, kpis=kpis)
        for key, kpis in (
            compute_groups(tables, grouping, filters, delivery=False)
            if grouping is not None
            else []
        )
    ]
    return KpiCommercialResponse(
        data=KpiCommercialData(
            groups=groups,
            statusScope=status_scope,
            weightedRates=weighted,
        ),
        meta=_base_meta(
            session_id=session_id,
            session_state=manifest.state,
            filters=filters.as_meta(),
        ),
        error=None,
    )
