"""Phase-6 orchestration: stage the raw file, run detection, persist, advance.

Pure value-level detection lives in :mod:`app.profile_checks` (no I/O
there). This module owns everything impure: integrity checks, the single
governed ``pandas.read_csv`` staging read (pyarrow-backed strings plus a
governed column projection), artifact persistence, lifecycle transitions,
the post-response pipeline hook, and startup recovery.

Lifecycle: success advances ``PROFILING -> CLEANING`` and stops (no
cleaning runs here); a malformed body fails terminally per DQ-FILE-005
with ADR-028 raw/derived removal. ``ERROR`` findings on DQ-KEY-001,
DQ-DATE-001, and DQ-GRAIN-001 name the exact downstream stage they gate
and travel with the session into CLEANING; they do not stop profiling.

Execution model: these workers are synchronous and run through the
existing framework-local post-response runner (``BackgroundTasks``).
Starlette executes synchronous background tasks via ``run_in_threadpool``,
so full-file pandas work runs on a worker thread without blocking the
event loop. No Celery/Redis/DB/queue was added. Honest local assumption
(as in Phase 5): single application process; an in-process guard prevents
duplicate profiling of one session, atomic artifact writes guard against
partial artifacts, and reset races resolve to no-resurrection.

Resource discipline (ADR-027): one full read with pyarrow-backed string
staging projected to governed profiling columns (unknown extras and
excluded columns never materialize), then immediate analysis. Per-column
vectorized operations, no full-copy chains, intermediates released. Peak
memory follows the accepted V1 assumption in architecture.md section 2;
no pandas memory multiplier is claimed here beyond that governance. No
chunking per ADR-027; chunking would complicate cross-row checks
(duplicate keys, invariance) with no measured benefit.

``raw.csv`` is never written, normalized, transcoded, or extended here.
A streaming SHA-256 is verified against the manifest before parsing, and
tests assert byte-identity after profiling.
"""

from __future__ import annotations

import hashlib
import logging
import os

import pandas as pd

from app import sessions as session_store
from app.config import settings
from app.ingestion_errors import (
    INTERNAL_STAGE_ERROR,
    MALFORMED_CSV,
    STAGE_PROFILING,
    IngestionError,
)
from app.profile_checks import (
    INT_FIELDS,
    MONEY_FIELDS,
    RULE_ORDER,
    RULES_DEFERRED,
    TIMESTAMP_FIELDS,
    ProfileInputs,
    RuleResult,
    evaluate_frame,
    invariance_by_field,
    missing_mask,
    parse_int_values,
    parse_money_valid,
    parse_timestamps,
    stripped,
)
from app.schema_registry import is_audit_only
from app.schema_validation import read_source_headers, strip_session_payloads
from app.schemas import (
    STATE_CLEANING,
    STATE_FAILED,
    STATE_PROFILING,
    ApiErrorModel,
    DataQualityIssue,
    InvarianceConflicts,
    InvarianceFieldConflicts,
    ProfileCardinality,
    ProfileData,
    ProfileDuplicates,
    ProfileMissingness,
    ProfilingArtifact,
    RuleContext,
    SchemaReport,
    SessionManifest,
)

logger = logging.getLogger(__name__)


def sha256_file(path: str) -> str:
    """Stream SHA-256 of a file without loading it into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def read_staged_frame(raw_path: str, encoding: str, usecols: list[str]) -> pd.DataFrame:
    """Single full read with governed column projection (ADR-026, ADR-027).

    ``dtype="string[pyarrow]"`` keeps every cell a pyarrow-backed string so
    pandas never invents missingness and identifiers stay strings, never
    floats (ADR-026). ``keep_default_na=False`` keeps empty fields empty.
    ``usecols`` restricts the load to governed profiling columns: unknown
    extras and excluded columns are never materialized, never semantically
    profiled, and never hashed into duplicate identity. Ragged rows raise
    and surface as DQ-FILE-005. Raises ``IngestionError`` (never a raw
    pandas exception) on failure.
    """
    codec = "utf-8-sig" if encoding in ("utf-8", "utf-8-sig") else "latin-1"
    try:
        frame = pd.read_csv(
            raw_path,
            dtype="string[pyarrow]",
            keep_default_na=False,
            encoding=codec,
            engine="c",
            on_bad_lines="error",
            usecols=usecols,
        )
    except pd.errors.ParserError as exc:
        raise IngestionError(
            MALFORMED_CSV,
            STAGE_PROFILING,
            "The CSV body is malformed (broken quoting or a truncated "
            "file). Fix the file structure and upload again.",
            422,
            {},
        ) from exc
    except UnicodeDecodeError as exc:
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_PROFILING,
            "The stored upload could not be decoded. Upload the file again.",
            500,
            {},
        ) from exc
    except Exception as exc:
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_PROFILING,
            "The upload could not be profiled. Upload the file again.",
            500,
            {},
        ) from exc
    return frame


def build_profile_inputs(report: SchemaReport) -> ProfileInputs:
    """Select governed profiling columns from the Phase-5 mapping.

    Only required/optional entries (mapped to canonical fields) participate,
    in source order. Redundant copies and unknown extras stay inert/raw-only.
    The leakage-flagged ``Late_delivery_risk`` header is located for the
    diagnostic agreement check only (DQ-BUSINESS-003); it never becomes an
    analytics input.
    """
    col_of: dict[str, str] = {}
    for entry in report.mapping:
        if entry.canonical is not None and entry.fieldClass in (
            "required",
            "optional",
        ):
            col_of[entry.canonical] = entry.source
    audit_header: str | None = None
    for extra in report.auditOnly:
        if is_audit_only(extra):
            audit_header = extra
            break
    return ProfileInputs(
        col_of=col_of,
        audit_header=audit_header,
        source_headers=list(report.sourceColumns),
    )


def parse_failures_by_field(
    frame: pd.DataFrame, inputs: ProfileInputs
) -> dict[str, int]:
    """Non-missing values failing governed type parsing, per canonical field.

    Kept separate from missing counts everywhere (profile statistics and
    rule populations). Unparseable values are never replaced with zero.
    """
    failures: dict[str, int] = {}
    for canonical, column in inputs.col_of.items():
        if canonical in INT_FIELDS:
            parsed = parse_int_values(stripped(frame, column))
            failures[canonical] = int(
                ((~missing_mask(frame, column)) & parsed.isna()).sum()
            )
        elif canonical in MONEY_FIELDS:
            valid = parse_money_valid(stripped(frame, column))
            failures[canonical] = int(((~missing_mask(frame, column)) & (~valid)).sum())
        elif canonical in TIMESTAMP_FIELDS:
            parsed_ts = parse_timestamps(stripped(frame, column))
            failures[canonical] = int(
                ((~missing_mask(frame, column)) & parsed_ts.isna()).sum()
            )
        else:
            failures[canonical] = 0
    return failures


def build_profile_data(
    frame: pd.DataFrame,
    inputs: ProfileInputs,
    results: list[RuleResult],
    exact_dupes: int,
) -> ProfileData:
    """Assemble the public profile projection (counts only, never values)."""
    from app.schema_registry import SOURCE_GRAIN_ORDER_ITEM

    rows = int(len(frame))
    failures = parse_failures_by_field(frame, inputs)
    missingness: list[ProfileMissingness] = []
    cardinality: list[ProfileCardinality] = []
    for canonical, column in inputs.col_of.items():
        values = stripped(frame, column)
        miss = missing_mask(frame, column)
        missing = int(miss.sum())
        missingness.append(
            ProfileMissingness(
                field=canonical,
                source=column,
                missing=missing,
                total=rows,
                rate=round(missing / rows, 4) if rows else 0.0,
                parseFailures=failures[canonical],
            )
        )
        cardinality.append(
            ProfileCardinality(
                field=canonical,
                source=column,
                distinct=int(values[~miss].nunique()),
            )
        )
    key_dupes = 0
    for result in results:
        if result.rule_id == "DQ-KEY-001":
            key_dupes = result.count
    orders_checked, conflicting, by_field = invariance_by_field(frame, inputs)
    return ProfileData(
        rows=rows,
        columns=len(inputs.col_of),
        grain=SOURCE_GRAIN_ORDER_ITEM,
        missingness=missingness,
        cardinality=cardinality,
        duplicates=ProfileDuplicates(exact=exact_dupes, keyDupes=key_dupes),
        invarianceConflicts=InvarianceConflicts(
            ordersChecked=orders_checked,
            conflictingOrders=conflicting,
            byField=[
                InvarianceFieldConflicts(field=f, conflictingOrders=c)
                for f, c in by_field.items()
            ],
        ),
    )


def rules_evaluated(inputs: ProfileInputs) -> list[str]:
    """Rule IDs actually executed for this session's mapped field set."""
    evaluated = ["DQ-FILE-005"]  # the successful staging read is the check
    for rule_id in RULE_ORDER:
        if rule_id == "DQ-CAT-003" and "customer_segment" not in inputs.col_of:
            continue
        if rule_id == "DQ-BUSINESS-003" and inputs.audit_header is None:
            continue
        evaluated.append(rule_id)
    return evaluated


def build_profiling_artifact(
    *,
    session_id: str,
    source_sha256: str,
    profile: ProfileData,
    results: list[RuleResult],
    evaluated: list[str],
    now_iso: str,
) -> ProfilingArtifact:
    """Assemble the typed derived artifact (counts and rule IDs only)."""
    issues = [
        DataQualityIssue(
            ruleId=result.rule_id,
            severity=result.severity,
            count=result.count,
            treatment=result.treatment,
            blockedStage=result.blocked_stage,
        )
        for result in results
    ]
    return ProfilingArtifact(
        sessionId=session_id,
        appVersion=settings.app_version,
        schemaVersion=settings.schema_version,
        sourceSha256=source_sha256,
        sourceRows=profile.rows,
        mappedFields=profile.columns,
        profile=profile,
        issues=issues,
        issueMessages={result.rule_id: result.message for result in results},
        ruleContext={
            result.rule_id: RuleContext(
                title=result.title,
                fields=list(result.fields),
                grain=result.grain,
                population=result.population,
            )
            for result in results
        },
        rulesEvaluated=evaluated,
        rulesDeferred=list(RULES_DEFERRED),
        profiledAt=now_iso,
    )


def _fail_profiling(
    paths: session_store.SessionPaths,
    manifest: SessionManifest,
    error: IngestionError,
    now_iso: str,
) -> SessionManifest:
    """Terminal profiling failure: ADR-028 raw/derived removal, metadata kept.

    The transition is returned only if its manifest write succeeds; a
    failed write returns the pre-transition manifest so callers never
    observe a state the disk does not carry.
    """
    strip_session_payloads(paths)
    transitioned = manifest.model_copy(
        update={
            "state": STATE_FAILED,
            "stage": STAGE_PROFILING,
            "error": ApiErrorModel(
                code=error.code,
                stage=error.stage,
                message=error.message,
                details=error.details,
            ),
            "updatedAt": now_iso,
            "lastAccessedAt": now_iso,
        }
    )
    try:
        session_store.write_manifest(paths, transitioned)
    except OSError:
        return manifest
    logger.info("profiling_failed code=%s", error.code)
    return transitioned


def _artifact_matches_session(
    stored: ProfilingArtifact,
    manifest: SessionManifest,
    paths: session_store.SessionPaths,
) -> bool:
    """Provenance gate before adopting an on-disk profiling artifact.

    Adoption requires: the artifact names this session, pins this session's
    source hash and pipeline versions, validates as the typed artifact
    (established by the typed read), has its preceding schema report
    present, and has the immutable raw still present. Anything else falls
    through to a full recompute that atomically overwrites the artifact.
    """
    return (
        stored.sessionId == manifest.sessionId
        and stored.sourceSha256 == manifest.sha256
        and stored.appVersion == settings.app_version
        and stored.schemaVersion == settings.schema_version
        and session_store.read_schema_report(paths) is not None
        and os.path.isfile(paths.raw)
    )


def ensure_profiled(
    paths: session_store.SessionPaths, manifest: SessionManifest, now_iso: str
) -> SessionManifest:
    """Run Phase-6 profiling once if still pending; otherwise return stored.

    Idempotent core shared by the validation-chained pipeline and startup
    recovery. Sessions already past PROFILING (or already carrying a
    profiling artifact) are returned untouched. A profiling artifact left
    on disk without its manifest pointer is adopted only after provenance
    checks (session, source hash, versions, preceding schema report, raw
    presence); otherwise it is recomputed and atomically overwritten, never
    silently trusted. Success advances the session to CLEANING with the
    report artifact; a malformed body fails terminally per DQ-FILE-005 with
    ADR-028 cleanup. Never mutates raw.
    """
    if manifest.state != STATE_PROFILING or manifest.profileArtifact is not None:
        return manifest
    stored = session_store.read_profiling_report(paths)
    if stored is not None and _artifact_matches_session(stored, manifest, paths):
        transitioned = manifest.model_copy(
            update={
                "state": STATE_CLEANING,
                "stage": STATE_CLEANING,
                "progress": session_store.make_cleaning_progress(),
                "profileArtifact": (
                    f"{session_store.DERIVED_DIRNAME}/"
                    f"{session_store.PROFILING_ARTIFACT_FILENAME}"
                ),
                "error": None,
                "updatedAt": now_iso,
                "lastAccessedAt": now_iso,
            }
        )
        try:
            session_store.write_manifest(paths, transitioned)
        except OSError:
            return manifest
        logger.info("profiling_adopted")
        return transitioned
    report = session_store.read_schema_report(paths)
    if report is None:
        error = IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_PROFILING,
            "The schema report could not be read. Upload the file again.",
            500,
            {},
        )
        return _fail_profiling(paths, manifest, error, now_iso)
    if not os.path.isfile(paths.raw):
        error = IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_PROFILING,
            "The stored upload could not be read. Upload the file again.",
            500,
            {},
        )
        return _fail_profiling(paths, manifest, error, now_iso)
    if sha256_file(paths.raw) != manifest.sha256:
        error = IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_PROFILING,
            "The stored upload failed its integrity check. Upload the file again.",
            500,
            {},
        )
        return _fail_profiling(paths, manifest, error, now_iso)
    inputs = build_profile_inputs(report)
    governed = set(inputs.col_of.values())
    if inputs.audit_header is not None:
        governed.add(inputs.audit_header)
    # Header integrity stays Phase-5 authority: a bounded first-row read
    # must reproduce the validated header list before any full-file work.
    try:
        staged_headers = read_source_headers(paths.raw, manifest.encoding)
    except OSError:
        logger.warning("profiling_header_io_error")
        return _fail_profiling(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_PROFILING,
                "The stored upload could not be read. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    if staged_headers != report.sourceColumns:
        error = IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_PROFILING,
            "The stored upload failed its integrity check. Upload the file again.",
            500,
            {},
        )
        return _fail_profiling(paths, manifest, error, now_iso)
    try:
        working = read_staged_frame(
            paths.raw,
            manifest.encoding,
            [c for c in report.sourceColumns if c in governed],
        )
    except IngestionError as exc:
        return _fail_profiling(paths, manifest, exc, now_iso)
    # Exact-duplicate identity spans the loaded governed columns only:
    # unknown extras and excluded columns are never materialized, so they
    # can neither leak nor affect identity. No DQ rule owns this stat.
    exact_dupes = int(working.duplicated(keep="first").sum()) if len(working) else 0
    _, _, results = evaluate_frame(working, inputs)
    profile = build_profile_data(working, inputs, results, exact_dupes)
    evaluated = rules_evaluated(inputs)
    artifact = build_profiling_artifact(
        session_id=manifest.sessionId,
        source_sha256=manifest.sha256,
        profile=profile,
        results=results,
        evaluated=evaluated,
        now_iso=now_iso,
    )
    del working
    try:
        session_store.write_profiling_report(paths, artifact)
    except OSError:
        return manifest
    transitioned = manifest.model_copy(
        update={
            "state": STATE_CLEANING,
            "stage": STATE_CLEANING,
            "progress": session_store.make_cleaning_progress(),
            "profileArtifact": (
                f"{session_store.DERIVED_DIRNAME}/"
                f"{session_store.PROFILING_ARTIFACT_FILENAME}"
            ),
            "error": None,
            "updatedAt": now_iso,
            "lastAccessedAt": now_iso,
        }
    )
    try:
        session_store.write_manifest(paths, transitioned)
    except OSError:
        return manifest
    logger.info(
        "profiled rows=%d fields=%d issues=%d",
        profile.rows,
        profile.columns,
        len(results),
    )
    return transitioned


__all__ = [
    "build_profile_data",
    "build_profile_inputs",
    "build_profiling_artifact",
    "ensure_profiled",
    "parse_failures_by_field",
    "read_staged_frame",
    "recover_profiling_sessions",
    "rules_evaluated",
    "run_profiling",
    "sha256_file",
]


# In-process guard against duplicate profiling runs for one session.
# Same honesty contract as the Phase-5 guard: local V1 single process,
# no awaits inside the guarded section, idempotent atomic transitions.
_PROFILING_IN_PROGRESS: set[str] = set()


def run_profiling(session_id: str) -> SessionManifest | None:
    """Execute one profiling pass for a session (pipeline/recovery body).

    Safe against reset races: a deleted session (no manifest) is a no-op
    and is never resurrected. Returns the resulting manifest, or None when
    there was nothing to do.
    """
    if not session_store.is_valid_session_id(session_id):
        return None
    if session_id in _PROFILING_IN_PROGRESS:
        return None
    _PROFILING_IN_PROGRESS.add(session_id)
    try:
        paths = session_store.session_paths(settings.session_root, session_id)
        manifest = session_store.read_manifest(paths)
        if manifest is None:
            return None
        return ensure_profiled(paths, manifest, session_store.utcnow_naive_iso())
    finally:
        _PROFILING_IN_PROGRESS.discard(session_id)


def recover_profiling_sessions(session_root: str) -> int:
    """Startup recovery: profile leftover PROFILING sessions, count them.

    Covers the crash window between validation success and profiling
    completion. Only the already-implemented Phase-6 step runs; later
    stages are never started, expired trees are left to the sweep, and
    valid resumable sessions are never deleted.
    """
    from datetime import datetime

    recovered = 0
    try:
        entries = sorted(os.listdir(session_root))
    except FileNotFoundError:
        return 0
    for entry in entries:
        if not session_store.is_valid_session_id(entry):
            continue
        paths = session_store.session_paths(session_root, entry)
        manifest = session_store.read_manifest(paths)
        if (
            manifest is None
            or manifest.state != STATE_PROFILING
            or manifest.profileArtifact is not None
        ):
            continue
        if session_store.read_profiling_report(paths) is not None:
            continue
        if session_store.is_expired(manifest, datetime.now()):
            continue
        run_profiling(entry)
        recovered += 1
    if recovered:
        logger.info("profiling_recovery_profiled=%d", recovered)
    return recovered
