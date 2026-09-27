"""Machine-readable benchmark report schema (ADR-042).

JSON only, governed safe metadata only: identity, environment, elapsed
durations, byte counts, SHAs, and unavailable-metric reasons. Never rows,
values, PII, paths, or secrets. Unmeasurable metrics are ``None`` with an
entry in ``unavailableReasons`` — never fabricated precision.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

SCRATCH_DIRNAME = ".tmp/benchmarks"
REPORTS_DIRNAME = "reports"

# Identity fields every report must carry (benchmark identity includes at
# least generator version, seed, tier, requested and actual row counts).
IDENTITY_FIELDS: tuple[str, ...] = (
    "generatorVersion",
    "seed",
    "tier",
    "profile",
    "requestedRows",
    "actualRows",
    "sourceBytes",
    "sourceSha256",
)

# Environment fields every report must carry (nodeVersion may be None).
ENVIRONMENT_FIELDS: tuple[str, ...] = (
    "appRevision",
    "workingTreeDirty",
    "platform",
    "architecture",
    "pythonVersion",
    "nodeVersion",
)

# Duration/size metrics (float seconds / int bytes, or None + reason).
MEASUREMENT_FIELDS: tuple[str, ...] = (
    "generationDurationSeconds",
    "uploadPostTestClientDurationSeconds",
    "validationDurationSeconds",
    "profilingDurationSeconds",
    "cleaningDurationSeconds",
    "canonicalizationDurationSeconds",
    "kpiDurationSeconds",
    "readyDurationSeconds",
    "overviewRequestDurationSeconds",
    "deliveryRequestDurationSeconds",
    "commercialRequestDurationSeconds",
    "filterOptionsRequestDurationSeconds",
    "ordersPageRequestDurationSeconds",
    "diagnosticsRequestDurationSeconds",
    "exportGenerationDurationSeconds",
    "exportDownloadDurationSeconds",
    "peakProcessRssBytes",
    "exportBytes",
    "frontendBundleBytes",
)


def repo_root() -> Path:
    """Repository root derived from this file's location."""
    return Path(__file__).resolve().parents[2]


def default_scratch_dir() -> Path:
    """Governed scratch location for generated benchmark artifacts."""
    return repo_root() / SCRATCH_DIRNAME


def default_reports_dir() -> Path:
    """Governed scratch location for benchmark reports (outside Git)."""
    return default_scratch_dir() / REPORTS_DIRNAME


def ensure_within_scratch(path: Path, *, test_only: bool = False) -> Path:
    """Resolve ``path`` and require it inside the governed scratch dir.

    Raises ``ValueError`` on escape. Unit tests may pass
    ``test_only=True`` with a pytest ``tmp_path`` outside the repo.
    """
    scratch = default_scratch_dir().resolve()
    resolved = path.resolve()
    if resolved == scratch or scratch in resolved.parents:
        return resolved
    if test_only and resolved.is_absolute():
        return resolved
    raise ValueError(f"Benchmark output must stay under {scratch}; got {resolved}.")


def build_report(
    *,
    identity: dict[str, object],
    environment: dict[str, object],
    measurements: dict[str, float | int | None],
    unavailable_reasons: dict[str, str],
    notes: list[str],
    request_config: dict[str, object],
) -> dict[str, object]:
    """Assemble a report dict; raises ``KeyError`` on missing fields."""
    for field in IDENTITY_FIELDS:
        if field not in identity:
            raise KeyError(f"Missing required identity field: {field}")
    for field in ENVIRONMENT_FIELDS:
        if field not in environment:
            raise KeyError(f"Missing required environment field: {field}")
    for field in MEASUREMENT_FIELDS:
        if field not in measurements:
            raise KeyError(f"Missing required measurement field: {field}")
    for name, value in measurements.items():
        if value is None:
            if name not in unavailable_reasons:
                raise KeyError(f"Unavailable metric '{name}' needs a reason.")
        elif isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError(f"Metric '{name}' must be numeric or None.")
        elif value < 0:
            raise ValueError(f"Metric '{name}' must be >= 0.")
    return {
        "schemaVersion": 1,
        "identity": {field: identity[field] for field in IDENTITY_FIELDS},
        "environment": {field: environment[field] for field in ENVIRONMENT_FIELDS},
        "measurements": {field: measurements[field] for field in MEASUREMENT_FIELDS},
        "unavailableReasons": dict(unavailable_reasons),
        "requestConfig": dict(request_config),
        "notes": list(notes),
    }


def _unique_tmp_path(final_path: Path) -> Path:
    """Same-directory unique temp path (repo atomic-write convention)."""
    return final_path.with_name(f"{final_path.name}.{uuid.uuid4().hex}.tmp")


def write_bytes_atomic(path: Path, content: bytes) -> Path:
    """Write bytes atomically (tmp + os.replace); scratch-guarded."""
    resolved = ensure_within_scratch(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _unique_tmp_path(resolved)
    try:
        tmp_path.write_bytes(content)
        os.replace(tmp_path, resolved)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return resolved


def write_report(report: dict[str, object], path: Path) -> Path:
    """Write a report as deterministic, standards-compliant JSON.

    Atomic publication (tmp + replace): a serialization/write failure never
    leaves a partial report at the final path. ``allow_nan=False`` rejects
    non-finite numbers instead of emitting non-standard JSON.
    """
    text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    return write_bytes_atomic(path, text.encode("utf-8"))


def scan_report_text(report: dict[str, object], forbidden: list[str]) -> list[str]:
    """Return the forbidden tokens found in the serialized report (want: [])."""
    text = json.dumps(report, sort_keys=True)
    return [token for token in forbidden if token in text]
