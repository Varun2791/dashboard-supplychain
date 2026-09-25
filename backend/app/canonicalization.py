"""Phase-8 canonical model construction.

Reads the verified internal `derived/cleaned.csv` (Phase-7 CAT-005 trims +
governed projection, same row order/count as the raw) plus the schema,
profiling, and cleaning reports, and builds the typed canonical tables from
`docs/canonical-schema.md`. No KPI math lives here: only sums/counts needed
to reconcile item aggregates to order and dataset totals (PLAN Phase-8 task).

Contract matrix (authority: AGENTS.md, ADRs, PLAN Phase-8, canonical-schema,
data-quality-rules, api-contract):

- `order_items`: one row per governed source line, PK `order_item_id`.
  Blocked by DQ-KEY-001 (duplicate item IDs — never deduped); the items
  build is the base, so a KEY-001 block parks the whole canonical build.
- `orders`: one row per `order_id`, built only after order-invariance
  validation passes. Blocked by DQ-GRAIN-001 (no first-row pick); a GRAIN-001
  block parks `orders` only — items/products/customers/calendar/issues still
  build (catalogue and API parentheticals both scope the block to the orders
  build).
- `products`: one row per `product_id`, identifying dims invariant-checked,
  defensible aggregations only (no reference price). A dim conflict blocks
  the products build under DQ-GRAIN-003 / PRODUCT_INVARIANCE_CONFLICT
  (ADR-036; order code never reused).
- `customers_sanitized`: one row per `customer_id`, segment
  invariant-checked, coarse customer-side geography only. A segment conflict
  blocks the customers build under DQ-GRAIN-004 /
  CUSTOMER_INVARIANCE_CONFLICT (ADR-036). No governed
  customer-side geo columns exist in V1 (bounded registry deferral), so geo
  fields are always null — never imputed from destinations (ADR-016). Direct
  personal fields can never enter (ADR-005).
- `calendar`: one row per distinct canonical `order_date` present; naive
  date parts only, no KPI semantics.
- `data_quality_issues`: one row per triggered profiling rule (rule, counts,
  severity, blocked stage); detection evidence carried forward, never a fix.

Implementation interpretations (smallest deterministic readings where the
contract leaves mechanics implicit; recorded here, not new ADRs):

- `source_row_number` is the 1-based logical data-row ordinal in `raw.csv`
  (header excluded; first data row = 1). Positional correspondence with
  `cleaned.csv` holds because cleaning preserves row order and count (both
  asserted before materialization). Quoted embedded-newline records count
  once (pandas record ordinal, not physical line number). Stored on
  `order_items` only, never null, never part of any key.
- Missing (empty/whitespace-only) or unparseable values are carried as null
  — never invented, never dropped, never zero-filled. Canonical money/int/
  date fields are therefore nullable in practice despite `NN` labels; null
  means absent/unparseable. Missingness has no governing ERROR rule, and
  DATE-001 explicitly keeps affected rows out of date-binned KPIs rather
  than blocking the row. File-wide DATE-001 (rows exist but zero parseable
  order dates) blocks the build as the catalogue states.
- The cancel signal compares the stripped `Delivery Status` text against the
  exact `"Shipping canceled"` value, consistent with profiling populations
  (profiling compares stripped text; cleaning never trims this field).
- Cancelled rows derive `actual_shipping_days = null` (no shipment occurred,
  per the schema parenthetical), `shipment_outcome = SHIPPING_CANCELED`,
  `is_late = null`, `schedule_variance_days = null`. Scheduled days are
  retained. `Late_delivery_risk` never materializes and never classifies.
- Unknown enum values become the `UNKNOWN_FLAGGED` sentinel (never coerced);
  blank enum cells become null (missing, not unknown). Known shipping-mode /
  customer-segment spellings map to their UPPER_SNAKE canonical tokens.
- IDs are carried as exact source text (no whitespace normalization — no
  rule authorizes it); key checks use the same raw-text semantics as
  profiling. Joins use exact text.
- The orders gate checks the 10 profiling invariance fields plus
  `customer_segment` (the orders table carries it as invariant) plus derived
  `shipment_outcome` agreement (schema: "re-checked at order level";
  `delivery_status` itself is not invariance-checked, so two lines can
  disagree on outcome). Merch dims on orders are single-value-or-null (they
  legitimately span products; null = multi-valued, not a fix).
- Product/customer identifying-dim conflicts block only that table under
  their governed codes (DQ-GRAIN-003 / PRODUCT_INVARIANCE_CONFLICT,
  DQ-GRAIN-004 / CUSTOMER_INVARIANCE_CONFLICT, ADR-036). Enforcement is the
  union of profiling evidence and the defensive re-check below: any
  disagreement parks (never builds) the affected table as a recoverable
  gate, because profiling compares stripped raw text while the re-check
  compares exact cleaned text and IDs are never trimmed.
- Persisted format (internal, not public API): deterministic UTF-8 CSVs with
  LF endings under `derived/` (one row per grain, fixed column order, stable
  sort), plus the typed `canonical_report.json`. CSV matches the existing
  `cleaned.csv` precedent and keeps Decimal/date round-trips strict.

Lifecycle: success advances CANONICALIZING -> ANALYZING and stops (Phase 9
owns KPI analysis; no READY is faked). Governed quality blocks keep the
session parked at CANONICALIZING with the raw retained (recoverable gate,
not terminal). Internal/artifact failures follow ADR-028 (raw/derived
removal, manifest-only error metadata).

Execution model: synchronous workers through the existing framework-local
post-response runner (chained from cleaning). Single-process guard against
duplicate runs; unique temp names + atomic replace; CAS manifest touching.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import date, datetime
from decimal import Decimal

import pandas as pd

from app import sessions as session_store
from app.config import settings
from app.ingestion_errors import (
    CUSTOMER_INVARIANCE_CONFLICT,
    DUPLICATE_ITEM_KEY,
    INTERNAL_STAGE_ERROR,
    ORDER_INVARIANCE_CONFLICT,
    PRODUCT_INVARIANCE_CONFLICT,
    STAGE_CANONICALIZING,
    IngestionError,
)
from app.profile_checks import (
    parse_int_values,
    parse_money_valid,
    parse_timestamps,
    stripped,
    to_decimal_or_none,
)
from app.profiling import sha256_file
from app.schema_registry import CANCEL_SIGNAL_VALUE
from app.schema_validation import strip_session_payloads
from app.schemas import (
    STATE_ANALYZING,
    STATE_CANONICALIZING,
    STATE_FAILED,
    ApiErrorModel,
    CanonicalArtifact,
    CanonicalBlocker,
    CanonicalReconciliation,
    CanonicalTableIdentity,
    SessionManifest,
)

logger = logging.getLogger(__name__)

UNKNOWN_FLAGGED = "UNKNOWN_FLAGGED"

# Exact enum maps (canonical-schema section 7; enforcement matches profiling:
# order_status is the closed 8-set; shipping_mode/customer_segment enforce
# only the verbatim source spellings, everything else takes UNKNOWN_FLAGGED).
ORDER_STATUS_MAP: dict[str, str] = {
    "COMPLETE": "COMPLETE",
    "CLOSED": "CLOSED",
    "PENDING": "PENDING",
    "PROCESSING": "PROCESSING",
    "ON_HOLD": "ON_HOLD",
    "CANCELED": "CANCELED",
    "PAYMENT_REVIEW": "PAYMENT_REVIEW",
    "SUSPECTED_FRAUD": "SUSPECTED_FRAUD",
}
SHIPPING_MODE_MAP: dict[str, str] = {
    "Standard Class": "STANDARD_CLASS",
    "Same Day": "SAME_DAY",
}
CUSTOMER_SEGMENT_MAP: dict[str, str] = {
    "Consumer": "CONSUMER",
    "Home Office": "HOME_OFFICE",
}

# Order-level gate: profiling's 10 invariance fields plus customer_segment
# (orders carry it as invariant) plus derived outcome agreement.
ORDER_GATE_FIELDS: tuple[str, ...] = (
    "customer_id",
    "order_status",
    "shipping_mode",
    "customer_segment",
    "order_timestamp",
    "ship_timestamp",
    "actual_shipping_days",
    "scheduled_shipping_days",
    "destination_country",
    "destination_region",
    "destination_market",
    "shipment_outcome",
)

# Merch dims legitimately span products within an order: single-or-null.
ORDER_MERCH_FIELDS: tuple[str, ...] = (
    "department_name",
    "category_name",
    "product_name",
)

PRODUCT_DIM_FIELDS: tuple[str, ...] = (
    "category_id",
    "department_name",
    "category_name",
    "product_name",
)

MONEY_FIELDS: tuple[str, ...] = (
    "gross_sales",
    "discount_amount",
    "net_sales",
    "profit_amount",
)

ITEM_COLUMNS: tuple[str, ...] = (
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
    "destination_country",
    "destination_region",
    "destination_market",
    "department_name",
    "category_name",
    "product_name",
    "shipment_outcome",
    "is_late",
    "schedule_variance_days",
    "order_date",
)

ORDER_COLUMNS: tuple[str, ...] = (
    "order_id",
    "session_id",
    "customer_id",
    "order_timestamp",
    "order_status",
    "shipping_mode",
    "customer_segment",
    "destination_country",
    "destination_region",
    "destination_market",
    "department_name",
    "category_name",
    "product_name",
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

PRODUCT_COLUMNS: tuple[str, ...] = (
    "product_id",
    "category_id",
    "department_name",
    "category_name",
    "product_name",
    "line_count",
    "total_units",
    "total_net_value",
    "total_profit_amount",
)

CUSTOMER_COLUMNS: tuple[str, ...] = (
    "customer_id",
    "customer_segment",
    "customer_country",
    "customer_state",
    "customer_city",
    "order_count",
    "total_net_value",
    "total_profit_amount",
)

CALENDAR_COLUMNS: tuple[str, ...] = (
    "date",
    "year",
    "quarter",
    "month",
    "iso_week",
    "day_of_week",
    "is_weekend",
)

ISSUE_COLUMNS: tuple[str, ...] = (
    "rule_id",
    "severity",
    "count",
    "treatment",
    "blocked_stage",
    "message",
)


def map_enum(values: pd.Series, mapping: dict[str, str]) -> list[str | None]:
    """Exact enum map: known -> canonical token, unknown -> sentinel.

    Blank (missing) cells become None (missing, not unknown). Never coerces.
    """
    out: list[str | None] = []
    for text in values.tolist():
        cell = str(text).strip()
        if cell == "":
            out.append(None)
        elif cell in mapping:
            out.append(mapping[cell])
        else:
            out.append(UNKNOWN_FLAGGED)
    return out


def parse_optional_int(values: pd.Series) -> list[int | None]:
    """Strict integer parse; unparseable/missing cells become None."""
    parsed = parse_int_values(values.str.strip())
    return [None if pd.isna(v) else int(v) for v in parsed.tolist()]


def parse_optional_decimal(values: pd.Series) -> list[Decimal | None]:
    """Strict money parse to Decimal; unparseable/missing cells become None."""
    cleaned = values.str.strip()
    valid = parse_money_valid(cleaned)
    out: list[Decimal | None] = []
    for text, ok in zip(cleaned.tolist(), valid.tolist(), strict=True):
        if not bool(ok):
            out.append(None)
        else:
            out.append(to_decimal_or_none(str(text)))
    return out


def parse_optional_timestamp(values: pd.Series) -> list[datetime | None]:
    """Explicit month-first parse (profiling semantics); failures are None."""
    parsed = parse_timestamps(values.str.strip())
    out: list[datetime | None] = []
    for value in parsed.tolist():
        if value is None or pd.isna(value):
            out.append(None)
        else:
            out.append(value.to_pydatetime().replace(tzinfo=None))
    return out


def build_order_items(
    cleaned: pd.DataFrame, col_of: dict[str, str], session_id: str
) -> pd.DataFrame:
    """Build the typed order-items frame (Python values, one row per line).

    Row order and count match `cleaned.csv`, so `source_row_number` is the
    1-based positional ordinal. Reported net stays authoritative; negative
    profit is retained; nothing is deduped or repaired.
    """
    n = len(cleaned)

    def col(canonical: str) -> pd.Series:
        return cleaned[col_of[canonical]]

    def id_or_none(canonical: str) -> list[str | None]:
        raw = col(canonical).astype(str).tolist()
        return [None if cell.strip() == "" else cell for cell in raw]

    def label_or_none(canonical: str) -> list[str | None]:
        if canonical not in col_of:
            return [None] * n
        vals = stripped(cleaned, col_of[canonical]).tolist()
        return [None if str(v) == "" else str(v) for v in vals]

    cancelled = [
        str(v).strip() == CANCEL_SIGNAL_VALUE
        for v in col("delivery_status").astype(str).tolist()
    ]
    actual = parse_optional_int(col("actual_shipping_days"))
    scheduled = parse_optional_int(col("scheduled_shipping_days"))
    order_ts = parse_optional_timestamp(col("order_timestamp"))
    ship_ts = parse_optional_timestamp(col("ship_timestamp"))

    status = map_enum(stripped(cleaned, col_of["order_status"]), ORDER_STATUS_MAP)
    mode = map_enum(stripped(cleaned, col_of["shipping_mode"]), SHIPPING_MODE_MAP)
    if "customer_segment" in col_of:
        segment = map_enum(
            stripped(cleaned, col_of["customer_segment"]), CUSTOMER_SEGMENT_MAP
        )
    else:
        segment = [None] * n

    outcome: list[str | None] = []
    is_late: list[bool | None] = []
    variance: list[int | None] = []
    for is_cancelled, real, plan in zip(cancelled, actual, scheduled, strict=True):
        if is_cancelled:
            outcome.append("SHIPPING_CANCELED")
            is_late.append(None)
            variance.append(None)
        elif real is None or plan is None:
            outcome.append(None)
            is_late.append(None)
            variance.append(None)
        elif real > plan:
            outcome.append("LATE")
            is_late.append(True)
            variance.append(real - plan)
        elif real == plan:
            outcome.append("ON_SCHEDULE")
            is_late.append(False)
            variance.append(0)
        else:
            outcome.append("EARLY")
            is_late.append(False)
            variance.append(real - plan)
    # Cancelled rows carry no actual days (no shipment occurred, per schema).
    actual = [None if c else v for c, v in zip(cancelled, actual, strict=True)]
    order_date = [ts.date() if ts is not None else None for ts in order_ts]

    frame = pd.DataFrame(
        {
            "session_id": [session_id] * n,
            "source_row_number": list(range(1, n + 1)),
            "order_item_id": id_or_none("order_item_id"),
            "order_id": id_or_none("order_id"),
            "customer_id": id_or_none("customer_id"),
            "product_id": id_or_none("product_id"),
            "category_id": id_or_none("category_id"),
            "quantity_units": parse_optional_int(col("quantity_units")),
            "unit_price": parse_optional_decimal(col("unit_price")),
            "gross_sales": parse_optional_decimal(col("gross_sales")),
            "discount_amount": parse_optional_decimal(col("discount_amount")),
            "net_sales": parse_optional_decimal(col("net_sales")),
            "profit_amount": parse_optional_decimal(col("profit_amount")),
            "order_status": status,
            "shipping_mode": mode,
            "customer_segment": segment,
            "order_timestamp": order_ts,
            "ship_timestamp": ship_ts,
            "actual_shipping_days": actual,
            "scheduled_shipping_days": scheduled,
            "destination_country": label_or_none("destination_country"),
            "destination_region": label_or_none("destination_region"),
            "destination_market": label_or_none("destination_market"),
            "department_name": label_or_none("department_name"),
            "category_name": label_or_none("category_name"),
            "product_name": label_or_none("product_name"),
            "shipment_outcome": outcome,
            "is_late": is_late,
            "schedule_variance_days": variance,
            "order_date": order_date,
        }
    )
    return frame[list(ITEM_COLUMNS)]


def duplicate_item_rows(raw_ids: pd.Series) -> int:
    """Excess rows sharing a duplicate Order Item Id (raw-text semantics).

    Mirrors profiling DQ-KEY-001: exact-text duplicates among non-missing
    IDs only. Missing IDs are reported via missingness, never deduped.
    """
    present = raw_ids.astype(str).str.strip() != ""
    return int((present & raw_ids.duplicated(keep="first")).sum())


def order_gate_conflicts(items: pd.DataFrame) -> dict[str, list[str]]:
    """Orders whose lines disagree on an order-level field (no first-row pick).

    Only distinct non-null values conflict; nulls are ignored. Returns
    order_id -> sorted conflicting fields. Counts only — no cell values.
    """
    keyed = items[items["order_id"].notna()]
    conflicts: dict[str, list[str]] = {}
    if len(keyed) == 0:
        return conflicts
    for field in ORDER_GATE_FIELDS:
        distinct = keyed.groupby("order_id")[field].nunique(dropna=True)
        for order_id in distinct[distinct > 1].index.tolist():
            conflicts.setdefault(str(order_id), []).append(field)
    return {order_id: sorted(fields) for order_id, fields in conflicts.items()}


def _single_or_none(group: pd.DataFrame, field: str) -> object:
    """The invariant value of a field within a group, or None when absent."""
    vals = [v for v in group[field].tolist() if v is not None]
    if not vals:
        return None
    first = vals[0]
    if any(v != first for v in vals[1:]):
        return None
    return first


def _decimal_sum(values: list[Decimal | None]) -> Decimal:
    total = Decimal("0")
    for value in values:
        if value is not None:
            total += value
    return total


def _int_sum(values: list[int | None]) -> int:
    return sum(v for v in values if v is not None)


def build_orders(items: pd.DataFrame, session_id: str) -> pd.DataFrame:
    """Aggregate orders from items exactly once (caller enforces the gate)."""
    keyed = items[items["order_id"].notna()].sort_values(
        ["order_id", "source_row_number"]
    )
    rows: list[dict[str, object]] = []
    for order_id, group in keyed.groupby("order_id", sort=True):
        rows.append(
            {
                "order_id": str(order_id),
                "session_id": session_id,
                "customer_id": _single_or_none(group, "customer_id"),
                "order_timestamp": _single_or_none(group, "order_timestamp"),
                "order_status": _single_or_none(group, "order_status"),
                "shipping_mode": _single_or_none(group, "shipping_mode"),
                "customer_segment": _single_or_none(group, "customer_segment"),
                "destination_country": _single_or_none(group, "destination_country"),
                "destination_region": _single_or_none(group, "destination_region"),
                "destination_market": _single_or_none(group, "destination_market"),
                "department_name": _single_or_none(group, "department_name"),
                "category_name": _single_or_none(group, "category_name"),
                "product_name": _single_or_none(group, "product_name"),
                "scheduled_shipping_days": _single_or_none(
                    group, "scheduled_shipping_days"
                ),
                "actual_shipping_days": _single_or_none(group, "actual_shipping_days"),
                "shipment_outcome": _single_or_none(group, "shipment_outcome"),
                "is_late": _single_or_none(group, "is_late"),
                "line_count": int(len(group)),
                "total_units": _int_sum(group["quantity_units"].tolist()),
                "gross_value": _decimal_sum(group["gross_sales"].tolist()),
                "discount_total": _decimal_sum(group["discount_amount"].tolist()),
                "net_value": _decimal_sum(group["net_sales"].tolist()),
                "profit_total": _decimal_sum(group["profit_amount"].tolist()),
            }
        )
    frame = pd.DataFrame(rows, columns=list(ORDER_COLUMNS))
    return frame


def dim_conflicts(
    items: pd.DataFrame, key: str, fields: tuple[str, ...]
) -> dict[str, list[str]]:
    """Keys whose identifying dims disagree (products/customers gate)."""
    keyed = items[items[key].notna()]
    conflicts: dict[str, list[str]] = {}
    if len(keyed) == 0:
        return conflicts
    for field in fields:
        distinct = keyed.groupby(key)[field].nunique(dropna=True)
        for key_value in distinct[distinct > 1].index.tolist():
            conflicts.setdefault(str(key_value), []).append(field)
    return {k: sorted(v) for k, v in conflicts.items()}


def build_products(items: pd.DataFrame) -> pd.DataFrame:
    """Aggregate products from items exactly once (caller enforces the gate)."""
    keyed = items[items["product_id"].notna()]
    rows: list[dict[str, object]] = []
    for product_id, group in keyed.groupby("product_id", sort=True):
        rows.append(
            {
                "product_id": str(product_id),
                "category_id": _single_or_none(group, "category_id"),
                "department_name": _single_or_none(group, "department_name"),
                "category_name": _single_or_none(group, "category_name"),
                "product_name": _single_or_none(group, "product_name"),
                "line_count": int(len(group)),
                "total_units": _int_sum(group["quantity_units"].tolist()),
                "total_net_value": _decimal_sum(group["net_sales"].tolist()),
                "total_profit_amount": _decimal_sum(group["profit_amount"].tolist()),
            }
        )
    return pd.DataFrame(rows, columns=list(PRODUCT_COLUMNS))


def build_customers(items: pd.DataFrame) -> pd.DataFrame:
    """Aggregate sanitized customers (coarse geo only; V1 geo always null)."""
    keyed = items[items["customer_id"].notna()]
    rows: list[dict[str, object]] = []
    for customer_id, group in keyed.groupby("customer_id", sort=True):
        order_ids = {v for v in group["order_id"].tolist() if v is not None}
        rows.append(
            {
                "customer_id": str(customer_id),
                "customer_segment": _single_or_none(group, "customer_segment"),
                "customer_country": None,
                "customer_state": None,
                "customer_city": None,
                "order_count": len(order_ids),
                "total_net_value": _decimal_sum(group["net_sales"].tolist()),
                "total_profit_amount": _decimal_sum(group["profit_amount"].tolist()),
            }
        )
    return pd.DataFrame(rows, columns=list(CUSTOMER_COLUMNS))


def build_calendar(items: pd.DataFrame) -> pd.DataFrame:
    """Calendar rows for distinct canonical order dates present (naive)."""
    dates = sorted({d for d in items["order_date"].tolist() if d is not None})
    rows: list[dict[str, object]] = []
    for day in dates:
        iso_year, iso_week, iso_day = day.isocalendar()
        rows.append(
            {
                "date": day,
                "year": day.year,
                "quarter": (day.month - 1) // 3 + 1,
                "month": day.month,
                "iso_week": iso_week,
                "day_of_week": iso_day,
                "is_weekend": iso_day >= 6,
            }
        )
    _ = iso_year  # calendar year (`year`) is the join key, not ISO year.
    return pd.DataFrame(rows, columns=list(CALENDAR_COLUMNS))


def _fmt_datetime(value: datetime | None) -> str:
    return "" if value is None else value.strftime("%Y-%m-%dT%H:%M:%S")


def _fmt_date(value: object) -> str:
    return "" if value is None else str(value)


def _fmt_decimal(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def _fmt_bool(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def _fmt_any(value: object) -> str:
    """Render one canonical cell: nulls empty, dates ISO, money plain.

    Nullable integer columns arrive as float64 (integral floats) and
    nullable timestamps as NaT: both render in their logical form.
    """
    if value is None:
        return ""
    if value is pd.NaT:  # NaT subclasses datetime: catch before the date branch
        return ""
    if isinstance(value, bool):
        return _fmt_bool(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, Decimal):
        return _fmt_decimal(value)
    if isinstance(value, datetime):
        return _fmt_datetime(value)
    if isinstance(value, date):
        return _fmt_date(value)
    if isinstance(value, str):
        return value
    if value is pd.NaT or value is pd.NA:  # other missing sentinels
        return ""
    return str(value)


def to_string_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Deterministic string rendering: nulls empty, dates ISO, money plain."""
    rendered = pd.DataFrame(
        {
            column: [_fmt_any(v) for v in frame[column].tolist()]
            for column in frame.columns
        }
    )
    return rendered.astype(str)


def write_canonical_csv(frame: pd.DataFrame, final_path: str) -> None:
    """Write one canonical table atomically via a unique temp sibling."""
    tmp_path = f"{final_path}.{os.urandom(8).hex()}.tmp"
    try:
        to_string_frame(frame).to_csv(
            tmp_path, index=False, encoding="utf-8", lineterminator="\n"
        )
        os.replace(tmp_path, final_path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _fail_canonicalization(
    paths: session_store.SessionPaths,
    manifest: SessionManifest,
    error: IngestionError,
    now_iso: str,
) -> SessionManifest:
    """Terminal failure: ADR-028 raw/derived removal, metadata kept."""
    strip_session_payloads(paths)
    transitioned = manifest.model_copy(
        update={
            "state": STATE_FAILED,
            "stage": STAGE_CANONICALIZING,
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
    logger.info("canonicalization_failed code=%s", error.code)
    return transitioned


def _artifact_matches_session(
    stored: CanonicalArtifact,
    manifest: SessionManifest,
    paths: session_store.SessionPaths,
) -> bool:
    """Provenance gate before adopting an on-disk canonical report.

    Stored metadata is never trusted on its own: every listed table's SHA is
    recomputed, and the live profiling/cleaning artifacts must match the
    recorded input identity (profiledAt/cleanedAt + source rows), so a stale
    or foreign report cannot be adopted. App/schema versions pin the code.
    """
    if not (
        stored.sessionId == manifest.sessionId
        and stored.sourceSha256 == manifest.sha256
        and stored.appVersion == settings.app_version
        and stored.schemaVersion == settings.schema_version
        and session_store.read_schema_report(paths) is not None
        and os.path.isfile(paths.raw)
        and os.path.isfile(session_store.cleaned_path(paths))
    ):
        return False
    profile = session_store.read_profiling_report(paths)
    cleaning = session_store.read_cleaning_report(paths)
    if (
        profile is None
        or cleaning is None
        or profile.profiledAt != stored.inputProfiledAt
        or cleaning.cleanedAt != stored.inputCleanedAt
        or profile.sourceRows != stored.sourceRows
        or cleaning.outputRows != stored.sourceRows
    ):
        return False
    try:
        for table in stored.tables:
            full = os.path.join(paths.root, table.name)
            if sha256_file(full) != table.sha256:
                return False
    except OSError:
        return False
    return True


def _adopt_report(
    paths: session_store.SessionPaths,
    manifest: SessionManifest,
    stored: CanonicalArtifact,
    now_iso: str,
) -> SessionManifest:
    """Adopt a verified report: ANALYZING on complete, parked if blocked."""
    state = STATE_ANALYZING if stored.status == "complete" else STATE_CANONICALIZING
    progress = (
        session_store.make_analyzing_progress()
        if state == STATE_ANALYZING
        else session_store.make_canonicalizing_progress()
    )
    transitioned = manifest.model_copy(
        update={
            "state": state,
            "stage": state,
            "progress": progress,
            "canonicalArtifact": (
                f"{session_store.DERIVED_DIRNAME}/"
                f"{session_store.CANONICAL_ARTIFACT_FILENAME}"
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
    logger.info("canonicalization_adopted status=%s", stored.status)
    return transitioned


def ensure_canonicalized(
    paths: session_store.SessionPaths, manifest: SessionManifest, now_iso: str
) -> SessionManifest:
    """Run Phase-8 canonicalization once if still pending; else return stored.

    Success parks at ANALYZING (no KPI analysis runs). Governed quality
    blocks (duplicate item keys, order-invariance conflicts) park at
    CANONICALIZING with the raw retained — a gate, not a terminal failure.
    Never mutates raw; verified by SHA before and after.
    """
    if manifest.state != STATE_CANONICALIZING or manifest.canonicalArtifact is not None:
        return manifest
    stored = session_store.read_canonical_report(paths)
    if stored is not None and _artifact_matches_session(stored, manifest, paths):
        return _adopt_report(paths, manifest, stored, now_iso)

    report = session_store.read_schema_report(paths)
    profile_artifact = session_store.read_profiling_report(paths)
    cleaning_artifact = session_store.read_cleaning_report(paths)
    if report is None or profile_artifact is None or cleaning_artifact is None:
        return _fail_canonicalization(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CANONICALIZING,
                "The profiling evidence could not be read. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    if not os.path.isfile(paths.raw) or not os.path.isfile(
        session_store.cleaned_path(paths)
    ):
        return _fail_canonicalization(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CANONICALIZING,
                "The stored upload could not be read. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    if sha256_file(paths.raw) != manifest.sha256:
        return _fail_canonicalization(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CANONICALIZING,
                "The stored upload failed its integrity check. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    # Cleaned lineage: recomputed SHA plus the live cleaning identity must
    # match before positional provenance (source_row_number) is trusted.
    try:
        cleaned_sha = sha256_file(session_store.cleaned_path(paths))
    except OSError:
        logger.warning("canonicalization_header_io_error")
        return _fail_canonicalization(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CANONICALIZING,
                "The stored upload could not be read. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    if cleaned_sha != cleaning_artifact.outputSha256:
        return _fail_canonicalization(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CANONICALIZING,
                "The cleaned working file failed its integrity check. "
                "Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )

    from app.profiling import build_profile_inputs, read_staged_frame

    inputs = build_profile_inputs(report)
    try:
        cleaned = read_staged_frame(
            session_store.cleaned_path(paths),
            "utf-8",
            [c for c in report.sourceColumns if c in set(inputs.col_of.values())],
        )
    except IngestionError as exc:
        return _fail_canonicalization(paths, manifest, exc, now_iso)
    if len(cleaned) != cleaning_artifact.outputRows or len(cleaned) == 0:
        return _fail_canonicalization(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CANONICALIZING,
                "The cleaned working file failed its integrity check. "
                "Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )

    derivations = [
        "shipment_outcome/is_late from authoritative day fields; "
        "SHIPPING_CANCELED + is_late null for 'Shipping canceled' rows; "
        "Late_delivery_risk never classifies",
        "schedule_variance_days = actual - scheduled (null when cancelled)",
        "order_date = date(order_timestamp)",
        "orders/products/customers aggregates summed from items exactly once; "
        "reported net_sales authoritative; negative profit retained",
        "unknown enums -> UNKNOWN_FLAGGED; missing/unparseable -> null",
        "calendar parts from distinct canonical order_date values",
    ]
    notes = [
        "source_row_number is the 1-based logical data-row ordinal in raw.csv",
        "customer geography is null in V1: no governed customer-side geo "
        "columns exist; never derived from destinations",
        "order merch dims are single-value-or-null (multi-valued is legitimate)",
    ]

    # DQ-KEY-001 gate BEFORE any canonical work (catalogue: blocks the
    # order_items build; nothing is deduplicated).
    raw_item_ids = cleaned[inputs.col_of["order_item_id"]].astype(str)
    dupes = duplicate_item_rows(raw_item_ids)
    if dupes:
        return _park_blocked(
            paths,
            manifest,
            profile_artifact,
            cleaning_artifact,
            len(cleaned),
            derivations,
            notes,
            CanonicalBlocker(
                code=DUPLICATE_ITEM_KEY,
                stage=STAGE_CANONICALIZING,
                scope="order_items",
                detail=(
                    f"{dupes} order-item line(s) share a duplicate Order Item "
                    "Id. Nothing was deduplicated; the canonical build stays "
                    "blocked until the input is fixed or replaced."
                ),
            ),
            tables=[],
            reconciliation=CanonicalReconciliation(
                itemRows=len(cleaned),
                itemsWithOrder=0,
                orderCount=None,
                linesInOrders=None,
                foreignKeysReconcile=None,
                totalsReconcile=None,
            ),
            now_iso=now_iso,
        )

    try:
        items = build_order_items(cleaned, inputs.col_of, manifest.sessionId)
    except Exception:  # never leak values; terminal per ADR-028
        logger.warning("canonicalization_unexpected_error")
        return _fail_canonicalization(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CANONICALIZING,
                "The upload could not be canonicalized. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    del cleaned

    # File-wide DATE-001: rows exist but no parseable order date (catalogue:
    # file-wide failure blocks canonicalization; per-row failures travel to
    # KPI analysis as nulls).
    if items["order_timestamp"].notna().sum() == 0:
        return _park_blocked(
            paths,
            manifest,
            profile_artifact,
            cleaning_artifact,
            len(items),
            derivations,
            notes,
            CanonicalBlocker(
                code="DQ-DATE-001",
                stage=STAGE_CANONICALIZING,
                scope="order_items",
                detail=(
                    f"{len(items)} order-item line(s) have no parseable order "
                    "date under the explicit month-first parse. The canonical "
                    "build stays blocked until the input is fixed or replaced."
                ),
            ),
            tables=[],
            reconciliation=CanonicalReconciliation(
                itemRows=len(items),
                itemsWithOrder=int(items["order_id"].notna().sum()),
                orderCount=None,
                linesInOrders=None,
                foreignKeysReconcile=None,
                totalsReconcile=None,
            ),
            now_iso=now_iso,
        )

    # Builder self-check (DQ-BUSINESS-001): cancelled adherence is null.
    cancelled = items["shipment_outcome"] == "SHIPPING_CANCELED"
    if bool((cancelled & items["is_late"].notna()).any()) or bool(
        (cancelled & items["schedule_variance_days"].notna()).any()
    ):
        logger.warning("canonicalization_self_check_failed")
        return _fail_canonicalization(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CANONICALIZING,
                "Canonicalization failed its consistency check. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )

    gate_conflicts = order_gate_conflicts(items)
    orders = None
    orders_blocker: CanonicalBlocker | None = None
    if gate_conflicts:
        by_field: dict[str, int] = {}
        for fields in gate_conflicts.values():
            for field in fields:
                by_field[field] = by_field.get(field, 0) + 1
        breakdown = ", ".join(f"{f}: {c}" for f, c in sorted(by_field.items()))
        orders_blocker = CanonicalBlocker(
            code=ORDER_INVARIANCE_CONFLICT,
            stage=STAGE_CANONICALIZING,
            scope="orders",
            detail=(
                f"{len(gate_conflicts)} order(s) disagree across lines on at "
                f"least one order-level attribute ({breakdown}). The orders "
                "build stays blocked; no first row is picked."
            ),
        )

    product_conflicts = dim_conflicts(items, "product_id", PRODUCT_DIM_FIELDS)
    profile_products_flagged = _profile_rule_count(profile_artifact, "DQ-GRAIN-003")
    products = None
    products_blocker: CanonicalBlocker | None = None
    if product_conflicts or profile_products_flagged:
        if product_conflicts:
            products_detail = (
                f"{len(product_conflicts)} product(s) disagree across lines on "
                "identifying dims. The products build stays blocked; no "
                "representative value is picked."
            )
        else:
            products_detail = (
                f"Profiling detected {profile_products_flagged} conflicting "
                "product(s) under DQ-GRAIN-003 that the cleaned re-check "
                "could not reproduce (stripped raw vs exact cleaned text). "
                "The products build stays blocked; no representative value "
                "is picked."
            )
        products_blocker = CanonicalBlocker(
            code=PRODUCT_INVARIANCE_CONFLICT,
            stage=STAGE_CANONICALIZING,
            scope="products",
            detail=products_detail,
        )

    customer_conflicts = dim_conflicts(items, "customer_id", ("customer_segment",))
    profile_customers_flagged = _profile_rule_count(profile_artifact, "DQ-GRAIN-004")
    customers = None
    customers_blocker: CanonicalBlocker | None = None
    if customer_conflicts or profile_customers_flagged:
        if customer_conflicts:
            customers_detail = (
                f"{len(customer_conflicts)} customer(s) disagree across lines "
                "on customer_segment. The customers build stays blocked."
            )
        else:
            customers_detail = (
                f"Profiling detected {profile_customers_flagged} conflicting "
                "customer(s) under DQ-GRAIN-004 that the cleaned re-check "
                "could not reproduce (stripped raw vs exact cleaned text). "
                "The customers build stays blocked."
            )
        customers_blocker = CanonicalBlocker(
            code=CUSTOMER_INVARIANCE_CONFLICT,
            stage=STAGE_CANONICALIZING,
            scope="customers_sanitized",
            detail=customers_detail,
        )

    tables: list[CanonicalTableIdentity] = []
    try:
        _persist(
            paths,
            session_store.CANONICAL_ITEMS_FILENAME,
            "order_items",
            items.sort_values("source_row_number"),
            tables,
        )
        calendar = build_calendar(items)
        _persist(
            paths,
            session_store.CANONICAL_CALENDAR_FILENAME,
            "calendar",
            calendar,
            tables,
        )
        issues = _issue_frame(profile_artifact)
        _persist(
            paths,
            session_store.CANONICAL_ISSUES_FILENAME,
            "data_quality_issues",
            issues,
            tables,
        )
        if products_blocker is None:
            products = build_products(items)
            _persist(
                paths,
                session_store.CANONICAL_PRODUCTS_FILENAME,
                "products",
                products.sort_values("product_id"),
                tables,
            )
        if customers_blocker is None:
            customers = build_customers(items)
            _persist(
                paths,
                session_store.CANONICAL_CUSTOMERS_FILENAME,
                "customers_sanitized",
                customers.sort_values("customer_id"),
                tables,
            )
        if orders_blocker is None:
            built_orders = build_orders(items, manifest.sessionId)
            _persist(
                paths,
                session_store.CANONICAL_ORDERS_FILENAME,
                "orders",
                built_orders.sort_values("order_id"),
                tables,
            )
            orders = built_orders
    except OSError:
        # Artifact write failure: leave the session rerunnable (no false claim).
        return manifest
    except Exception:  # never leak values; terminal per ADR-028
        logger.warning("canonicalization_unexpected_error")
        return _fail_canonicalization(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CANONICALIZING,
                "The upload could not be canonicalized. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )

    blocker = orders_blocker or products_blocker or customers_blocker
    if blocker is not None:
        return _park_blocked(
            paths,
            manifest,
            profile_artifact,
            cleaning_artifact,
            len(items),
            derivations,
            notes,
            blocker,
            tables=tables,
            reconciliation=CanonicalReconciliation(
                itemRows=len(items),
                itemsWithOrder=int(items["order_id"].notna().sum()),
                orderCount=None if orders is None else int(len(orders)),
                linesInOrders=None,
                foreignKeysReconcile=None,
                totalsReconcile=None,
            ),
            now_iso=now_iso,
        )
    assert orders is not None
    reconciliation = _reconcile(items, orders)
    if reconciliation is None:
        logger.warning("canonicalization_self_check_failed")
        return _fail_canonicalization(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CANONICALIZING,
                "Canonicalization failed its consistency check. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    # Raw immutability proof: SHA unchanged across the canonical pass.
    if sha256_file(paths.raw) != manifest.sha256:
        logger.warning("canonicalization_self_check_failed")
        return _fail_canonicalization(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CANONICALIZING,
                "The stored upload failed its integrity check. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    artifact = CanonicalArtifact(
        sessionId=manifest.sessionId,
        appVersion=settings.app_version,
        schemaVersion=settings.schema_version,
        sourceSha256=manifest.sha256,
        sourceRows=len(items),
        inputProfiledAt=profile_artifact.profiledAt,
        inputCleanedAt=cleaning_artifact.cleanedAt,
        status="complete",
        blocker=None,
        tables=tables,
        reconciliation=reconciliation,
        derivations=derivations,
        notes=notes,
        canonicalizedAt=now_iso,
    )
    try:
        session_store.write_canonical_report(paths, artifact)
    except OSError:
        return manifest
    transitioned = manifest.model_copy(
        update={
            "state": STATE_ANALYZING,
            "stage": STATE_ANALYZING,
            "progress": session_store.make_analyzing_progress(),
            "canonicalArtifact": (
                f"{session_store.DERIVED_DIRNAME}/"
                f"{session_store.CANONICAL_ARTIFACT_FILENAME}"
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
        "canonicalized items=%d orders=%d",
        len(items),
        len(orders),
    )
    return transitioned


def _profile_rule_count(profile_artifact: object, rule_id: str) -> int:
    """Profiling-evidence count for one DQ rule (0 when never triggered).

    Enforcement input for the union gate: canonicalization blocks when
    either profiling evidence or the defensive cleaned-data re-check reports
    a conflict, so a conflict can never be built through disagreement.
    Counts only — no values.
    """
    from app.schemas import ProfilingArtifact

    assert isinstance(profile_artifact, ProfilingArtifact)
    for issue in profile_artifact.issues:
        if issue.ruleId == rule_id:
            return int(issue.count)
    return 0


def _issue_frame(profile_artifact: object) -> pd.DataFrame:
    """Carry profiling detection evidence into the canonical issues table."""
    from app.schemas import ProfilingArtifact

    assert isinstance(profile_artifact, ProfilingArtifact)
    rows = [
        {
            "rule_id": issue.ruleId,
            "severity": issue.severity,
            "count": issue.count,
            "treatment": issue.treatment,
            "blocked_stage": issue.blockedStage,
            "message": profile_artifact.issueMessages.get(issue.ruleId, ""),
        }
        for issue in profile_artifact.issues
    ]
    frame = pd.DataFrame(rows, columns=list(ISSUE_COLUMNS))
    return frame.sort_values("rule_id").reset_index(drop=True)


def _persist(
    paths: session_store.SessionPaths,
    filename: str,
    table: str,
    frame: pd.DataFrame,
    tables: list[CanonicalTableIdentity],
) -> None:
    """Write one table and record its identity (raises OSError on failure)."""
    full = session_store.canonical_table_path(paths, filename)
    write_canonical_csv(frame, full)
    tables.append(
        CanonicalTableIdentity(
            name=f"{session_store.DERIVED_DIRNAME}/{filename}",
            table=table,
            rows=int(len(frame)),
            sha256=sha256_file(full),
            columns=list(frame.columns),
        )
    )


def _reconcile(
    items: pd.DataFrame, orders: pd.DataFrame
) -> CanonicalReconciliation | None:
    """GRAIN-002 self-check: item aggregates reconcile exactly (None = bug)."""
    items_with_order = int(items["order_id"].notna().sum())
    lines_in_orders = int(orders["line_count"].sum())
    fk_items = {v for v in items["order_id"].tolist() if v is not None}
    fk_orders = set(orders["order_id"].tolist())
    foreign_keys = fk_items == fk_orders and lines_in_orders == items_with_order
    totals = True
    pairs = (
        ("gross_sales", "gross_value"),
        ("discount_amount", "discount_total"),
        ("net_sales", "net_value"),
        ("profit_amount", "profit_total"),
    )
    for item_field, order_field in pairs:
        if _decimal_sum(items[item_field].tolist()) != _decimal_sum(
            orders[order_field].tolist()
        ):
            totals = False
    if _int_sum(items["quantity_units"].tolist()) != int(orders["total_units"].sum()):
        totals = False
    if not (foreign_keys and totals):
        return None
    return CanonicalReconciliation(
        itemRows=int(len(items)),
        itemsWithOrder=items_with_order,
        orderCount=int(len(orders)),
        linesInOrders=lines_in_orders,
        foreignKeysReconcile=True,
        totalsReconcile=True,
    )


def _park_blocked(
    paths: session_store.SessionPaths,
    manifest: SessionManifest,
    profile_artifact: object,
    cleaning_artifact: object,
    source_rows: int,
    derivations: list[str],
    notes: list[str],
    blocker: CanonicalBlocker,
    tables: list[CanonicalTableIdentity],
    reconciliation: CanonicalReconciliation,
    now_iso: str,
) -> SessionManifest:
    """Persist the blocked-build report and park at CANONICALIZING.

    A governed quality gate: the raw is retained, built tables stay, and no
    terminal failure is recorded. The session advances only when the input
    is fixed or replaced.
    """
    from app.schemas import CleaningArtifact, ProfilingArtifact

    assert isinstance(profile_artifact, ProfilingArtifact)
    assert isinstance(cleaning_artifact, CleaningArtifact)
    artifact = CanonicalArtifact(
        sessionId=manifest.sessionId,
        appVersion=settings.app_version,
        schemaVersion=settings.schema_version,
        sourceSha256=manifest.sha256,
        sourceRows=source_rows,
        inputProfiledAt=profile_artifact.profiledAt,
        inputCleanedAt=cleaning_artifact.cleanedAt,
        status="blocked",
        blocker=blocker,
        tables=tables,
        reconciliation=reconciliation,
        derivations=derivations,
        notes=notes,
        canonicalizedAt=now_iso,
    )
    try:
        session_store.write_canonical_report(paths, artifact)
    except OSError:
        return manifest
    transitioned = manifest.model_copy(
        update={
            "state": STATE_CANONICALIZING,
            "stage": STATE_CANONICALIZING,
            "progress": session_store.make_canonicalizing_progress(),
            "canonicalArtifact": (
                f"{session_store.DERIVED_DIRNAME}/"
                f"{session_store.CANONICAL_ARTIFACT_FILENAME}"
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
        "canonicalization_blocked code=%s scope=%s",
        blocker.code,
        blocker.scope,
    )
    return transitioned


__all__ = [
    "build_calendar",
    "build_customers",
    "build_order_items",
    "build_orders",
    "build_products",
    "dim_conflicts",
    "duplicate_item_rows",
    "ensure_canonicalized",
    "map_enum",
    "order_gate_conflicts",
    "recover_canonicalizing_sessions",
    "run_canonicalization",
    "to_string_frame",
    "write_canonical_csv",
]


_CANONICALIZATION_IN_PROGRESS: set[str] = set()


def run_canonicalization(session_id: str) -> SessionManifest | None:
    """Execute one canonicalization pass for a session (pipeline/recovery body).

    Safe against reset races: a deleted session (no manifest) is a no-op
    and is never resurrected. Returns the resulting manifest, or None when
    there was nothing to do.
    """
    if not session_store.is_valid_session_id(session_id):
        return None
    if session_id in _CANONICALIZATION_IN_PROGRESS:
        return None
    _CANONICALIZATION_IN_PROGRESS.add(session_id)
    try:
        paths = session_store.session_paths(settings.session_root, session_id)
        manifest = session_store.read_manifest(paths)
        if manifest is None:
            return None
        return ensure_canonicalized(paths, manifest, session_store.utcnow_naive_iso())
    finally:
        _CANONICALIZATION_IN_PROGRESS.discard(session_id)


def recover_canonicalizing_sessions(session_root: str) -> int:
    """Startup recovery: canonicalize leftover CANONICALIZING sessions.

    Covers the crash window between cleaning success and canonicalization
    completion. Sessions already carrying an adopted report (complete or
    blocked) are left alone; expired trees are left to the sweep; later
    stages (KPI analysis) never start.
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
            or manifest.state != STATE_CANONICALIZING
            or manifest.canonicalArtifact is not None
        ):
            continue
        if session_store.read_canonical_report(paths) is not None:
            continue
        if session_store.is_expired(manifest, datetime.now()):
            continue
        run_canonicalization(entry)
        recovered += 1
    if recovered:
        logger.info("canonicalization_recovery_canonicalized=%d", recovered)
    return recovered
