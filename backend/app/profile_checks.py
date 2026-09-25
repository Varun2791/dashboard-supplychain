"""Phase-6 value-level profiling and data-quality detection (read-only).

Pure detection over an in-memory string dataframe plus the Phase-5 mapping.
Nothing here mutates data, writes files, or serves HTTP: orchestration lives
in `app/profiling.py`.

Implementation interpretations (bounded by governance, documented here):

- Missing values are empty or whitespace-only fields only. Textual
  ``null``/``N/A``/``NA``, zero, and false-like values are legitimate source
  values and are never treated as missing.
- Parse failures are tracked separately from missing values.
- Identifiers stay strings: the frame is staged with pyarrow-backed
  string dtypes (ADR-026) projected to governed columns only, so
  numeric-looking IDs are never floated and unknown/excluded columns are
  never materialized.
- Timestamps use explicit month-first formats only
  (``%m-%d-%Y`` with optional ``%H:%M`` / ``%H:%M:%S``), timezone-naive.
  No locale guessing, no day-first reinterpretation.
- Integers must be plain digit strings (optional sign); money must be plain
  decimal strings. No thousands separators, currency symbols, or locale
  decimals. Commercial reconciliation uses ``Decimal`` with the governed
  ``$0.05`` per-line tolerance (ADR-008); net stays authoritative.
- Enum membership is evaluated on whitespace-trimmed values against the
  exact governed sets (canonical-schema section 7). A value that matches
  only after trimming is reported under DQ-CAT-005 (fixable by cleaning),
  not as an unknown enum, so root causes are not double-counted.
- ``order_status`` matches the eight canonical spellings exactly (source
  examples in governance are already upper-snake). Shipping mode and
  customer segment enforce only the source spellings with a verbatim
  instance in canonical-schema section 7 ("Standard Class", "Same Day",
  "Consumer", "Home Office"); inversion-derived spellings without a
  verbatim instance are not enforced (see the governance-consistency note
  at the enum sets). The delivery-status domain beyond the exact
  cancel signal ``Shipping canceled`` is not governed, so DQ-CAT-004 is
  deferred (see ``RULES_DEFERRED``); cancel recognition is still used
  internally for rule populations.
- Order invariance compares stripped raw text per governed order-level
  field (timestamps compare parsed values when both parse, else raw text).
  Only distinct non-missing values conflict; missingness is reported
  separately. Product/category merchandising fields legitimately vary
  within an order and are never invariance-checked.
- Dimension invariance (DQ-GRAIN-003/004, ADR-036) uses the same
  stripped-text, non-missing-only comparison at product/customer grain:
  merch fields vary legitimately within an order but must agree within a
  product; customer_segment must agree within a customer.
- Privacy detection (DQ-PRIVACY-001/002) is a documented keyword heuristic
  over header tokens because exact personal-header strings are unspecified
  in governance. It is INFO-only and reports counts, never header names.
- DQ-DATE-004 uses a >=12 h gap among Same-Day rows with both timestamps
  parseable as the implementation reading of the "~12 h" pattern.
- Negative profit is valid (ADR-017): DQ-NUM-003 only flags
  ``profit/net < -1.0`` for investigation; nothing is removed or clipped.
- Timestamp-derived durations are diagnostic only (ADR-015): the supplied
  day fields drive DQ-BUSINESS-003 expectations, never timestamps.
- ``Late_delivery_risk`` is validation evidence only (ADR-018/030): it is
  compared, never used as a lateness input, and no ``is_late`` derivation
  is produced here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Final

import pandas as pd

from app.schema_registry import CANCEL_SIGNAL_VALUE

# ---------------------------------------------------------------------------
# Governed detection vocabularies
# ---------------------------------------------------------------------------

SOURCE_GRAIN: Final = "order_item"

ID_FIELDS: Final = (
    "order_id",
    "order_item_id",
    "customer_id",
    "product_id",
    "category_id",
)

TIMESTAMP_FIELDS: Final = ("order_timestamp", "ship_timestamp")

MONEY_FIELDS: Final = (
    "gross_sales",
    "discount_amount",
    "net_sales",
    "profit_amount",
    "unit_price",
)

INT_FIELDS: Final = (
    "quantity_units",
    "actual_shipping_days",
    "scheduled_shipping_days",
)

ENUM_FIELDS: Final = ("order_status", "shipping_mode", "customer_segment")

LABEL_FIELDS: Final = (
    "destination_country",
    "destination_region",
    "destination_market",
    "department_name",
    "category_name",
    "product_name",
)

# Order-level attributes that must agree within one order (DQ-GRAIN-001).
# Merchandising/product fields vary legitimately across lines and are out.
INVARIANCE_FIELDS: Final = (
    "customer_id",
    "order_status",
    "shipping_mode",
    "order_timestamp",
    "ship_timestamp",
    "actual_shipping_days",
    "scheduled_shipping_days",
    "destination_country",
    "destination_region",
    "destination_market",
)

# Product identifying dims that must agree within one product (DQ-GRAIN-003,
# ADR-036). unit_price is deliberately absent: no reference-price concept.
PRODUCT_INVARIANCE_FIELDS: Final = (
    "category_id",
    "department_name",
    "category_name",
    "product_name",
)

# Customer identifying dims that must agree within one customer (DQ-GRAIN-004,
# ADR-036). Only the segment: customer-side geography is nullable by
# construction and never imputed, so it cannot conflict.
CUSTOMER_INVARIANCE_FIELDS: Final = ("customer_segment",)

ORDER_STATUS_VALUES: Final = frozenset(
    {
        "COMPLETE",
        "CLOSED",
        "PENDING",
        "PROCESSING",
        "ON_HOLD",
        "CANCELED",
        "PAYMENT_REVIEW",
        "SUSPECTED_FRAUD",
    }
)

# Source spellings evidenced in canonical-schema section 7 ("Source examples
# mapped exactly"). Governance-consistency note (pre-commit audit): the
# canonical sets are closed and explicit, but the source column uses "e.g."
# exemplars, so only spellings with a verbatim instance in accepted text
# are enforced:
# - order_status: canonical cell lists all 8 values with no "e.g.", source
#   examples are identity-spelled, full table verified at implementation —
#   enforced as the closed 8-set;
# - shipping_mode: only "Standard Class" and "Same Day" are verbatim;
# - customer_segment: only "Consumer" and "Home Office" are verbatim.
# "Second Class", "First Class", and "Corporate" follow the demonstrated
# Title-Case inversion but have no verbatim instance, so they are NOT
# enforced as known (inversion is not authority). Such values take the
# governed UNKNOWN path (ADR-030: counted, reported, excluded from split
# views, never coerced, never blocking) until reference-file confirmation
# records the exact strings in governance.
SHIPPING_MODE_VALUES: Final = frozenset({"Standard Class", "Same Day"})

CUSTOMER_SEGMENT_VALUES: Final = frozenset({"Consumer", "Home Office"})

SAME_DAY_SOURCE_VALUE: Final = "Same Day"

# Explicit month-first timestamp formats, timezone-naive. No day-first,
# no locale guessing.
TIMESTAMP_FORMATS: Final = (
    "%m-%d-%Y %H:%M:%S",
    "%m-%d-%Y %H:%M",
    "%m-%d-%Y",
)

NET_TOLERANCE: Final = Decimal("0.05")
PROFIT_RATIO_THRESHOLD: Final = Decimal("-1.0")
SAME_DAY_GAP: Final = timedelta(hours=12)

INT_PATTERN: Final = r"[+-]?\d+"
MONEY_PATTERN: Final = r"[+-]?\d+(\.\d+)?"

# Privacy header heuristics (token-exact, case-insensitive). Documented
# interpretation: exact personal/precise-geo header strings are unspecified
# in governance, so detection is keyword-based, INFO-only, count-only.
PRIVACY_PERSONAL_TOKENS: Final = frozenset(
    {"firstname", "lastname", "email", "password", "street"}
)
PRIVACY_PERSONAL_PHRASES: Final = (("first", "name"), ("last", "name"))

PRIVACY_GEO_TOKENS: Final = frozenset(
    {
        "latitude",
        "longitude",
        "lat",
        "lon",
        "lng",
        "zip",
        "zipcode",
        "postcode",
        "postal",
        "ip",
    }
)


@dataclass(frozen=True)
class RuleResult:
    """One evaluated PROFILING-stage rule (triggered or not)."""

    rule_id: str
    severity: str
    count: int
    treatment: str
    blocked_stage: str | None
    message: str
    title: str
    fields: tuple[str, ...]
    grain: str
    population: str


@dataclass(frozen=True)
class EvaluatedRule:
    """Catalogue metadata for one executed rule."""

    severity: str
    treatment: str
    blocked_stage: str | None
    title: str
    fields: tuple[str, ...]
    grain: str
    population: str


# Catalogue-exact metadata for every PROFILING-stage rule executed here.
# Severity, treatment, and blocked stage reproduce docs/data-quality-rules.md
# with one governed exception: the catalogue's Treatment column names the
# pipeline's eventual disposition, while `treatment` here is the disposition
# true at profiling time. DQ-CAT-005's catalogue treatment `fixed (trim)`
# is therefore reported as `detected` — cleaning has not run, and profiling
# must never falsely claim a fix (AGENTS.md). The `fixed` counts materialize
# in Phase-7 cleaning reports.
RULES: Final[dict[str, EvaluatedRule]] = {
    "DQ-KEY-001": EvaluatedRule(
        "ERROR",
        "flagged",
        "CANONICALIZATION",
        "Item-ID uniqueness",
        ("order_item_id",),
        "order_item",
        "lines with a non-missing Order Item Id",
    ),
    "DQ-KEY-002": EvaluatedRule(
        "INFO",
        "unchanged",
        None,
        "Order-ID repetition is legitimate",
        ("order_id",),
        "order_item",
        "all lines",
    ),
    "DQ-KEY-003": EvaluatedRule(
        "INFO",
        "unchanged",
        None,
        "Order+Product is not a key",
        ("order_id", "product_id"),
        "order_item",
        "lines with non-missing order and product IDs",
    ),
    "DQ-DATE-001": EvaluatedRule(
        "ERROR",
        "flagged",
        "KPI_ANALYSIS",
        "Order timestamp parseable",
        ("order_timestamp",),
        "order_item",
        "lines with a non-missing order date",
    ),
    "DQ-DATE-002": EvaluatedRule(
        "WARNING",
        "flagged",
        None,
        "Ship timestamp parseable",
        ("ship_timestamp",),
        "order_item",
        "lines with a non-missing shipping date",
    ),
    "DQ-DATE-003": EvaluatedRule(
        "WARNING",
        "flagged",
        None,
        "Ship >= order evidence",
        ("order_timestamp", "ship_timestamp"),
        "order_item",
        "lines with both timestamps parseable",
    ),
    "DQ-DATE-004": EvaluatedRule(
        "INFO",
        "unchanged",
        None,
        "Same-Day pattern noted",
        ("order_timestamp", "ship_timestamp"),
        "order_item",
        "Same Day lines with both timestamps parseable",
    ),
    "DQ-NUM-001": EvaluatedRule(
        "WARNING",
        "flagged",
        None,
        "Non-negative quantities/prices",
        ("quantity_units", "unit_price"),
        "order_item",
        "lines with parseable quantity and unit price",
    ),
    "DQ-NUM-002": EvaluatedRule(
        "WARNING",
        "flagged",
        None,
        "Net-tolerance agreement",
        ("gross_sales", "discount_amount", "net_sales"),
        "order_item",
        "lines with all three amounts parseable",
    ),
    "DQ-NUM-003": EvaluatedRule(
        "WARNING",
        "flagged",
        None,
        "Extreme negative profit retained",
        ("profit_amount", "net_sales"),
        "order_item",
        "lines with parseable profit and non-zero net",
    ),
    "DQ-CAT-001": EvaluatedRule(
        "WARNING",
        "flagged",
        None,
        "Known order status",
        ("order_status",),
        "order_item",
        "lines with a non-missing order status",
    ),
    "DQ-CAT-002": EvaluatedRule(
        "WARNING",
        "flagged",
        None,
        "Known shipping mode",
        ("shipping_mode",),
        "order_item",
        "lines with a non-missing shipping mode",
    ),
    "DQ-CAT-003": EvaluatedRule(
        "WARNING",
        "flagged",
        None,
        "Known customer segment",
        ("customer_segment",),
        "order_item",
        "lines with a non-missing customer segment",
    ),
    "DQ-CAT-005": EvaluatedRule(
        "INFO",
        "detected",
        None,
        "Label whitespace normalization",
        LABEL_FIELDS + ENUM_FIELDS,
        "order_item",
        "lines with padding in governed label fields",
    ),
    "DQ-GRAIN-001": EvaluatedRule(
        "ERROR",
        "flagged",
        "CANONICALIZATION",
        "Order-invariance holds",
        INVARIANCE_FIELDS,
        "order",
        "orders with a non-missing Order Id",
    ),
    "DQ-GRAIN-003": EvaluatedRule(
        "ERROR",
        "flagged",
        "CANONICALIZATION",
        "Product-invariance holds",
        PRODUCT_INVARIANCE_FIELDS,
        "product",
        "products with a non-missing Product Card Id",
    ),
    "DQ-GRAIN-004": EvaluatedRule(
        "ERROR",
        "flagged",
        "CANONICALIZATION",
        "Customer-invariance holds",
        CUSTOMER_INVARIANCE_FIELDS,
        "customer",
        "customers with a non-missing Customer Id",
    ),
    "DQ-BUSINESS-002": EvaluatedRule(
        "WARNING",
        "flagged",
        None,
        "Shipping days plausible",
        ("actual_shipping_days", "scheduled_shipping_days"),
        "order_item",
        "lines with parseable shipping-day fields",
    ),
    "DQ-BUSINESS-003": EvaluatedRule(
        "WARNING",
        "flagged",
        None,
        "Late-risk agreement (audit only)",
        ("actual_shipping_days", "scheduled_shipping_days"),
        "order_item",
        "non-cancelled lines with derivable day outcome",
    ),
    "DQ-PRIVACY-001": EvaluatedRule(
        "INFO",
        "excluded",
        None,
        "Direct personal fields excluded",
        (),
        "column",
        "source headers",
    ),
    "DQ-PRIVACY-002": EvaluatedRule(
        "INFO",
        "excluded",
        None,
        "Precise geo excluded",
        (),
        "column",
        "source headers",
    ),
}

RULE_ORDER: Final = tuple(RULES)

# Governed rules deliberately NOT executed in PROFILING, with reasons.
RULES_DEFERRED: Final = (
    "DQ-SCHEMA-004: redundant-copy value agreement needs governed "
    "column pairings that do not exist (only presence is reported by "
    "schema mapping); deferred pending exact comparison semantics.",
    "DQ-GRAIN-002: totals reconciliation needs built orders; deferred to "
    "canonicalization.",
    "DQ-BUSINESS-001: cancelled-adherence self-check runs after "
    "canonicalization; deferred to canonicalization.",
    "DQ-BUSINESS-004: fraud/cancel separation is a design review gate, "
    "not row detection; no data rule to execute.",
    "DQ-NUM-004: zero-denominator guard applies to requested KPI slices; "
    "deferred to KPI analysis.",
    "DQ-CAT-004: the mapped delivery-status domain beyond the exact "
    "'Shipping canceled' signal is not governed; cancel recognition is "
    "used for rule populations only.",
    "DQ-PRIVACY-003: export privacy gate runs at export time against "
    "candidate export headers; deferred to the export phase.",
)

# Missing required-value coverage has no governing ERROR rule: missingness
# is reported per field in the profile, and this gap is surfaced to the
# caller rather than invented as a rule.
MISSING_VALUE_GAP_NOTE: Final = (
    "No catalogue rule governs missing required values (e.g. a missing "
    "Order Item Id); missingness is reported per field without blocking."
)


# ---------------------------------------------------------------------------
# Low-level parsing helpers (vectorized, deterministic)
# ---------------------------------------------------------------------------


def stripped(frame: pd.DataFrame, column: str) -> pd.Series:
    """Whitespace-trimmed string values for one profiled column."""
    return frame[column].str.strip()


def missing_mask(frame: pd.DataFrame, column: str) -> pd.Series:
    """Missing = empty or whitespace-only (governed definition)."""
    return stripped(frame, column) == ""


def parse_int_values(values: pd.Series) -> pd.Series:
    """Strict integer parse: plain digit strings only, else NaN (float)."""
    ok = values.str.fullmatch(INT_PATTERN)
    return pd.to_numeric(values.where(ok), errors="coerce")


def parse_money_valid(values: pd.Series) -> pd.Series:
    """Boolean mask of strictly valid money strings (non-missing input)."""
    return values.str.fullmatch(MONEY_PATTERN).fillna(False).astype(bool)


def to_decimal_or_none(text: str) -> Decimal | None:
    """Parse one validated money string; None on any failure."""
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_timestamps(values: pd.Series) -> pd.Series:
    """Explicit month-first parse across governed formats; NaT on failure."""
    parsed = pd.to_datetime(values, format=TIMESTAMP_FORMATS[0], errors="coerce")
    for fmt in TIMESTAMP_FORMATS[1:]:
        remaining = parsed.isna()
        if not bool(remaining.any()):
            break
        retry = pd.to_datetime(values.where(remaining), format=fmt, errors="coerce")
        parsed = parsed.where(~remaining, retry)
    return parsed


def enum_known_mask(values: pd.Series, allowed: frozenset[str]) -> pd.Series:
    """Trimmed membership in the exact governed enum set."""
    return values.isin(allowed)


def header_tokens(header: str) -> list[str]:
    """Lowercase alphanumeric tokens of a header for privacy heuristics."""
    token = ""
    tokens: list[str] = []
    for char in header.lower():
        if char.isalnum():
            token += char
        elif token:
            tokens.append(token)
            token = ""
    if token:
        tokens.append(token)
    return tokens


def privacy_counts(source_headers: list[str]) -> tuple[int, int]:
    """Count personal-like and precise-geo-like headers (heuristic, INFO)."""
    personal = 0
    geo = 0
    for header in source_headers:
        tokens = header_tokens(header)
        token_set = set(tokens)
        if token_set & PRIVACY_PERSONAL_TOKENS or any(
            all(word in tokens for word in phrase)
            for phrase in PRIVACY_PERSONAL_PHRASES
        ):
            personal += 1
        if token_set & PRIVACY_GEO_TOKENS:
            geo += 1
    return personal, geo


# ---------------------------------------------------------------------------
# Rule evaluation over one profiled frame
# ---------------------------------------------------------------------------


@dataclass
class ProfileInputs:
    """What the engine needs beyond the frame itself."""

    col_of: dict[str, str]  # canonical field -> original source header
    audit_header: str | None  # Late_delivery_risk header when present
    source_headers: list[str]  # all original headers (privacy heuristics)


def _trigger(rule_id: str, count: int, message: str) -> RuleResult:
    meta = RULES[rule_id]
    return RuleResult(
        rule_id=rule_id,
        severity=meta.severity,
        count=count,
        treatment=meta.treatment,
        blocked_stage=meta.blocked_stage,
        message=message,
        title=meta.title,
        fields=meta.fields,
        grain=meta.grain,
        population=meta.population,
    )


def evaluate_frame(
    frame: pd.DataFrame, inputs: ProfileInputs
) -> tuple[dict[str, int], dict[str, int], list[RuleResult]]:
    """Run every PROFILING-stage rule; return (missing, distinct, results).

    `missing`/`distinct` map canonical field -> count for the profile
    statistics. `results` contains one entry per evaluated rule, triggered
    or not; the caller keeps only triggered ones as issues.
    """
    col_of = inputs.col_of
    missing: dict[str, int] = {}
    distinct: dict[str, int] = {}
    trimmed: dict[str, pd.Series] = {}
    for canonical, column in col_of.items():
        values = stripped(frame, column)
        trimmed[canonical] = values
        miss = missing_mask(frame, column)
        missing[canonical] = int(miss.sum())
        distinct[canonical] = int(values[~miss].nunique())

    results: list[RuleResult] = []

    # -- DQ-KEY-001/002/003 -------------------------------------------------
    item_col = col_of["order_item_id"]
    item_present = ~missing_mask(frame, item_col)
    item_dupes = int((item_present & frame[item_col].duplicated(keep="first")).sum())
    if item_dupes:
        results.append(
            _trigger(
                "DQ-KEY-001",
                item_dupes,
                f"{item_dupes} order-item line(s) share a duplicate "
                "Order Item Id. Nothing was deduplicated; the "
                "canonical order-items build stays blocked until the "
                "input is fixed or replaced.",
            )
        )
    order_col = col_of["order_id"]
    present_orders = trimmed["order_id"][~missing_mask(frame, order_col)]
    key2 = int(len(present_orders) - present_orders.nunique())
    if key2:
        results.append(
            _trigger(
                "DQ-KEY-002",
                key2,
                f"{key2} order-item line(s) share an Order Id with "
                "another line. Repetition is legitimate at order-item "
                "grain and changes nothing.",
            )
        )
    both_present = ~missing_mask(frame, order_col) & ~missing_mask(
        frame, col_of["product_id"]
    )
    pairs = (
        frame[order_col].where(both_present).astype(str)
        + "\x00"
        + frame[col_of["product_id"]].where(both_present).astype(str)
    )
    key3 = int(both_present.sum() - pairs[both_present].nunique())
    if key3:
        results.append(
            _trigger(
                "DQ-KEY-003",
                key3,
                f"{key3} order-item line(s) repeat an Order Id + "
                "Product Id pair. The pair is not a key and changes "
                "nothing.",
            )
        )

    # -- DQ-DATE-001/002/003/004 --------------------------------------------
    order_missing = missing_mask(frame, col_of["order_timestamp"])
    ship_missing = missing_mask(frame, col_of["ship_timestamp"])
    order_parsed = parse_timestamps(trimmed["order_timestamp"])
    ship_parsed = parse_timestamps(trimmed["ship_timestamp"])
    date1 = int(((~order_missing) & order_parsed.isna()).sum())
    if date1:
        results.append(
            _trigger(
                "DQ-DATE-001",
                date1,
                f"{date1} line(s) have an order date that fails the "
                "explicit month-first parse. Affected rows stay out of "
                "date-binned KPIs; a file-wide failure blocks "
                "canonicalization.",
            )
        )
    date2 = int(((~ship_missing) & ship_parsed.isna()).sum())
    if date2:
        results.append(
            _trigger(
                "DQ-DATE-002",
                date2,
                f"{date2} line(s) have a shipping date that fails the "
                "explicit month-first parse. The shipping timestamp "
                "is validation evidence only.",
            )
        )
    both_dates = order_parsed.notna() & ship_parsed.notna()
    date3 = int((both_dates & (ship_parsed < order_parsed)).sum())
    if date3:
        results.append(
            _trigger(
                "DQ-DATE-003",
                date3,
                f"{date3} line(s) have a shipping timestamp earlier "
                "than the order timestamp. Shipment KPIs use the "
                "authoritative day fields regardless.",
            )
        )
    same_day = trimmed["shipping_mode"] == SAME_DAY_SOURCE_VALUE
    gap = (ship_parsed - order_parsed).abs()
    date4 = int((same_day & both_dates & (gap >= SAME_DAY_GAP)).sum())
    if date4:
        results.append(
            _trigger(
                "DQ-DATE-004",
                date4,
                f"{date4} Same Day line(s) show shipping and order "
                "timestamps at least 12 hours apart. Noted only; "
                "the authoritative actual-days field is unchanged.",
            )
        )

    # -- DQ-NUM-001/002/003 ---------------------------------------------------
    qty = parse_int_values(trimmed["quantity_units"])
    price_ok = parse_money_valid(trimmed["unit_price"])
    # Distinct rows with either condition.
    qty_neg = set(frame.index[(qty.notna()) & (qty < 0)].tolist())
    price_neg_rows: set[int] = set()
    unit_texts = trimmed["unit_price"].tolist()
    for pos, text in enumerate(unit_texts):
        if not bool(price_ok.iat[pos]):
            continue
        parsed_price = to_decimal_or_none(str(text).strip())
        if parsed_price is not None and parsed_price < 0:
            price_neg_rows.add(pos)
    num1 = len(qty_neg | price_neg_rows)
    if num1:
        results.append(
            _trigger(
                "DQ-NUM-001",
                num1,
                f"{num1} line(s) have a negative quantity or unit "
                "price. Flagged for investigation; nothing was "
                "clipped or removed.",
            )
        )
    gross_ok = parse_money_valid(trimmed["gross_sales"])
    disc_ok = parse_money_valid(trimmed["discount_amount"])
    net_ok = parse_money_valid(trimmed["net_sales"])
    recon = gross_ok & disc_ok & net_ok
    num2 = 0
    recon_idx = frame.index[recon].tolist()
    gross_s = trimmed["gross_sales"]
    disc_s = trimmed["discount_amount"]
    net_s = trimmed["net_sales"]
    for idx in recon_idx:
        g = to_decimal_or_none(str(gross_s.loc[idx]).strip())
        d = to_decimal_or_none(str(disc_s.loc[idx]).strip())
        n = to_decimal_or_none(str(net_s.loc[idx]).strip())
        if g is None or d is None or n is None:
            continue
        if abs((g - d) - n) > NET_TOLERANCE:
            num2 += 1
    if num2:
        results.append(
            _trigger(
                "DQ-NUM-002",
                num2,
                f"{num2} line(s) differ between gross minus discount "
                "and reported net beyond the $0.05 per-line tolerance. "
                "Reported net stays authoritative.",
            )
        )
    profit_ok = parse_money_valid(trimmed["profit_amount"])
    num3 = 0
    both_money = profit_ok & net_ok
    profit_s = trimmed["profit_amount"]
    for idx in frame.index[both_money].tolist():
        p = to_decimal_or_none(str(profit_s.loc[idx]).strip())
        n = to_decimal_or_none(str(net_s.loc[idx]).strip())
        if p is None or n is None or n == 0:
            continue
        if p / n < PROFIT_RATIO_THRESHOLD:
            num3 += 1
    if num3:
        results.append(
            _trigger(
                "DQ-NUM-003",
                num3,
                f"{num3} line(s) have a profit ratio below -1.0. "
                "Retained per policy; flagged for investigation only.",
            )
        )

    # -- DQ-CAT-001/002/003 + whitespace bucketing -----------------------------
    enum_sets = {
        "order_status": ORDER_STATUS_VALUES,
        "shipping_mode": SHIPPING_MODE_VALUES,
        "customer_segment": CUSTOMER_SEGMENT_VALUES,
    }
    rule_of_enum = {
        "order_status": "DQ-CAT-001",
        "shipping_mode": "DQ-CAT-002",
        "customer_segment": "DQ-CAT-003",
    }
    padded_known_rows: set[int] = set()
    for canonical, allowed in enum_sets.items():
        if canonical not in col_of:
            continue
        raw = frame[col_of[canonical]].astype(str)
        vals = trimmed[canonical]
        non_missing = vals != ""
        unknown = non_missing & ~enum_known_mask(vals, allowed)
        unknown_count = int(unknown.sum())
        if unknown_count:
            results.append(
                _trigger(
                    rule_of_enum[canonical],
                    unknown_count,
                    f"{unknown_count} line(s) carry an order status "
                    f"value outside the governed set."
                    if canonical == "order_status"
                    else (
                        f"{unknown_count} line(s) carry a shipping mode "
                        "value outside the governed set."
                        if canonical == "shipping_mode"
                        else (
                            f"{unknown_count} line(s) carry a customer "
                            "segment value outside the governed set."
                        )
                    ),
                )
            )
        padded = non_missing & (raw != vals) & enum_known_mask(vals, allowed)
        padded_known_rows.update(frame.index[padded].tolist())

    # -- DQ-CAT-005 -------------------------------------------------------------
    ws_rows: set[int] = set(padded_known_rows)
    for canonical in LABEL_FIELDS:
        if canonical not in col_of:
            continue
        raw = frame[col_of[canonical]].astype(str)
        vals = trimmed[canonical]
        padded_label = (vals != "") & (raw != vals)
        ws_rows.update(frame.index[padded_label].tolist())
    if ws_rows:
        results.append(
            _trigger(
                "DQ-CAT-005",
                len(ws_rows),
                f"{len(ws_rows)} line(s) have leading or trailing "
                "whitespace in governed label fields. Eligible for "
                "cleaning-time trimming; nothing was changed.",
            )
        )

    # -- DQ-GRAIN-001 ------------------------------------------------------------
    inv_fields = [f for f in INVARIANCE_FIELDS if f in col_of]
    order_present_mask = ~missing_mask(frame, order_col)
    by_field: dict[str, int] = {}
    conflicting: set[str] = set()
    order_ids = trimmed["order_id"]
    for field in inv_fields:
        vals = trimmed[field]
        usable = order_present_mask & (vals != "")
        if not bool(usable.any()):
            by_field[field] = 0
            continue
        grouped = vals[usable].groupby(order_ids[usable]).nunique()
        bad = set(grouped[grouped > 1].index.tolist())
        by_field[field] = len(bad)
        conflicting.update(bad)
    grain1 = len(conflicting)
    if grain1:
        results.append(
            _trigger(
                "DQ-GRAIN-001",
                grain1,
                f"{grain1} order(s) disagree across lines on at "
                "least one order-level attribute. The orders build "
                "stays blocked; no first row is picked.",
            )
        )

    # -- DQ-GRAIN-003 ------------------------------------------------------------
    prod_conflicting, _ = _dimension_key_conflicts(
        frame, inputs, "product_id", PRODUCT_INVARIANCE_FIELDS
    )
    grain3 = len(prod_conflicting)
    if grain3:
        results.append(
            _trigger(
                "DQ-GRAIN-003",
                grain3,
                f"{grain3} product(s) disagree across lines on at "
                "least one invariant product attribute. The products "
                "build stays blocked; no representative value is picked.",
            )
        )

    # -- DQ-GRAIN-004 ------------------------------------------------------------
    # customer_segment is optional: without it nothing is assessable, so the
    # rule is not evaluated (mirrors the rules_evaluated skip for DQ-CAT-003).
    if "customer_segment" in col_of:
        cust_conflicting, _ = _dimension_key_conflicts(
            frame, inputs, "customer_id", CUSTOMER_INVARIANCE_FIELDS
        )
        grain4 = len(cust_conflicting)
        if grain4:
            results.append(
                _trigger(
                    "DQ-GRAIN-004",
                    grain4,
                    f"{grain4} customer(s) disagree across lines on "
                    "customer_segment. The customers_sanitized build "
                    "stays blocked; no representative segment is picked.",
                )
            )

    # -- DQ-BUSINESS-002 ----------------------------------------------------------
    actual = parse_int_values(trimmed["actual_shipping_days"])
    scheduled = parse_int_values(trimmed["scheduled_shipping_days"])
    biz2_rows = set(frame.index[(actual.notna()) & (actual < 0)].tolist()) | set(
        frame.index[(scheduled.notna()) & (scheduled <= 0)].tolist()
    )
    if biz2_rows:
        results.append(
            _trigger(
                "DQ-BUSINESS-002",
                len(biz2_rows),
                f"{len(biz2_rows)} line(s) have implausible shipping "
                "days (actual below zero or scheduled at/below zero). "
                "Flagged only.",
            )
        )

    # -- DQ-BUSINESS-003 (audit-only comparison) ------------------------------------
    if inputs.audit_header is not None and inputs.audit_header in frame.columns:
        risk = stripped(frame, inputs.audit_header)
        risk_known = risk.isin({"0", "1"})
        not_cancelled = trimmed["delivery_status"] != CANCEL_SIGNAL_VALUE
        derivable = not_cancelled & risk_known & actual.notna() & scheduled.notna()
        expected_late = actual > scheduled
        risk_late = risk == "1"
        biz3 = int((derivable & (risk_late != expected_late)).sum())
        if biz3:
            results.append(
                _trigger(
                    "DQ-BUSINESS-003",
                    biz3,
                    f"{biz3} line(s) disagree between Late_delivery_risk "
                    "and the day-field outcome. The leakage field never "
                    "drives classification; this is audit evidence only.",
                )
            )

    # -- DQ-PRIVACY-001/002 ----------------------------------------------------------
    personal, geo = privacy_counts(inputs.source_headers)
    if personal:
        results.append(
            _trigger(
                "DQ-PRIVACY-001",
                personal,
                f"{personal} source column(s) look like direct personal "
                "fields. Excluded from canonical outputs by "
                "construction; values were never read.",
            )
        )
    if geo:
        results.append(
            _trigger(
                "DQ-PRIVACY-002",
                geo,
                f"{geo} source column(s) look like precise geo or "
                "locator fields. Excluded from canonical outputs by "
                "construction; values were never read.",
            )
        )

    # Orders checked is needed by the caller for the profile artifact.
    return missing, distinct, results


def _dimension_key_conflicts(
    frame: pd.DataFrame,
    inputs: ProfileInputs,
    key_field: str,
    dim_fields: tuple[str, ...],
) -> tuple[set[str], dict[str, int]]:
    """Keys whose invariant dims disagree (dimension-specific, ADR-036).

    Compares stripped governed text — the only authorized lexical treatment,
    shared with DQ-GRAIN-001 (case-sensitive, internal whitespace kept, no
    ID trimming, no fuzzy matching). Only distinct non-missing values
    conflict; unmapped dim fields are narrowed out like INVARIANCE_FIELDS.
    Returns conflicting key texts and per-field conflicting-key counts.
    """
    col_of = inputs.col_of
    assessable = [f for f in dim_fields if f in col_of]
    conflicting: set[str] = set()
    by_field: dict[str, int] = {}
    if key_field not in col_of or not assessable:
        return conflicting, by_field
    key_col = col_of[key_field]
    key_present_mask = ~missing_mask(frame, key_col)
    key_ids = stripped(frame, key_col)
    for field in assessable:
        vals = stripped(frame, col_of[field])
        usable = key_present_mask & (vals != "")
        if not bool(usable.any()):
            by_field[field] = 0
            continue
        grouped = vals[usable].groupby(key_ids[usable]).nunique()
        bad = set(grouped[grouped > 1].index.tolist())
        by_field[field] = len(bad)
        conflicting.update(bad)
    return conflicting, by_field


def dimension_invariance_by_key(
    frame: pd.DataFrame,
    inputs: ProfileInputs,
    key_field: str,
    dim_fields: tuple[str, ...],
) -> tuple[int, int, dict[str, int]]:
    """Recompute dimension-invariance detail for the profile artifact."""
    col_of = inputs.col_of
    if key_field not in col_of:
        return 0, 0, {}
    key_ids = stripped(frame, col_of[key_field])
    keys_checked = int(key_ids[~missing_mask(frame, col_of[key_field])].nunique())
    conflicting, by_field = _dimension_key_conflicts(
        frame, inputs, key_field, dim_fields
    )
    return keys_checked, len(conflicting), by_field


def invariance_by_field(
    frame: pd.DataFrame, inputs: ProfileInputs
) -> tuple[int, int, dict[str, int]]:
    """Recompute invariance detail for the profile artifact (counts only)."""
    col_of = inputs.col_of
    inv_fields = [f for f in INVARIANCE_FIELDS if f in col_of]
    order_col = col_of["order_id"]
    order_present_mask = ~missing_mask(frame, order_col)
    order_ids = stripped(frame, order_col)
    orders_checked = int(order_ids[order_present_mask].nunique())
    by_field: dict[str, int] = {}
    conflicting: set[str] = set()
    for field in inv_fields:
        vals = stripped(frame, col_of[field])
        usable = order_present_mask & (vals != "")
        if not bool(usable.any()):
            by_field[field] = 0
            continue
        grouped = vals[usable].groupby(order_ids[usable]).nunique()
        bad = set(grouped[grouped > 1].index.tolist())
        by_field[field] = len(bad)
        conflicting.update(bad)
    return orders_checked, len(conflicting), by_field
