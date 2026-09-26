"""Phase-16 governed export engine (ADR-033/040, docs/export-contract.md).

Exactly four export kinds; raw is never exportable and the internal
``derived/cleaned.csv`` is never served. Data exports project explicit
canonical allowlists (never "all columns"); reports serialize governed
audit artifacts only. Filtering reuses the Phase-15 predicate machinery
(`apply_filters`) restricted to the 8-key public vocabulary; reports
reject any non-empty filter. Every export carries the contract
provenance; CSV kinds publish as one atomic logical record (primary +
same-basename ``.meta.json`` sidecar) and downloads serve persisted
bytes with hash verification, never regeneration.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

import pandas as pd

from app import sessions as session_store
from app.config import settings
from app.ingestion_errors import (
    EXPORT_BLOCKED,
    EXPORT_NOT_FOUND,
    INTERNAL_STAGE_ERROR,
    INVALID_FILTER_VALUE,
    STAGE_ANALYZING,
    STAGE_EXPORT,
    IngestionError,
)
from app.schemas import SessionManifest

if TYPE_CHECKING:
    from app.kpis import KpiFilters

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kind set and vocabulary (export-contract sections 1/1a/1b)
# ---------------------------------------------------------------------------

KIND_CLEANED_ITEMS = "cleaned_items"
KIND_ORDERS = "orders"
KIND_QUALITY_REPORT = "quality_report"
KIND_CLEANING_REPORT = "cleaning_report"

EXPORT_KINDS: tuple[str, ...] = (
    KIND_CLEANED_ITEMS,
    KIND_ORDERS,
    KIND_QUALITY_REPORT,
    KIND_CLEANING_REPORT,
)

REPORT_KINDS: frozenset[str] = frozenset({KIND_QUALITY_REPORT, KIND_CLEANING_REPORT})
CSV_KINDS: frozenset[str] = frozenset({KIND_CLEANED_ITEMS, KIND_ORDERS})

# Public V1 export vocabulary in deterministic order. `department` and
# `customer_segment` are deliberately absent even though `KpiFilters`
# supports them (ADR-040: the export surface never exceeds the
# user-visible analytics filter state).
EXPORT_FILTER_KEYS: tuple[str, ...] = (
    "from",
    "to",
    "market",
    "region",
    "category",
    "shipping_mode",
    "order_status",
    "shipment_outcome",
)

DATA_PROVENANCE: dict[str, str] = {
    KIND_CLEANED_ITEMS: "cleaned",
    KIND_ORDERS: "canonical",
    KIND_QUALITY_REPORT: "report",
    KIND_CLEANING_REPORT: "report",
}

CURRENCY_NOTE = "currency unspecified — numeric units only"
SYNTHETIC_DATA_NOTE = "demo dataset; findings describe the file, not a real company"

# ---------------------------------------------------------------------------
# Explicit allowlists (export-contract section 2, exact order)
# ---------------------------------------------------------------------------

CLEANED_ITEMS_COLUMNS: tuple[str, ...] = (
    "session_id",
    "source_row_number",
    "order_item_id",
    "order_id",
    "customer_id",
    "product_id",
    "category_id",
    "quantity_units",
    "unit_price",
    "gross_sales",
    "discount_amount",
    "net_sales",
    "profit_amount",
    "order_status",
    "shipping_mode",
    "customer_segment",
    "order_timestamp",
    "ship_timestamp",
    "actual_shipping_days",
    "scheduled_shipping_days",
    "shipment_outcome",
    "is_late",
    "schedule_variance_days",
    "order_date",
    "destination_country",
    "destination_region",
    "destination_market",
    "department_name",
    "category_name",
    "product_name",
)

ORDERS_COLUMNS: tuple[str, ...] = (
    "order_id",
    "customer_id",
    "order_timestamp",
    "order_status",
    "shipping_mode",
    "customer_segment",
    "destination_country",
    "destination_region",
    "destination_market",
    "scheduled_shipping_days",
    "actual_shipping_days",
    "shipment_outcome",
    "is_late",
    "line_count",
    "total_units",
    "gross_value",
    "discount_total",
    "net_value",
    "profit_total",
)

KIND_ALLOWLIST: dict[str, tuple[str, ...]] = {
    KIND_CLEANED_ITEMS: CLEANED_ITEMS_COLUMNS,
    KIND_ORDERS: ORDERS_COLUMNS,
}

# Typed columns per export kind (canonical-schema types): emitted as-is,
# never spreadsheet-protected. Every other allowlisted column is a
# string/text cell subject to the injection rule (contract section 7).
MONEY_COLUMNS: frozenset[str] = frozenset(
    {
        "unit_price",
        "gross_sales",
        "discount_amount",
        "net_sales",
        "profit_amount",
        "gross_value",
        "discount_total",
        "net_value",
        "profit_total",
    }
)
INT_COLUMNS: frozenset[str] = frozenset(
    {
        "source_row_number",
        "quantity_units",
        "actual_shipping_days",
        "scheduled_shipping_days",
        "schedule_variance_days",
        "line_count",
        "total_units",
    }
)
DATETIME_COLUMNS: frozenset[str] = frozenset({"order_timestamp", "ship_timestamp"})
DATE_COLUMNS: frozenset[str] = frozenset({"order_date"})
BOOL_COLUMNS: frozenset[str] = frozenset({"is_late"})

# ---------------------------------------------------------------------------
# Privacy gate (DQ-PRIVACY-003, export-contract section 3)
# ---------------------------------------------------------------------------

# Explicit banned-header names (fail closed). The primary enforcement is
# allowlist membership — anything outside the kind's allowlist blocks —
# and this set names the governed banned classes so diagnostics and tests
# can address them directly.
BANNED_EXPORT_HEADERS: frozenset[str] = frozenset(
    {
        "customer_first_name",
        "customer_last_name",
        "customer_street",
        "customer_email",
        "customer_password",
        "first_name",
        "last_name",
        "street",
        "email",
        "password",
        "customer_latitude",
        "customer_longitude",
        "latitude",
        "longitude",
        "destination_postal_code",
        "postal_code",
        "zip",
        "zipcode",
        "ip",
        "ip_address",
    }
)


def run_privacy_gate(kind: str, candidate_headers: list[str]) -> list[str]:
    """DQ-PRIVACY-003: candidate headers must be allowlist members.

    Returns the offending headers (empty when clean). Anything outside
    the kind's explicit allowlist — banned personal/precise columns,
    redundant banned copies, or unmapped unknown columns — is a hit.
    Counts and names of governed fields only; values never inspected.
    """
    allowlist = set(KIND_ALLOWLIST[kind])
    return [
        header
        for header in candidate_headers
        if header not in allowlist or header.casefold() in BANNED_EXPORT_HEADERS
    ]


def check_privacy_gate(
    kind: str, candidate_headers: list[str], session_id: str, state: str | None
) -> None:
    """Enforce the gate before any export bytes are written (422 on hit)."""
    hits = run_privacy_gate(kind, candidate_headers)
    if hits:
        logger.warning("export_blocked kind=%s hits=%d", kind, len(hits))
        raise IngestionError(
            EXPORT_BLOCKED,
            STAGE_EXPORT,
            "The export was blocked by the privacy gate: "
            "candidate output contains non-allowlisted headers.",
            422,
            {"kind": kind, "hits": len(hits)},
            session_id=session_id,
            session_state=state,
        )


# ---------------------------------------------------------------------------
# Spreadsheet-injection protection (export-contract section 7, text only)
# ---------------------------------------------------------------------------

_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@")


def protect_text_cell(value: str) -> str:
    """Neutralize one string/text cell; typed values never reach here."""
    trimmed = value.strip()
    if trimmed.startswith(_FORMULA_PREFIXES) or "|" in trimmed:
        return "'" + value
    return value


# ---------------------------------------------------------------------------
# Cell rendering (export-contract section 8)
# ---------------------------------------------------------------------------


def _render_money(cell: str, column: str) -> str:
    try:
        return format(Decimal(cell).quantize(Decimal("0.00")), "f")
    except (InvalidOperation, ValueError, AttributeError):
        raise _internal_error(column)


def _render_int(cell: str, column: str) -> str:
    try:
        return str(int(cell))
    except (ValueError, AttributeError):
        raise _internal_error(column)


def _internal_error(column: str) -> IngestionError:  # pragma: no cover
    # Unreachable behind the READY gate over validated canonical tables;
    # a malformed canonical cell is an internal integrity failure, never
    # silently emitted.
    return IngestionError(
        INTERNAL_STAGE_ERROR,
        STAGE_EXPORT,
        "A canonical value could not be serialized for export. Upload the file again.",
        500,
        {"column": column},
    )


def render_cell(column: str, cell: str) -> str:
    """Render one canonical CSV string cell for export.

    Canonical tables already serialize per contract; this enforces the
    export boundary: money fixed 2 dp, typed numerics/bools/dates passed
    through untouched (never injection-protected), string cells
    protected. Empty stays empty (nulls are never invented).
    """
    if cell == "":
        return ""
    if column in MONEY_COLUMNS:
        return _render_money(cell, column)
    if column in INT_COLUMNS:
        return _render_int(cell, column)
    if column in BOOL_COLUMNS:
        if cell in ("true", "false"):
            return cell
        raise _internal_error(column)
    if column in DATETIME_COLUMNS or column in DATE_COLUMNS:
        return cell
    return protect_text_cell(cell)


# ---------------------------------------------------------------------------
# Export filter parsing (8-key public vocabulary, Phase-15 semantics)
# ---------------------------------------------------------------------------


def _enum_sets() -> dict[str, set[str]]:
    from app.canonicalization import (
        CUSTOMER_SEGMENT_MAP,
        ORDER_STATUS_MAP,
        SHIPPING_MODE_MAP,
        UNKNOWN_FLAGGED,
    )

    return {
        "shipping_mode": set(SHIPPING_MODE_MAP.values()) | {UNKNOWN_FLAGGED},
        "order_status": set(ORDER_STATUS_MAP.values()) | {UNKNOWN_FLAGGED},
        "customer_segment": set(CUSTOMER_SEGMENT_MAP.values()) | {UNKNOWN_FLAGGED},
        "shipment_outcome": {"LATE", "EARLY", "ON_SCHEDULE", "SHIPPING_CANCELED"},
    }


def parse_export_filters(
    kind: str,
    raw: dict[str, Any] | None,
    session_id: str,
    state: str | None,
) -> KpiFilters:
    """Validate the POST `filters` object into normalized `KpiFilters`.

    Unknown keys (including `department`/`customer_segment`), invalid
    values, and any non-empty filter on a report kind all fail with
    422 INVALID_FILTER_VALUE. Empty/absent filters are always allowed.
    """
    from app.kpis import KpiFilters

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise IngestionError(
            INVALID_FILTER_VALUE,
            STAGE_ANALYZING,
            "Export filters must be an object keyed by governed filter names.",
            422,
            {"kind": kind},
            session_id=session_id,
            session_state=state,
        )
    unknown = sorted(key for key in raw if key not in EXPORT_FILTER_KEYS)
    if unknown:
        raise IngestionError(
            INVALID_FILTER_VALUE,
            STAGE_ANALYZING,
            "Unknown export filter keys. Use only the governed V1 set.",
            422,
            {"kind": kind, "unknown": unknown},
            session_id=session_id,
            session_state=state,
        )
    if kind in REPORT_KINDS and any(
        value is not None and (not isinstance(value, str) or value.strip() != "")
        for value in raw.values()
    ):
        raise IngestionError(
            INVALID_FILTER_VALUE,
            STAGE_ANALYZING,
            "Audit report exports are whole-session and reject filters.",
            422,
            {"kind": kind},
            session_id=session_id,
            session_state=state,
        )

    def text(name: str) -> str | None:
        # Mirrors the Phase-15 query parser: blank strings are absent,
        # non-strings are invalid (never coerced).
        value = raw.get(name)
        if value is None:
            return None
        if not isinstance(value, str):
            raise IngestionError(
                INVALID_FILTER_VALUE,
                STAGE_ANALYZING,
                f"Invalid export filter value for '{name}'.",
                422,
                {"kind": kind, name: value},
                session_id=session_id,
                session_state=state,
            )
        return value.strip() or None

    def iso_date(name: str) -> date | None:
        value = text(name)
        if value is None:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise IngestionError(
                INVALID_FILTER_VALUE,
                STAGE_ANALYZING,
                f"Unknown date filter '{name}'. Use ISO YYYY-MM-DD on order date.",
                422,
                {"kind": kind, name: raw.get(name)},
                session_id=session_id,
                session_state=state,
            ) from None

    def enum(name: str) -> str | None:
        value = text(name)
        if value is None:
            return None
        if value in _enum_sets()[name]:
            return value
        raise IngestionError(
            INVALID_FILTER_VALUE,
            STAGE_ANALYZING,
            f"Unknown {name} filter value. It was rejected, never mapped.",
            422,
            {"kind": kind, name: raw.get(name)},
            session_id=session_id,
            session_state=state,
        )

    return KpiFilters(
        date_from=iso_date("from"),
        date_to=iso_date("to"),
        market=text("market"),
        region=text("region"),
        category=text("category"),
        department=None,
        shipping_mode=enum("shipping_mode"),
        order_status=enum("order_status"),
        shipment_outcome=enum("shipment_outcome"),
        customer_segment=None,
    )


def filters_applied_map(filters: KpiFilters) -> dict[str, str]:
    """Truthful provenance: only filters that narrowed content, fixed order."""
    full = filters.as_meta()
    return {key: full[key] for key in EXPORT_FILTER_KEYS if key in full}


# ---------------------------------------------------------------------------
# Filenames and identity (export-contract section 5)
# ---------------------------------------------------------------------------

_SAFE_BASENAME_RE = re.compile(r"[^A-Za-z0-9\-_]")


def safe_basename(filename_safe: str) -> str:
    """Derive the governed stem: safe chars only, 40 chars, never the raw."""
    stem = filename_safe.rsplit(".", 1)[0] if "." in filename_safe else filename_safe
    cleaned = _SAFE_BASENAME_RE.sub("", stem)[:40]
    return cleaned or "export"


def export_filenames(
    filename_safe: str, kind: str, extension: str, now_iso: str
) -> tuple[str, str | None]:
    """Primary (+ sidecar for CSV kinds) display filenames."""
    stamp = now_iso.replace("-", "").replace(":", "")
    primary = (
        f"{safe_basename(filename_safe)}_{kind}_"
        f"app{settings.app_version}_schema{settings.schema_version}_{stamp}.{extension}"
    )
    if kind in CSV_KINDS:
        return primary, primary.rsplit(".", 1)[0] + ".meta.json"
    return primary, None


def new_export_id() -> str:
    """Server-generated opaque lookup key (never a filesystem path)."""
    return uuid.uuid4().hex


_EXPORT_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def is_valid_export_id(candidate: str) -> bool:
    """Opaque-ID gate: anything else never touches the filesystem."""
    return bool(_EXPORT_ID_RE.match(candidate or ""))


# ---------------------------------------------------------------------------
# Provenance (export-contract section 4)
# ---------------------------------------------------------------------------


def build_provenance(
    *,
    kind: str,
    manifest: SessionManifest,
    filters: KpiFilters,
    generated_at: str,
) -> dict[str, Any]:
    """Exact 12-field provenance for sidecars and embedded report blocks."""
    applied = filters_applied_map(filters) if kind not in REPORT_KINDS else {}
    return {
        "appVersion": settings.app_version,
        "schemaVersion": settings.schema_version,
        "sessionId": manifest.sessionId,
        "sourceFilenameSafe": manifest.filenameSafe,
        "sourceSha256": manifest.sha256,
        "sourceBytes": manifest.bytes,
        "generatedAt": generated_at,
        "filtersApplied": applied,
        "exportKind": kind,
        "dataProvenance": DATA_PROVENANCE[kind],
        "currencyNote": CURRENCY_NOTE,
        "syntheticDataNote": SYNTHETIC_DATA_NOTE,
    }


# ---------------------------------------------------------------------------
# CSV building (canonical projection + render + RFC 4180)
# ---------------------------------------------------------------------------


def _read_canonical_strings(
    paths: session_store.SessionPaths, filename: str
) -> pd.DataFrame:
    full = session_store.canonical_table_path(paths, filename)
    return pd.read_csv(full, dtype="string[pyarrow]", keep_default_na=False)


@dataclass(frozen=True)
class BuiltCsv:
    header: list[str]
    rows: list[list[str]]
    row_count: int


def build_csv_dataset(
    kind: str,
    paths: session_store.SessionPaths,
    filters: KpiFilters,
    session_id: str,
    state: str | None,
) -> BuiltCsv:
    """Project, filter, gate, and render one CSV dataset (no bytes yet)."""
    from app.kpis import apply_filters, load_canonical_tables

    columns = KIND_ALLOWLIST[kind]
    check_privacy_gate(kind, list(columns), session_id, state)
    try:
        tables = load_canonical_tables(paths)
    except OSError as exc:
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_EXPORT,
            "The canonical tables could not be read. Upload the file again.",
            500,
            {"kind": kind},
            session_id=session_id,
            session_state=state,
        ) from exc
    items, orders = apply_filters(tables, filters)
    if kind == KIND_CLEANED_ITEMS:
        filtered, key = items, "order_item_id"
        filename = session_store.CANONICAL_ITEMS_FILENAME
    else:
        filtered, key = orders, "order_id"
        filename = session_store.CANONICAL_ORDERS_FILENAME
    try:
        frame = _read_canonical_strings(paths, filename)
    except OSError as exc:
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_EXPORT,
            "The canonical tables could not be read. Upload the file again.",
            500,
            {"kind": kind},
            session_id=session_id,
            session_state=state,
        ) from exc
    # Preserve canonical file order (source-row order for items,
    # order_id-sorted for orders): deterministic by construction. The
    # filtered parsed frames reset their index, so rejoin positions
    # through the unique row key (gated unique upstream).
    positions = {str(value): pos for pos, value in enumerate(frame[key].tolist())}
    rows: list[list[str]] = []
    for key_value in filtered[key].tolist():
        record = frame.iloc[positions[str(key_value)]]
        rows.append([render_cell(column, str(record[column])) for column in columns])
    return BuiltCsv(header=list(columns), rows=rows, row_count=len(rows))


def serialize_csv(header: list[str], rows: list[list[str]]) -> bytes:
    """UTF-8+BOM, LF endings, RFC 4180 quoting, header always."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return "\ufeff".encode() + buffer.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Report building (JSON only in V1; governed artifacts only)
# ---------------------------------------------------------------------------


def build_quality_report(
    paths: session_store.SessionPaths,
    provenance: dict[str, Any],
    session_id: str,
    state: str | None,
) -> dict[str, Any]:
    """V1 quality report: profile + DQ issues + schema coverage (counts)."""
    profiling = session_store.read_profiling_report(paths)
    schema = session_store.read_schema_report(paths)
    if profiling is None or schema is None:  # pragma: no cover
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_EXPORT,
            "The profiling evidence could not be read. Upload the file again.",
            500,
            {"kind": KIND_QUALITY_REPORT},
            session_id=session_id,
            session_state=state,
        )
    return {
        "provenance": provenance,
        "profile": profiling.profile.model_dump(mode="json"),
        "dataQuality": {
            "summary": {
                "rulesEvaluated": profiling.rulesEvaluated,
                "rulesTriggered": len(profiling.issues),
                "errors": sum(1 for i in profiling.issues if i.severity == "ERROR"),
                "warnings": sum(1 for i in profiling.issues if i.severity == "WARNING"),
                "infos": sum(1 for i in profiling.issues if i.severity == "INFO"),
                "blockingIssues": sum(
                    1 for i in profiling.issues if i.blockedStage is not None
                ),
            },
            "issues": [issue.model_dump(mode="json") for issue in profiling.issues],
            "issueMessages": dict(profiling.issueMessages),
        },
        "schema": {
            "sourceColumns": list(schema.sourceColumns),
            "mapping": [m.model_dump(mode="json") for m in schema.mapping],
            "missingCritical": list(schema.missingRequired),
            "unrecognized": list(schema.unrecognized),
            "redundant": list(schema.redundant),
            "auditOnly": list(schema.auditOnly),
        },
    }


def build_cleaning_report(
    paths: session_store.SessionPaths,
    provenance: dict[str, Any],
    session_id: str,
    state: str | None,
) -> dict[str, Any]:
    """V1 cleaning report: audit steps + totals + reconciliation (counts)."""
    cleaning = session_store.read_cleaning_report(paths)
    if cleaning is None:  # pragma: no cover
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_EXPORT,
            "The cleaning evidence could not be read. Upload the file again.",
            500,
            {"kind": KIND_CLEANING_REPORT},
            session_id=session_id,
            session_state=state,
        )
    return {
        "provenance": provenance,
        "steps": [step.model_dump(mode="json") for step in cleaning.steps],
        "totals": cleaning.totals.model_dump(mode="json"),
        "reconciliation": cleaning.reconciliation.model_dump(mode="json"),
        "versions": {
            "appVersion": cleaning.appVersion,
            "schemaVersion": cleaning.schemaVersion,
        },
    }


def serialize_report(payload: dict[str, Any]) -> bytes:
    """UTF-8 JSON, naive ISO datetimes already strings, money 2-dp strings."""
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )


# ---------------------------------------------------------------------------
# Atomic publication + persisted export records (no database)
# ---------------------------------------------------------------------------


def _write_atomic_bytes(final_path: str, content: bytes) -> None:
    tmp_path = session_store._unique_tmp_path(final_path)
    try:
        with open(tmp_path, "wb") as handle:
            handle.write(content)
        os.replace(tmp_path, final_path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


@dataclass(frozen=True)
class PublishedExport:
    export_id: str
    kind: str
    filename: str
    content: bytes
    sha256: str
    metadata_filename: str | None
    metadata_content: bytes | None
    metadata_sha256: str | None


def _export_paths(paths: session_store.SessionPaths, export_id: str) -> dict[str, str]:
    base = os.path.join(paths.exports, export_id)
    return {
        "record": base + ".record.json",
        "primary": base + ".primary",
        "sidecar": base + ".meta.json",
    }


def publish_export(
    paths: session_store.SessionPaths,
    *,
    kind: str,
    manifest: SessionManifest,
    filters: KpiFilters,
    primary: bytes,
    primary_filename: str,
    sidecar: bytes | None,
    sidecar_filename: str | None,
    generated_at: str,
) -> PublishedExport:
    """Atomically publish one logical export; 201 only after all durable.

    Writes primary (+ sidecar for CSV kinds) via unique-temp + rename,
    then the lookup record last. Any failure before the record lands
    leaves no downloadable export: GET requires the record.
    """
    export_id = new_export_id()
    locations = _export_paths(paths, export_id)
    primary_sha = hashlib.sha256(primary).hexdigest()
    sidecar_sha = hashlib.sha256(sidecar).hexdigest() if sidecar is not None else None
    record = {
        "exportId": export_id,
        "kind": kind,
        "filename": primary_filename,
        "bytes": len(primary),
        "sha256": primary_sha,
        "metadataFilename": sidecar_filename,
        "metadataBytes": len(sidecar) if sidecar is not None else None,
        "metadataSha256": sidecar_sha,
        "filtersApplied": (
            filters_applied_map(filters) if kind not in REPORT_KINDS else {}
        ),
        "createdAt": generated_at,
        "sessionId": manifest.sessionId,
    }
    try:
        _write_atomic_bytes(locations["primary"], primary)
        if sidecar is not None and sidecar_filename is not None:
            _write_atomic_bytes(locations["sidecar"], sidecar)
        _write_atomic_bytes(
            locations["record"],
            json.dumps(record, sort_keys=True).encode("utf-8"),
        )
    except OSError as exc:
        for stale in (
            locations["record"],
            locations["primary"],
            locations["sidecar"],
        ):
            try:
                os.remove(stale)
            except OSError:
                pass
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_EXPORT,
            "The export could not be published. Try again.",
            500,
            {"kind": kind},
            session_id=manifest.sessionId,
            session_state=manifest.state,
        ) from exc
    logger.info("export_published kind=%s bytes=%d", kind, len(primary))
    return PublishedExport(
        export_id=export_id,
        kind=kind,
        filename=primary_filename,
        content=primary,
        sha256=primary_sha,
        metadata_filename=sidecar_filename,
        metadata_content=sidecar,
        metadata_sha256=sidecar_sha,
    )


def read_export_record(
    paths: session_store.SessionPaths, export_id: str
) -> dict[str, Any] | None:
    """Load the persisted lookup record (None when absent/corrupt)."""
    if not is_valid_export_id(export_id):
        return None
    try:
        record_path = _export_paths(paths, export_id)["record"]
        with open(record_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError):
        return None


def read_export_bytes(
    paths: session_store.SessionPaths,
    export_id: str,
    *,
    sidecar: bool,
    session_id: str,
    state: str | None,
) -> tuple[bytes, dict[str, Any]]:
    """Serve persisted bytes with hash verification (never regenerate).

    Returns (content, record). Missing record → EXPORT_NOT_FOUND;
    hash mismatch → INTERNAL_STAGE_ERROR (never silently serve corrupt
    bytes, never silently rebuild).
    """
    record = read_export_record(paths, export_id)
    if record is None:
        raise IngestionError(
            EXPORT_NOT_FOUND,
            STAGE_EXPORT,
            "No export matches this identifier.",
            404,
            {"exportId": "unknown"},
            session_id=session_id,
            session_state=state,
        )
    if sidecar and record.get("metadataSha256") is None:
        raise IngestionError(
            EXPORT_NOT_FOUND,
            STAGE_EXPORT,
            "This export has no metadata sidecar.",
            404,
            {"exportId": "unknown", "kind": record.get("kind")},
            session_id=session_id,
            session_state=state,
        )
    locations = _export_paths(paths, export_id)
    target = locations["sidecar"] if sidecar else locations["primary"]
    expected = record.get("metadataSha256") if sidecar else record.get("sha256")
    try:
        with open(target, "rb") as handle:
            content = handle.read()
    except OSError:
        raise IngestionError(
            EXPORT_NOT_FOUND,
            STAGE_EXPORT,
            "The export artifact is no longer available.",
            404,
            {"exportId": "unknown"},
            session_id=session_id,
            session_state=state,
        ) from None
    if hashlib.sha256(content).hexdigest() != expected:
        logger.warning("export_integrity_mismatch")
        raise IngestionError(
            INTERNAL_STAGE_ERROR,
            STAGE_EXPORT,
            "The export artifact failed its integrity check. Build the export again.",
            500,
            {"kind": record.get("kind")},
            session_id=session_id,
            session_state=state,
        )
    return content, record
