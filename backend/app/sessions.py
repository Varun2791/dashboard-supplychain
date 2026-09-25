"""Session filesystem lifecycle (ADR-028, docs/architecture.md section 4).

Layout per session::

    .tmp/sessions/{uuid}/
        manifest.json   # typed Phase-4 metadata only (never cell values)
        raw.csv         # immutable, filesystem read-only, exact upload bytes
        derived/        # later phases (created empty in Phase 4)
        exports/        # later phases (created empty in Phase 4)

Rules honored here: UUID-only directory names (no path traversal), atomic
manifest writes (temp + rename), read-only raw, idempotent reset, TTL expiry
with a sliding `lastAccessedAt`, and a restart sweep that removes corrupt,
terminal-failed, or expired trees while logging counts only.

Immutability note: the guarantee is single promotion (`os.replace` of the
validated temp file inside the session directory, so a partially accepted
raw can never be observed), not the chmod flag, which remains only as
defense-in-depth. No service here exposes a raw-write operation: the only
raw transitions are promote-once and delete-whole-tree.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import ValidationError

from app.config import settings
from app.schemas import (
    FORWARD_STATES,
    STATE_CANONICALIZING,
    STATE_CLEANING,
    STATE_FAILED,
    STATE_PROFILING,
    STATE_UPLOADING,
    STATE_VALIDATING,
    CleaningArtifact,
    ProfilingArtifact,
    SchemaReport,
    SessionManifest,
    SessionProgress,
)

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "manifest.json"
RAW_FILENAME = "raw.csv"
PARTIAL_FILENAME = ".upload.part"
DERIVED_DIRNAME = "derived"
EXPORTS_DIRNAME = "exports"
SCHEMA_ARTIFACT_FILENAME = "schema_report.json"
PROFILING_ARTIFACT_FILENAME = "profiling_report.json"
CLEANING_ARTIFACT_FILENAME = "cleaning_report.json"
CLEANED_FILENAME = "cleaned.csv"


def utcnow_naive_iso() -> str:
    """Current timezone-naive timestamp (source supplies no timezone)."""
    return datetime.now().replace(microsecond=0).isoformat()


def new_session_id() -> str:
    """One server-generated UUIDv4: encodes no user/file/time information."""
    return str(uuid.uuid4())


def is_valid_session_id(candidate: str) -> bool:
    """UUID format gate: anything else never touches the filesystem."""
    try:
        parsed = uuid.UUID(candidate, version=4)
    except (ValueError, AttributeError, TypeError):
        return False
    return str(parsed) == candidate.lower()


@dataclass(frozen=True)
class SessionPaths:
    """Resolved layout for one session directory (UUID-scoped)."""

    root: str
    manifest: str
    raw: str
    partial: str
    derived: str
    exports: str


def session_paths(session_root: str, session_id: str) -> SessionPaths:
    """Build session paths. Callers must validate the ID first."""
    root = os.path.join(session_root, session_id)
    return SessionPaths(
        root=root,
        manifest=os.path.join(root, MANIFEST_FILENAME),
        raw=os.path.join(root, RAW_FILENAME),
        partial=os.path.join(root, PARTIAL_FILENAME),
        derived=os.path.join(root, DERIVED_DIRNAME),
        exports=os.path.join(root, EXPORTS_DIRNAME),
    )


def create_session_layout(paths: SessionPaths) -> None:
    """Create the empty session tree (raw/manifest land here later)."""
    os.makedirs(paths.derived, exist_ok=False)
    os.makedirs(paths.exports, exist_ok=False)


def remove_session_tree(paths: SessionPaths) -> None:
    """Delete the complete session tree; missing trees are a no-op."""
    shutil.rmtree(paths.root, ignore_errors=True)


def _unique_tmp_path(final_path: str) -> str:
    """Collision-free temp sibling for an atomic write.

    Concurrent writers (status touches vs pipeline transitions, possibly in
    different threads) must never share one fixed ``.tmp`` name: a shared
    name lets one writer's rename unlink the other's pending temp file and
    fail its rename with ``FileNotFoundError``. Unique names keep every
    rename total; last writer wins, readers never see partial content.
    """
    return f"{final_path}.{uuid.uuid4().hex}.tmp"


def _atomic_write_json(final_path: str, payload: str) -> None:
    """Write ``payload`` to ``final_path`` atomically via a unique temp file."""
    tmp_path = _unique_tmp_path(final_path)
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_path, final_path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def write_manifest(paths: SessionPaths, manifest: SessionManifest) -> None:
    """Persist the manifest atomically: temp file + rename, never partial."""
    _atomic_write_json(paths.manifest, manifest.model_dump_json())


def read_manifest(paths: SessionPaths) -> SessionManifest | None:
    """Load and validate the manifest; corrupt/missing input yields None."""
    try:
        with open(paths.manifest, encoding="utf-8") as handle:
            payload = json.load(handle)
        return SessionManifest.model_validate(payload)
    except (OSError, ValueError, ValidationError):
        return None


def read_manifest_bytes(paths: SessionPaths) -> bytes | None:
    """Raw manifest bytes for compare-and-swap touches (None when unreadable)."""
    try:
        with open(paths.manifest, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def touch_manifest_if_current(
    paths: SessionPaths, manifest: SessionManifest, now_iso: str
) -> SessionManifest:
    """Refresh sliding-TTL timestamps only if the disk still carries `manifest`.

    Status polling must never regress a concurrent pipeline transition (or
    resurrect a terminal state): the touch writes back only when the stored
    bytes still equal the manifest that was read. On mismatch (a worker
    transitioned meanwhile) the fresh stored manifest is returned untouched.
    Terminal FAILED manifests are never rewritten. Returns the manifest the
    caller should serve.
    """
    if manifest.state == STATE_FAILED:
        return manifest
    disk = read_manifest_bytes(paths)
    if disk is None:
        return manifest
    if disk != manifest.model_dump_json().encode("utf-8"):
        fresh = read_manifest(paths)
        return fresh if fresh is not None else manifest
    touched = manifest.model_copy(
        update={"lastAccessedAt": now_iso, "updatedAt": now_iso}
    )
    write_manifest(paths, touched)
    return touched


def make_validating_progress() -> SessionProgress:
    """Truthful Phase-4 progress: parked at VALIDATING, nothing faked done."""
    current_index = FORWARD_STATES.index(STATE_VALIDATING)
    return SessionProgress(
        completedStages=[STATE_UPLOADING],
        currentStage=STATE_VALIDATING,
        remainingStages=[stage for stage in FORWARD_STATES[current_index + 1 :]],
        note="Later processing stages are not implemented yet.",
    )


def make_profiling_progress() -> SessionProgress:
    """Truthful Phase-5 progress: VALIDATING done, PROFILING current."""
    current_index = FORWARD_STATES.index(STATE_PROFILING)
    return SessionProgress(
        completedStages=[STATE_UPLOADING, STATE_VALIDATING],
        currentStage=STATE_PROFILING,
        remainingStages=[stage for stage in FORWARD_STATES[current_index + 1 :]],
        note="Profiling is running; results are not available yet.",
    )


def make_cleaning_progress() -> SessionProgress:
    """Truthful Phase-6 progress: PROFILING done, CLEANING current."""
    current_index = FORWARD_STATES.index(STATE_CLEANING)
    return SessionProgress(
        completedStages=[STATE_UPLOADING, STATE_VALIDATING, STATE_PROFILING],
        currentStage=STATE_CLEANING,
        remainingStages=[stage for stage in FORWARD_STATES[current_index + 1 :]],
        note="Cleaning is running; results are not available yet.",
    )


def make_canonicalizing_progress() -> SessionProgress:
    """Truthful Phase-7 progress: CLEANING done, parked at CANONICALIZING."""
    current_index = FORWARD_STATES.index(STATE_CANONICALIZING)
    return SessionProgress(
        completedStages=[
            STATE_UPLOADING,
            STATE_VALIDATING,
            STATE_PROFILING,
            STATE_CLEANING,
        ],
        currentStage=STATE_CANONICALIZING,
        remainingStages=[stage for stage in FORWARD_STATES[current_index + 1 :]],
        note="Cleaning is complete; canonicalization is not implemented yet.",
    )


def profiling_artifact_path(paths: SessionPaths) -> str:
    """Derived-area location of the profiling report (raw stays untouched)."""
    return os.path.join(paths.derived, PROFILING_ARTIFACT_FILENAME)


def write_profiling_report(paths: SessionPaths, report: ProfilingArtifact) -> None:
    """Persist the profiling report atomically into `derived/`."""
    _atomic_write_json(profiling_artifact_path(paths), report.model_dump_json())


def read_profiling_report(paths: SessionPaths) -> ProfilingArtifact | None:
    """Load the profiling report; corrupt/missing input yields None."""
    try:
        with open(profiling_artifact_path(paths), encoding="utf-8") as handle:
            payload = json.load(handle)
        return ProfilingArtifact.model_validate(payload)
    except (OSError, ValueError, ValidationError):
        return None


def cleaning_artifact_path(paths: SessionPaths) -> str:
    """Derived-area location of the cleaning report (raw stays untouched)."""
    return os.path.join(paths.derived, CLEANING_ARTIFACT_FILENAME)


def cleaned_path(paths: SessionPaths) -> str:
    """Derived-area location of the internal cleaned rows (raw stays untouched)."""
    return os.path.join(paths.derived, CLEANED_FILENAME)


def write_cleaning_report(paths: SessionPaths, report: CleaningArtifact) -> None:
    """Persist the cleaning report atomically into `derived/`."""
    _atomic_write_json(cleaning_artifact_path(paths), report.model_dump_json())


def read_cleaning_report(paths: SessionPaths) -> CleaningArtifact | None:
    """Load the cleaning report; corrupt/missing input yields None."""
    try:
        with open(cleaning_artifact_path(paths), encoding="utf-8") as handle:
            payload = json.load(handle)
        return CleaningArtifact.model_validate(payload)
    except (OSError, ValueError, ValidationError):
        return None


def schema_artifact_path(paths: SessionPaths) -> str:
    """Derived-area location of the schema report (raw stays untouched)."""
    return os.path.join(paths.derived, SCHEMA_ARTIFACT_FILENAME)


def write_schema_report(paths: SessionPaths, report: SchemaReport) -> None:
    """Persist the schema report atomically into `derived/`."""
    _atomic_write_json(schema_artifact_path(paths), report.model_dump_json())


def read_schema_report(paths: SessionPaths) -> SchemaReport | None:
    """Load the schema report; corrupt/missing input yields None."""
    try:
        with open(schema_artifact_path(paths), encoding="utf-8") as handle:
            payload = json.load(handle)
        return SchemaReport.model_validate(payload)
    except (OSError, ValueError, ValidationError):
        return None


def build_manifest(
    *,
    session_id: str,
    filename_safe: str,
    size_bytes: int,
    sha256_hex: str,
    encoding: str,
    now: str,
) -> SessionManifest:
    """Assemble the manifest for a freshly ingested session."""
    return SessionManifest(
        sessionId=session_id,
        appVersion=settings.app_version,
        schemaVersion=settings.schema_version,
        filenameSafe=filename_safe,
        bytes=size_bytes,
        sha256=sha256_hex,
        encoding=encoding,
        state=STATE_VALIDATING,
        stage=STATE_VALIDATING,
        progress=make_validating_progress(),
        createdAt=now,
        updatedAt=now,
        lastAccessedAt=now,
        error=None,
    )


def mark_raw_read_only(raw_path: str) -> None:
    """Flag `raw.csv` read-only where the platform supports it (POSIX)."""
    try:
        os.chmod(raw_path, 0o444)
    except OSError:
        logger.warning("raw_readonly_unsupported")


def is_expired(manifest: SessionManifest, now: datetime) -> bool:
    """TTL check against the sliding `lastAccessedAt` (default 24 h)."""
    try:
        last_access = datetime.fromisoformat(manifest.lastAccessedAt)
    except ValueError:
        return True
    ttl = timedelta(hours=settings.session_ttl_hours)
    return (now - last_access) > ttl


@dataclass(frozen=True)
class SweepOutcome:
    """Counts only: sweep logs carry no file contents or personal fields."""

    scanned: int
    removed_corrupt: int
    removed_failed: int
    removed_expired: int
    kept: int


def sweep_sessions(session_root: str, now: datetime) -> SweepOutcome:
    """Restart/expiry cleanup: remove corrupt, FAILED, or expired trees.

    Deterministic in `now` so tests freeze time instead of sleeping. Never
    raises for a single bad directory; per-entry problems are counted.
    """
    scanned = removed_corrupt = removed_failed = removed_expired = kept = 0
    try:
        entries = sorted(os.listdir(session_root))
    except FileNotFoundError:
        return SweepOutcome(0, 0, 0, 0, 0)
    for entry in entries:
        if not is_valid_session_id(entry):
            continue
        scanned += 1
        paths = session_paths(session_root, entry)
        try:
            manifest = read_manifest(paths)
            if manifest is None:
                remove_session_tree(paths)
                removed_corrupt += 1
            elif manifest.state == STATE_FAILED:
                remove_session_tree(paths)
                removed_failed += 1
            elif is_expired(manifest, now):
                remove_session_tree(paths)
                removed_expired += 1
            else:
                kept += 1
        except OSError:
            removed_corrupt += 1
    outcome = SweepOutcome(
        scanned, removed_corrupt, removed_failed, removed_expired, kept
    )
    logger.info(
        "session_sweep scanned=%d corrupt=%d failed=%d expired=%d kept=%d",
        outcome.scanned,
        outcome.removed_corrupt,
        outcome.removed_failed,
        outcome.removed_expired,
        outcome.kept,
    )
    return outcome
