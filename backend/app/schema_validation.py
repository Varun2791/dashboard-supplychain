"""Phase-5 source-schema recognition (headers only, never values).

Reads the first header row of the immutable `raw.csv`, classifies every
original header against the governed V1 registry
(`app/schema_registry.py`), and decides compatibility:

- all required source fields present → schema report artifact in
  `derived/`, session advances VALIDATING → PROFILING, then stops;
- any required source field missing → terminal FAILED with raw/derived
  removal per ADR-028; only the privacy-safe manifest/error metadata stays.

Bounded by header size: no row reads, no pandas, no value validation, no
derivations. Runs as a framework-local post-response task scheduled by the
upload route (never inside the 202 request itself), plus startup recovery
for sessions left VALIDATING by a restart. GET status/schema endpoints are
purely observational and never execute validation.
"""

from __future__ import annotations

import csv
import logging
import os
import shutil
from datetime import datetime

from app import sessions as session_store
from app.config import settings
from app.ingestion_errors import (
    INTERNAL_STAGE_ERROR,
    SCHEMA_MISSING_COLUMN,
    STAGE_VALIDATING,
    IngestionError,
)
from app.schema_registry import (
    REQUIRED_MAPPINGS,
    SCHEMA_REFERENCE_ID,
    SOURCE_GRAIN_ORDER_ITEM,
    TIMESTAMP_CONTRACTS,
    is_audit_only,
    is_redundant,
    lookup,
)
from app.schemas import (
    STATE_FAILED,
    STATE_PROFILING,
    STATE_VALIDATING,
    ApiErrorModel,
    SchemaFieldMapping,
    SchemaReport,
    SchemaRuleOutcome,
    SchemaTimestampContract,
    SessionManifest,
)

logger = logging.getLogger(__name__)


def validate_headers(source_headers: list[str]) -> SchemaReport:
    """Classify headers deterministically (pure: no I/O, no values).

    Order-independent: the same header set in any column order yields the
    same report. Original header text is always preserved.
    """
    mapping: list[SchemaFieldMapping] = []
    seen_canonical: set[str] = set()
    redundant: list[str] = []
    audit_only: list[str] = []
    unrecognized: list[str] = []
    for original in source_headers:
        entry = lookup(original)
        if entry is not None:
            seen_canonical.add(entry.canonical_field)
            mapping.append(
                SchemaFieldMapping(
                    source=original,
                    canonical=entry.canonical_field,
                    fieldClass=("required" if entry.required else "optional"),
                    required=entry.required,
                    role=entry.role,
                )
            )
        elif is_redundant(original):
            redundant.append(original)
            mapping.append(
                SchemaFieldMapping(
                    source=original,
                    canonical=None,
                    fieldClass="redundant",
                    required=False,
                    role="governed redundant copy; retained in raw only",
                )
            )
        elif is_audit_only(original):
            audit_only.append(original)
            mapping.append(
                SchemaFieldMapping(
                    source=original,
                    canonical=None,
                    fieldClass="excluded",
                    required=False,
                    role="leakage-flagged audit evidence; never classification input",
                )
            )
        else:
            unrecognized.append(original)
            mapping.append(
                SchemaFieldMapping(
                    source=original,
                    canonical=None,
                    fieldClass="unknown",
                    required=False,
                    role="unrecognized extra; quarantined to raw-only scope",
                )
            )
    missing = [
        entry.source_header
        for entry in REQUIRED_MAPPINGS
        if entry.canonical_field not in seen_canonical
    ]
    rule_outcomes: list[SchemaRuleOutcome] = []
    if missing:
        rule_outcomes.append(
            SchemaRuleOutcome(
                ruleId="DQ-SCHEMA-001",
                severity="ERROR",
                message=(
                    "Required source column(s) missing: "
                    + ", ".join(missing)
                    + ". Blocks CANONICALIZING and KPI_ANALYSIS."
                ),
            )
        )
    if unrecognized:
        rule_outcomes.append(
            SchemaRuleOutcome(
                ruleId="DQ-SCHEMA-003",
                severity="INFO",
                message=(
                    f"{len(unrecognized)} unrecognized column(s) "
                    "quarantined to raw-only scope."
                ),
            )
        )
    now = session_store.utcnow_naive_iso()
    return SchemaReport(
        schemaReferenceId=SCHEMA_REFERENCE_ID,
        compatible=not missing,
        sourceGrain=SOURCE_GRAIN_ORDER_ITEM,
        sourceColumns=list(source_headers),
        mapping=mapping,
        missingRequired=missing,
        unrecognized=unrecognized,
        redundant=redundant,
        auditOnly=audit_only,
        timestampContracts=[
            SchemaTimestampContract(
                canonicalField=item.canonical_field,
                sourceHeader=item.source_header,
                parse=item.parse,
                timezoneNaive=item.timezone_naive,
            )
            for item in TIMESTAMP_CONTRACTS
        ],
        ruleOutcomes=rule_outcomes,
        appVersion=settings.app_version,
        schemaVersion=settings.schema_version,
        decidedAt=now,
    )


def read_source_headers(raw_path: str, encoding: str) -> list[str]:
    """Return the first non-blank header row; bounded, values never read."""
    codec = "utf-8-sig" if encoding in ("utf-8", "utf-8-sig") else "latin-1"
    with open(raw_path, encoding=codec, newline="") as handle:
        for row in csv.reader(handle):
            if row:
                return list(row)
    return []


def strip_session_payloads(paths: session_store.SessionPaths) -> None:
    """ADR-028 terminal-failure cleanup: remove raw + derived/exports files.

    Keeps the session directory and manifest slot; only privacy-safe
    manifest/error metadata may be rewritten afterwards.
    """
    try:
        if os.path.exists(paths.raw):
            os.remove(paths.raw)
        for directory in (paths.derived, paths.exports):
            if not os.path.isdir(directory):
                continue
            for name in os.listdir(directory):
                target = os.path.join(directory, name)
                if os.path.isdir(target) and not os.path.islink(target):
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    try:
                        os.remove(target)
                    except OSError:
                        pass
    except OSError:
        pass


def _missing_columns_error(report: SchemaReport) -> IngestionError:
    missing = report.missingRequired
    count = len(missing)
    noun = "column" if count == 1 else "columns"
    return IngestionError(
        SCHEMA_MISSING_COLUMN,
        STAGE_VALIDATING,
        f"The file is missing {count} required {noun}: "
        + ", ".join(missing)
        + ". V1 supports DataCo-compatible CSV files: "
        "add the missing columns and upload again.",
        422,
        {
            "missing": missing,
            "recognized": len(report.sourceColumns) - len(missing),
            "columnCount": len(report.sourceColumns),
        },
    )


def ensure_schema_validated(
    paths: session_store.SessionPaths, manifest: SessionManifest, now_iso: str
) -> SessionManifest:
    """Run Phase-5 validation once if still pending; otherwise return stored.

    Idempotent deterministic core shared by the post-response worker and
    startup recovery. Sessions already past VALIDATING (or already carrying
    a schema artifact) are returned untouched. Compatible sessions advance
    to PROFILING with the report artifact; incompatible sessions transition
    to FAILED with raw/derived removal and manifest-only error retention.
    A schema artifact left on disk without its manifest pointer is simply
    recomputed (bounded header-only read, deterministic same content).
    """
    if manifest.state != STATE_VALIDATING or manifest.schemaArtifact is not None:
        return manifest
    try:
        headers = read_source_headers(paths.raw, manifest.encoding)
        report = validate_headers(headers)
    except OSError as exc:
        logger.warning("schema_validation_io_error")
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_VALIDATING,
            "The stored upload could not be read. Upload the file again.",
            500,
            {},
        ) from exc
    if not report.compatible:
        strip_session_payloads(paths)
        error = _missing_columns_error(report)
        transitioned = manifest.model_copy(
            update={
                "state": STATE_FAILED,
                "stage": STATE_VALIDATING,
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
        session_store.write_manifest(paths, transitioned)
        logger.info("schema_validation_failed missing=%d", len(report.missingRequired))
        return transitioned
    session_store.write_schema_report(paths, report)
    transitioned = manifest.model_copy(
        update={
            "state": STATE_PROFILING,
            "stage": STATE_PROFILING,
            "progress": session_store.make_profiling_progress(),
            "schemaArtifact": os.path.join(
                session_store.DERIVED_DIRNAME, session_store.SCHEMA_ARTIFACT_FILENAME
            ),
            "error": None,
            "updatedAt": now_iso,
            "lastAccessedAt": now_iso,
        }
    )
    session_store.write_manifest(paths, transitioned)
    logger.info(
        "schema_validated mapped=%d unrecognized=%d",
        len(report.sourceColumns) - len(report.unrecognized),
        len(report.unrecognized),
    )
    return transitioned


__all__ = [
    "ensure_schema_validated",
    "read_source_headers",
    "recover_validating_sessions",
    "run_schema_validation",
    "strip_session_payloads",
    "validate_headers",
]


# In-process guard against duplicate validation runs for one session.
# Deployment assumption (honest): local V1 single application process. The
# guarded section contains no awaits and the transition is idempotent over
# atomic renames, so this set only ever skips redundant work; cross-process
# duplicates remain possible but harmless (deterministic same content).
_VALIDATING_IN_PROGRESS: set[str] = set()


def run_schema_validation(session_id: str) -> SessionManifest | None:
    """Execute one bounded validation for a session (worker body).

    On success the Phase-6 profiling worker is chained inline (same
    framework-local runner): compatible sessions therefore settle at
    CLEANING once both steps complete. Safe against reset races: a deleted
    session (no manifest) is a no-op and is never resurrected. Returns the
    resulting manifest, or None when there was nothing to do.
    """
    if not session_store.is_valid_session_id(session_id):
        return None
    if session_id in _VALIDATING_IN_PROGRESS:
        return None
    _VALIDATING_IN_PROGRESS.add(session_id)
    try:
        paths = session_store.session_paths(settings.session_root, session_id)
        manifest = session_store.read_manifest(paths)
        if manifest is None:
            return None
        result = ensure_schema_validated(
            paths, manifest, session_store.utcnow_naive_iso()
        )
        if result.state == STATE_PROFILING and result.profileArtifact is None:
            # Local import: profiling owns the reverse dependency
            # (it reuses the terminal-cleanup helper defined here).
            from app.profiling import run_profiling

            profiled = run_profiling(session_id)
            return profiled if profiled is not None else result
        return result
    finally:
        _VALIDATING_IN_PROGRESS.discard(session_id)


def recover_validating_sessions(session_root: str) -> int:
    """Startup recovery: validate leftover VALIDATING sessions, count them.

    Covers the crash window between the 202 response and the post-response
    task (interrupted tasks leave no queue behind by design). Only the
    already-implemented Phase-5 step runs; later stages are never started,
    expired/corrupt trees are left to the sweep, and valid resumable
    sessions are never deleted.
    """
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
            or manifest.state != STATE_VALIDATING
            or manifest.schemaArtifact is not None
        ):
            continue
        if session_store.is_expired(manifest, datetime.now()):
            continue
        run_schema_validation(entry)
        recovered += 1
    if recovered:
        logger.info("schema_recovery_validated=%d", recovered)
    return recovered
