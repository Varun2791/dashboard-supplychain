"""Phase-4 session routes: upload, status, and reset.

Handlers validate transport, call the ingestion/session services, and map
domain errors to the typed error envelope. No supply-chain logic lives here:
a structurally valid CSV is accepted regardless of its columns.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile

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
    NOT_READY,
    SCHEMA_MISSING_COLUMN,
    SESSION_EXPIRED,
    SESSION_NOT_FOUND,
    STAGE_VALIDATING,
    IngestionError,
)
from app.schema_validation import run_schema_validation
from app.schemas import (
    STATE_EXPIRED,
    STATE_FAILED,
    STATE_VALIDATING,
    ApiErrorModel,
    EnvelopeMeta,
    ErrorResponse,
    SchemaMappingView,
    SchemaReportData,
    SchemaReportResponse,
    SessionDeletedData,
    SessionDeletedResponse,
    SessionStatusData,
    SessionStatusResponse,
    UploadAcceptedData,
    UploadAcceptedResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


def _base_meta(
    *,
    session_id: str | None = None,
    session_state: str | None = None,
) -> EnvelopeMeta:
    """Envelope metadata stamped per response (versions read live)."""
    return EnvelopeMeta(
        appVersion=settings.app_version,
        schemaVersion=settings.schema_version,
        generatedAt=session_store.utcnow_naive_iso(),
        sessionId=session_id,
        sessionState=session_state,
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
    manifest.lastAccessedAt = now_iso
    manifest.updatedAt = now_iso
    session_store.write_manifest(paths, manifest)
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
