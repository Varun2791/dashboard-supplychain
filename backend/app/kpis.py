"""Phase-9 KPI engine: the sole owner of every V1 KPI definition.

Consumes the governed canonical tables built by Phase 8 (`derived/
canonical_*.csv`) — never `raw.csv`, and never `cleaned.csv` for a metric
the canonical model covers (AGENTS.md input authority). Pure domain module:
no HTTP knowledge, no React knowledge; the lifecycle worker
(`ensure_kpis_analyzed` / `run_kpi_analysis`) follows the Phase-6/7/8
ensure/run/recover pattern, and the API layer only validates I/O.

Contract matrix (authority: `docs/kpi-contracts.md`, PLAN Phase 9,
ADR-002/007/008/009/010/011/012/013/014/015/017/030/031):

- Volume/entity counts (6): items, orders, shipment-eligible orders,
  customers, products, units. Counts come from canonical grain tables:
  items from `order_items`, orders from `orders`, customers from
  `customers_sanitized`, products from `products`.
- Commercial (11): gross/discount/net/profit sums originate at order-item
  grain; `net_sales` is authoritative (ADR-008 — gross minus discount is
  validation evidence, never a replacement); negatives retained (ADR-017);
  margin and discount rate are amount-weighted ratios of sums (ADR-014);
  no recognized-revenue label (ADR-009); no currency (ADR-010).
- Delivery (10): order grain only (ADR-002) — one order contributes at most
  once. Eligible = classifiable shipment outcomes (`LATE`, `EARLY`,
  `ON_SCHEDULE` — the exact-on-schedule value; no `EXACT` token exists,
  ADR-037 clarification of the missing-data rule); cancelled and
  null/unclassifiable rows are excluded from adherence denominators and
  counted in `missingDataCount` where governed. Cancelled rows carry
  `is_late = null` and never count as non-late (ADR-012).
  Classification input is the governed canonical derivation (day-field
  comparison); `Late_delivery_risk` and `Delivery Status` never classify
  (ADR-030); timestamp differences are validation evidence only (ADR-015).
  Early + exactly-on-schedule compose on-schedule (ADR-012 reference split).
- Cancellation/fraud (3): strict `CANCELED`, `SUSPECTED_FRAUD`, and the
  combined shipping-blocked rate stay separate (ADR-013).

Representation (api-contract section 6; the contract pins counts, money,
and unavailable semantics — the string forms below are the smallest
Decimal-safe reading where the contract leaves mechanics implicit):

- counts render as integers; money as 2-dp strings with no currency
  symbol; rates as 4-dp fraction strings (e.g. `"0.5731"`); day averages
  and per-order means as 2-dp strings. Underlying sums keep full Decimal
  precision; rounding applies only at this representation boundary
  (ROUND_HALF_UP, commercial expectation).
- Empty eligible population, zero denominator, or fully-missing required
  fields return `{value: null, status: "unavailable", reason}` with the
  pinned reason vocabulary — never `0` or `0%`. A row missing a required
  field is excluded from that KPI and counted in `missingDataCount`.
- No production constant from the DataCo regression controls appears here
  (ADR-020): every result is calculated from the active canonical tables.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from app import sessions as session_store
from app.config import settings
from app.ingestion_errors import (
    INTERNAL_STAGE_ERROR,
    STAGE_ANALYZING,
    IngestionError,
)
from app.profiling import sha256_file
from app.schema_validation import strip_session_payloads
from app.schemas import (
    STATE_ANALYZING,
    STATE_FAILED,
    STATE_READY,
    ApiErrorModel,
    CanonicalArtifact,
    KpiArtifact,
    KpiResult,
    SessionManifest,
)

logger = logging.getLogger(__name__)

UNKNOWN_FLAGGED = "UNKNOWN_FLAGGED"

# Pinned unavailable-reason vocabulary (api-contract section 6).
REASON_EMPTY_POPULATION = "empty-eligible-population"
REASON_ZERO_DENOMINATOR = "zero-denominator"
REASON_MISSING_FIELDS = "missing-required-fields"

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"

CANCELED_OUTCOME = "SHIPPING_CANCELED"
LATE_OUTCOME = "LATE"
EARLY_OUTCOME = "EARLY"
EXACT_OUTCOME = "ON_SCHEDULE"

STATUS_CANCELED = "CANCELED"
STATUS_FRAUD = "SUSPECTED_FRAUD"

# Governed classified shipment outcomes (canonical-schema §6 derivation:
# LATE = actual > scheduled; EARLY = actual < scheduled; ON_SCHEDULE =
# actual == scheduled, i.e. exactly on schedule — no EXACT token exists;
# SHIPPING_CANCELED = cancel signal; null = missing day fields).
# Adherence eligibility (ADR-037 clarification of the contract's global
# missing-data rule): an order is eligible only when its outcome is one of
# these three. SHIPPING_CANCELED is ineligible (ADR-012); null/empty/
# unclassifiable outcomes are excluded from adherence denominators.
CLASSIFIABLE_OUTCOMES: frozenset[str] = frozenset(
    {LATE_OUTCOME, EARLY_OUTCOME, EXACT_OUTCOME}
)


def is_classifiable_outcome(outcome: object) -> bool:
    """Whether one outcome value is a governed classified shipment outcome."""
    return outcome in CLASSIFIABLE_OUTCOMES


def eligible_shipments(orders: pd.DataFrame) -> pd.DataFrame:
    """Classifiable shipment-adherence frame: the single eligibility rule.

    One order contributes at most once (order-grain frame in, filtered
    frame out). Cancelled and null/unclassifiable rows are excluded here,
    so every shipment-rate denominator built from this frame shares the
    governed population and `late + early + exact = eligible` holds.
    """
    return orders[orders["shipment_outcome"].isin(CLASSIFIABLE_OUTCOMES)].reset_index(
        drop=True
    )


def missing_outcome_count(orders: pd.DataFrame) -> int:
    """Non-cancelled orders whose classification is unavailable (null/empty)."""
    outcome = orders["shipment_outcome"]
    unclassifiable = ~outcome.isin(CLASSIFIABLE_OUTCOMES)
    return int(((outcome != CANCELED_OUTCOME) & unclassifiable).sum())


def canceled_shipment_count(orders: pd.DataFrame) -> int:
    """Orders with an explicit shipping-cancelled outcome (all-orders scope)."""
    return int((orders["shipment_outcome"] == CANCELED_OUTCOME).sum())


# Every authorized V1 KPI ID with its approved display label, in
# `docs/kpi-contracts.md` order. The frontend renders `label` verbatim and
# performs no calculation; `test_kpi_contract_labels` pins this registry
# against the contract document (ADR-031).
KPI_LABELS: dict[str, str] = {
    "kpi.items.count": "Order-item lines",
    "kpi.orders.count": "Orders",
    "kpi.orders.shipment_eligible_count": "Shipment-eligible orders",
    "kpi.customers.count": "Customers",
    "kpi.products.count": "Products",
    "kpi.units.total": "Units",
    "kpi.value.gross": "Gross order value",
    "kpi.value.discount": "Discounts",
    "kpi.value.net": "Recorded net order value",
    "kpi.profit.recorded": "Recorded profit",
    "kpi.margin.profit": "Profit margin",
    "kpi.rate.discount": "Discount rate",
    "kpi.value.aov": "Average net per order",
    "kpi.units.per_order": "Units per order",
    "kpi.lines.per_order": "Lines per order",
    "kpi.orders.loss_making_rate": "Loss-making-order rate",
    "kpi.value.net_associated_with_late": (
        "Net order value associated with late shipments"
    ),
    "kpi.ship.late_rate": "Late-shipment rate",
    "kpi.ship.on_schedule_rate": "On-schedule shipment rate",
    "kpi.ship.early_rate": "Early-shipment rate",
    "kpi.ship.exact_rate": "Exactly on-schedule rate",
    "kpi.ship.late_count": "Late / early / exactly on-schedule orders",
    "kpi.ship.early_count": "Late / early / exactly on-schedule orders",
    "kpi.ship.exact_count": "Late / early / exactly on-schedule orders",
    "kpi.ship.avg_actual_days": "Average actual shipping days",
    "kpi.ship.avg_scheduled_days": "Average scheduled shipping days",
    "kpi.ship.variance_days": "Average schedule variance (days)",
    "kpi.orders.strict_cancel_rate": "Strict cancellation rate",
    "kpi.orders.fraud_rate": "Suspected-fraud rate",
    "kpi.orders.blocked_rate": "Shipping-blocked rate",
}

VOLUME_KPI_IDS: tuple[str, ...] = (
    "kpi.items.count",
    "kpi.orders.count",
    "kpi.orders.shipment_eligible_count",
    "kpi.customers.count",
    "kpi.products.count",
    "kpi.units.total",
)

COMMERCIAL_KPI_IDS: tuple[str, ...] = (
    "kpi.value.gross",
    "kpi.value.discount",
    "kpi.value.net",
    "kpi.profit.recorded",
    "kpi.margin.profit",
    "kpi.rate.discount",
    "kpi.value.aov",
    "kpi.units.per_order",
    "kpi.lines.per_order",
    "kpi.orders.loss_making_rate",
    "kpi.value.net_associated_with_late",
)

DELIVERY_KPI_IDS: tuple[str, ...] = (
    "kpi.ship.late_rate",
    "kpi.ship.on_schedule_rate",
    "kpi.ship.early_rate",
    "kpi.ship.exact_rate",
    "kpi.ship.late_count",
    "kpi.ship.early_count",
    "kpi.ship.exact_count",
    "kpi.ship.avg_actual_days",
    "kpi.ship.avg_scheduled_days",
    "kpi.ship.variance_days",
    "kpi.orders.strict_cancel_rate",
    "kpi.orders.fraud_rate",
    "kpi.orders.blocked_rate",
)

# `by=` dimensions (kpi-contracts) mapped to the native canonical column.
# Grouping re-slices numerator/denominator under identical formulas on the
# endpoint's row frame (delivery: eligible orders; commercial: items).
BY_COLUMN: dict[str, str] = {
    "shipping_mode": "shipping_mode",
    "order_status": "order_status",
    "shipment_outcome": "shipment_outcome",
    "customer_segment": "customer_segment",
    "destination_market": "destination_market",
    "destination_region": "destination_region",
    "destination_country": "destination_country",
    "department_name": "department_name",
    "category_name": "category_name",
    "product_name": "product_name",
    "order_month": "order_month",
}


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KpiFilters:
    """Validated serving filters (api-contract section 5).

    Filters narrow the eligible population; they never change a formula,
    grain, or label. The API layer rejects unknown enum values (422) before
    these are built, so every set field holds a canonical token or date.
    """

    date_from: date | None = None
    date_to: date | None = None
    market: str | None = None
    region: str | None = None
    category: str | None = None
    department: str | None = None
    shipping_mode: str | None = None
    order_status: str | None = None
    shipment_outcome: str | None = None
    customer_segment: str | None = None

    def is_active(self) -> bool:
        """Whether any filter narrows the population."""
        return any(
            value is not None
            for value in (
                self.date_from,
                self.date_to,
                self.market,
                self.region,
                self.category,
                self.department,
                self.shipping_mode,
                self.order_status,
                self.shipment_outcome,
                self.customer_segment,
            )
        )

    def describe(self) -> str:
        """Stable filter summary echoed in populations and meta.filters."""
        parts: list[str] = []
        if self.date_from is not None:
            parts.append(f"from={self.date_from.isoformat()}")
        if self.date_to is not None:
            parts.append(f"to={self.date_to.isoformat()}")
        for name in (
            "market",
            "region",
            "category",
            "department",
            "shipping_mode",
            "order_status",
            "shipment_outcome",
            "customer_segment",
        ):
            value = getattr(self, name)
            if value is not None:
                parts.append(f"{name}={value}")
        return ", ".join(parts)

    def as_meta(self) -> dict[str, str]:
        """Echo map for the response envelope (`meta.filters`)."""
        out: dict[str, str] = {}
        described = self.describe()
        if described:
            for part in described.split(", "):
                key, _, value = part.partition("=")
                out[key] = value
        return out


NO_FILTERS = KpiFilters()


# ---------------------------------------------------------------------------
# Canonical-table loading (typed parsing of the Phase-8 string CSVs)
# ---------------------------------------------------------------------------


def _present(text: str) -> str | None:
    """Canonical CSVs render nulls as empty strings; only they are missing."""
    return None if text == "" else text


def _parse_money(text: str) -> Decimal | None:
    cell = _present(text)
    if cell is None:
        return None
    try:
        return Decimal(cell)
    except Exception:
        return None


def _parse_int(text: str) -> int | None:
    cell = _present(text)
    if cell is None:
        return None
    try:
        return int(cell)
    except ValueError:
        return None


def _parse_bool(text: str) -> bool | None:
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _parse_timestamp(text: str) -> datetime | None:
    cell = _present(text)
    if cell is None:
        return None
    try:
        return datetime.strptime(cell, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def _parse_date(text: str) -> date | None:
    cell = _present(text)
    if cell is None:
        return None
    try:
        return date.fromisoformat(cell)
    except ValueError:
        return None


@dataclass
class KpiTables:
    """Parsed canonical inputs for one KPI computation."""

    items: pd.DataFrame
    orders: pd.DataFrame
    product_ids: list[str]
    customer_ids: list[str]


def _obj(values: list[object]) -> pd.Series:
    """Object-dtype series for parsed canonical columns (None-safe)."""
    return pd.Series(values, dtype=object)


def _read_table(paths: session_store.SessionPaths, filename: str) -> pd.DataFrame:
    full = session_store.canonical_table_path(paths, filename)
    return pd.read_csv(full, dtype="string[pyarrow]", keep_default_na=False)


def load_canonical_tables(paths: session_store.SessionPaths) -> KpiTables:
    """Load and strictly parse the governed canonical tables.

    Raises OSError when a table file is missing/unreadable (the lifecycle
    maps that to a terminal ANALYZING failure — a claimed build whose
    tables are gone is not analyzable).
    """
    items = _read_table(paths, session_store.CANONICAL_ITEMS_FILENAME)
    orders = _read_table(paths, session_store.CANONICAL_ORDERS_FILENAME)
    products = _read_table(paths, session_store.CANONICAL_PRODUCTS_FILENAME)
    customers = _read_table(paths, session_store.CANONICAL_CUSTOMERS_FILENAME)

    for column in ("gross_sales", "discount_amount", "net_sales", "profit_amount"):
        items = items.assign(
            **{f"_{column}": _obj([_parse_money(v) for v in items[column].tolist()])}
        )
    items = items.assign(
        _quantity_units=_obj([_parse_int(v) for v in items["quantity_units"].tolist()]),
        _is_late=_obj([_parse_bool(v) for v in items["is_late"].tolist()]),
        _order_timestamp=_obj(
            [_parse_timestamp(v) for v in items["order_timestamp"].tolist()]
        ),
        _order_date=_obj([_parse_date(v) for v in items["order_date"].tolist()]),
    )

    for column in ("gross_value", "discount_total", "net_value", "profit_total"):
        orders = orders.assign(
            **{f"_{column}": _obj([_parse_money(v) for v in orders[column].tolist()])}
        )
    orders = orders.assign(
        _total_units=_obj([_parse_int(v) for v in orders["total_units"].tolist()]),
        _line_count=_obj([_parse_int(v) for v in orders["line_count"].tolist()]),
        _is_late=_obj([_parse_bool(v) for v in orders["is_late"].tolist()]),
        _actual_shipping_days=_obj(
            [_parse_int(v) for v in orders["actual_shipping_days"].tolist()]
        ),
        _scheduled_shipping_days=_obj(
            [_parse_int(v) for v in orders["scheduled_shipping_days"].tolist()]
        ),
        _order_timestamp=_obj(
            [_parse_timestamp(v) for v in orders["order_timestamp"].tolist()]
        ),
    )
    # The orders table carries no variance/order-date columns
    # (canonical-schema section 2): both reuse the governed section 6
    # formulas on canonical fields — variance is actual minus scheduled,
    # order date is the date part of the order timestamp.
    actual_days = orders["_actual_shipping_days"].tolist()
    scheduled_days = orders["_scheduled_shipping_days"].tolist()
    stamps = orders["_order_timestamp"].tolist()
    orders = orders.assign(
        _schedule_variance_days=_obj(
            [
                a - s if a is not None and s is not None else None
                for a, s in zip(actual_days, scheduled_days, strict=True)
            ]
        ),
        _order_date=_obj([s.date() if s is not None else None for s in stamps]),
    )

    product_ids = [str(v) for v in products["product_id"].tolist() if v != ""]
    customer_ids = [str(v) for v in customers["customer_id"].tolist() if v != ""]
    return KpiTables(
        items=items, orders=orders, product_ids=product_ids, customer_ids=customer_ids
    )


# ---------------------------------------------------------------------------
# Filtering and grouping (population narrowing only)
# ---------------------------------------------------------------------------


def _date_in_range(
    stamp: datetime | None, date_from: date | None, date_to: date | None
) -> bool:
    if date_from is None and date_to is None:
        return True
    # A row without a governed order timestamp cannot be evaluated against
    # a date range: DQ-DATE-001 keeps it out of date-filtered populations.
    if stamp is None:
        return False
    day = stamp.date()
    if date_from is not None and day < date_from:
        return False
    return not (date_to is not None and day > date_to)


def apply_filters(
    tables: KpiTables, filters: KpiFilters
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Narrow items/orders to the filtered population (formulas unchanged)."""
    items = tables.items
    orders = tables.orders
    dims: tuple[tuple[str, str | None], ...] = (
        ("destination_market", filters.market),
        ("destination_region", filters.region),
        ("category_name", filters.category),
        ("department_name", filters.department),
        ("shipping_mode", filters.shipping_mode),
        ("order_status", filters.order_status),
        ("shipment_outcome", filters.shipment_outcome),
        ("customer_segment", filters.customer_segment),
    )
    if filters.is_active():
        keep_items = [
            _date_in_range(stamp, filters.date_from, filters.date_to)
            for stamp in items["_order_timestamp"].tolist()
        ]
        keep_orders = [
            _date_in_range(stamp, filters.date_from, filters.date_to)
            for stamp in orders["_order_timestamp"].tolist()
        ]
        for column, wanted in dims:
            if wanted is None:
                continue
            column_items = items[column].tolist()
            column_orders = orders[column].tolist()
            keep_items = [
                keep and cell == wanted
                for keep, cell in zip(keep_items, column_items, strict=True)
            ]
            keep_orders = [
                keep and cell == wanted
                for keep, cell in zip(keep_orders, column_orders, strict=True)
            ]
        items = items[keep_items].reset_index(drop=True)
        orders = orders[keep_orders].reset_index(drop=True)
    return items, orders


def _group_key(frame: pd.DataFrame, by: str, index: int, row: pd.Series) -> str | None:
    if by == "order_month":
        day = frame["_order_date"].tolist()[index]
        if day is None:
            return None
        return f"{day.year:04d}-{day.month:02d}"
    cell = str(row[BY_COLUMN[by]])
    if cell == "" or cell == UNKNOWN_FLAGGED:
        # ADR-030: unknown enum values are counted and reported, but
        # excluded from split KPIs.
        return None
    return cell


def group_keys(frame: pd.DataFrame, by: str) -> dict[str, list[int]]:
    """Deterministic groupkey -> row positions (unknown/null excluded)."""
    groups: dict[str, list[int]] = {}
    rows = list(frame.iterrows())
    for position, (_, row) in enumerate(rows):
        key = _group_key(frame, by, position, row)
        if key is None:
            continue
        groups.setdefault(key, []).append(position)
    return {key: groups[key] for key in sorted(groups)}


# ---------------------------------------------------------------------------
# Representation
# ---------------------------------------------------------------------------


def _fmt_money(total: Decimal) -> str:
    """Money display: exactly 2 dp, no currency symbol (ADR-010)."""
    return str(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _fmt_rate(fraction: Decimal) -> str:
    """Rate display: 4-dp fraction string (1-dp percent is a UI concern)."""
    return str(fraction.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _fmt_mean(mean: Decimal) -> str:
    """Day-average / per-order-mean display: exactly 2 dp."""
    return str(mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _result(
    kpi_id: str,
    *,
    value: int | str | None,
    status: str,
    numerator: int | str | None,
    denominator: int | str | None,
    population: str,
    exclusions: str,
    reason: str | None = None,
    missing: int = 0,
) -> KpiResult:
    return KpiResult(
        id=kpi_id,
        label=KPI_LABELS[kpi_id],
        value=value,
        status=status,
        numerator=numerator,
        denominator=denominator,
        population=population,
        exclusions=exclusions,
        reason=reason,
        missingDataCount=missing,
    )


def _unavailable(
    kpi_id: str,
    *,
    numerator: int | str | None,
    denominator: int | str | None,
    population: str,
    exclusions: str,
    reason: str,
    missing: int = 0,
) -> KpiResult:
    return _result(
        kpi_id,
        value=None,
        status=STATUS_UNAVAILABLE,
        numerator=numerator,
        denominator=denominator,
        population=population,
        exclusions=exclusions,
        reason=reason,
        missing=missing,
    )


def _scope_suffix(filters: KpiFilters, group: str | None) -> str:
    suffix = ""
    if filters.is_active():
        suffix += f"; filters: {filters.describe()}"
    if group is not None:
        suffix += f"; group: {group}"
    return suffix


def _decimal_sum(values: list[Decimal | None]) -> Decimal:
    total = Decimal("0")
    for value in values:
        if value is not None:
            total += value
    return total


# ---------------------------------------------------------------------------
# Volume / entity counts (canonical grain tables)
# ---------------------------------------------------------------------------


def compute_volume(
    tables: KpiTables,
    items: pd.DataFrame,
    orders: pd.DataFrame,
    filters: KpiFilters,
    group: str | None = None,
) -> list[KpiResult]:
    """Volume KPIs. Counts come from canonical grain tables, never raw rows.

    Inside a `by=` group the entity counts re-slice to the group frame;
    the headline uses the dimension tables as grain authority.
    """
    suffix = _scope_suffix(filters, group)
    order_ids = [v for v in orders["order_id"].tolist() if v != ""]
    n_orders = len(order_ids)
    eligible = eligible_shipments(orders)
    n_eligible = int(len(eligible))
    missing_outcome = missing_outcome_count(orders)
    n_items = int(len(items))
    units = sum(v for v in items["_quantity_units"].tolist() if v is not None)
    missing_units = (
        sum(1 for v in items["_quantity_units"].tolist() if v is None) if n_items else 0
    )
    if group is None and not filters.is_active():
        n_customers = len({v for v in tables.customer_ids})
        n_products = len({v for v in tables.product_ids})
    else:
        # Filtered/grouped entity counts represent the distinct entities
        # participating in the filtered governed population (frames are
        # already narrowed; union of canonical IDs, no joins, no
        # amount duplication).
        n_customers = len(
            {v for v in items["customer_id"].tolist() if v != ""}
            | {v for v in orders["customer_id"].tolist() if v != ""}
        )
        n_products = len({v for v in items["product_id"].tolist() if v != ""})
    out = [
        _result(
            "kpi.items.count",
            value=n_items,
            status=STATUS_OK,
            numerator=n_items,
            denominator=None,
            population=f"{n_items} canonical order-item lines{suffix}",
            exclusions="none",
        ),
        _result(
            "kpi.orders.count",
            value=n_orders,
            status=STATUS_OK,
            numerator=n_orders,
            denominator=None,
            population=f"{n_orders} canonical orders{suffix}",
            exclusions="none",
        )
        if n_orders
        else _unavailable(
            "kpi.orders.count",
            numerator=0,
            denominator=None,
            population=f"0 canonical orders{suffix}",
            exclusions="none",
            reason=REASON_EMPTY_POPULATION,
        ),
        _result(
            "kpi.orders.shipment_eligible_count",
            value=n_eligible,
            status=STATUS_OK,
            numerator=n_eligible,
            denominator=None,
            population=f"{n_eligible} eligible shipment orders{suffix}",
            exclusions="shipping-cancelled orders excluded",
            missing=missing_outcome,
        )
        if n_eligible
        else _unavailable(
            "kpi.orders.shipment_eligible_count",
            numerator=0,
            denominator=None,
            population=f"0 eligible shipment orders{suffix}",
            exclusions="shipping-cancelled orders excluded",
            reason=REASON_EMPTY_POPULATION,
            missing=missing_outcome,
        ),
        _result(
            "kpi.customers.count",
            value=n_customers,
            status=STATUS_OK,
            numerator=n_customers,
            denominator=None,
            population=f"{n_customers} sanitized customers{suffix}",
            exclusions="none",
        ),
        _result(
            "kpi.products.count",
            value=n_products,
            status=STATUS_OK,
            numerator=n_products,
            denominator=None,
            population=f"{n_products} products{suffix}",
            exclusions="none",
        ),
        _result(
            "kpi.units.total",
            value=units,
            status=STATUS_OK,
            numerator=units,
            denominator=None,
            population=f"{n_items} order-item lines{suffix}",
            exclusions="none",
            missing=missing_units,
        ),
    ]
    return out


# ---------------------------------------------------------------------------
# Commercial value (order-item grain sums; authoritative recorded net)
# ---------------------------------------------------------------------------


def compute_commercial(
    items: pd.DataFrame,
    orders: pd.DataFrame,
    filters: KpiFilters,
    group: str | None = None,
) -> list[KpiResult]:
    """Commercial KPIs from item-grain sums; order-grain means via orders."""
    suffix = _scope_suffix(filters, group)
    n_items = int(len(items))
    order_ids = [v for v in orders["order_id"].tolist() if v != ""]
    n_orders = len(order_ids)
    gross = items["_gross_sales"].tolist()
    discount = items["_discount_amount"].tolist()
    net = items["_net_sales"].tolist()
    profit = items["_profit_amount"].tolist()
    gross_total = _decimal_sum(gross)
    discount_total = _decimal_sum(discount)
    net_total = _decimal_sum(net)
    profit_total = _decimal_sum(profit)
    missing_gross = sum(1 for v in gross if v is None)
    missing_discount = sum(1 for v in discount if v is None)
    missing_net = sum(1 for v in net if v is None)
    missing_profit = sum(1 for v in profit if v is None)
    both_margin = [
        (p, n)
        for p, n in zip(profit, net, strict=True)
        if p is not None and n is not None
    ]
    missing_margin = n_items - len(both_margin)
    margin_profit = _decimal_sum([p for p, _ in both_margin])
    margin_net = _decimal_sum([n for _, n in both_margin])
    both_discount = [
        (d, g)
        for d, g in zip(discount, gross, strict=True)
        if d is not None and g is not None
    ]
    missing_disc_rate = n_items - len(both_discount)
    rate_discount = _decimal_sum([d for d, _ in both_discount])
    rate_gross = _decimal_sum([g for _, g in both_discount])

    order_net = orders["_net_value"].tolist()
    order_profit = orders["_profit_total"].tolist()
    order_units = orders["_total_units"].tolist()
    order_lines = orders["_line_count"].tolist()
    scope_pop = f"{n_items} order-item lines, all-status scope{suffix}"
    order_pop = f"{n_orders} orders{suffix}"

    results = [
        _result(
            "kpi.value.gross",
            value=_fmt_money(gross_total),
            status=STATUS_OK,
            numerator=_fmt_money(gross_total),
            denominator=None,
            population=scope_pop,
            exclusions="none",
            missing=missing_gross,
        ),
        _result(
            "kpi.value.discount",
            value=_fmt_money(discount_total),
            status=STATUS_OK,
            numerator=_fmt_money(discount_total),
            denominator=None,
            population=scope_pop,
            exclusions="none",
            missing=missing_discount,
        ),
        _result(
            "kpi.value.net",
            value=_fmt_money(net_total),
            status=STATUS_OK,
            numerator=_fmt_money(net_total),
            denominator=None,
            population=scope_pop,
            exclusions="none",
            missing=missing_net,
        ),
        _result(
            "kpi.profit.recorded",
            value=_fmt_money(profit_total),
            status=STATUS_OK,
            numerator=_fmt_money(profit_total),
            denominator=None,
            population=f"{scope_pop}; negatives retained",
            exclusions="none",
            missing=missing_profit,
        ),
    ]
    if margin_net == 0:
        reason = (
            REASON_ZERO_DENOMINATOR
            if both_margin
            else REASON_MISSING_FIELDS
            if n_items
            else REASON_EMPTY_POPULATION
        )
        results.append(
            _unavailable(
                "kpi.margin.profit",
                numerator=_fmt_money(margin_profit),
                denominator=_fmt_money(margin_net),
                population=f"{len(both_margin)} lines with recorded profit "
                f"and net{suffix}",
                exclusions="lines missing profit or net excluded",
                reason=reason,
                missing=missing_margin,
            )
        )
    else:
        results.append(
            _result(
                "kpi.margin.profit",
                value=_fmt_rate(margin_profit / margin_net),
                status=STATUS_OK,
                numerator=_fmt_money(margin_profit),
                denominator=_fmt_money(margin_net),
                population=f"{len(both_margin)} lines with recorded profit "
                f"and net{suffix}",
                exclusions="lines missing profit or net excluded; "
                "ratio of sums, never mean of row margins",
                missing=missing_margin,
            )
        )
    if rate_gross == 0:
        reason = (
            REASON_ZERO_DENOMINATOR
            if both_discount
            else REASON_MISSING_FIELDS
            if n_items
            else REASON_EMPTY_POPULATION
        )
        results.append(
            _unavailable(
                "kpi.rate.discount",
                numerator=_fmt_money(rate_discount),
                denominator=_fmt_money(rate_gross),
                population=f"{len(both_discount)} lines with recorded "
                f"discount and gross{suffix}",
                exclusions="lines missing discount or gross excluded",
                reason=reason,
                missing=missing_disc_rate,
            )
        )
    else:
        results.append(
            _result(
                "kpi.rate.discount",
                value=_fmt_rate(rate_discount / rate_gross),
                status=STATUS_OK,
                numerator=_fmt_money(rate_discount),
                denominator=_fmt_money(rate_gross),
                population=f"{len(both_discount)} lines with recorded "
                f"discount and gross{suffix}",
                exclusions="lines missing discount or gross excluded; amount-weighted",
                missing=missing_disc_rate,
            )
        )
    if n_orders == 0:
        for kpi_id in (
            "kpi.value.aov",
            "kpi.units.per_order",
            "kpi.lines.per_order",
            "kpi.orders.loss_making_rate",
        ):
            results.append(
                _unavailable(
                    kpi_id,
                    numerator=None,
                    denominator=0,
                    population=f"0 orders{suffix}",
                    exclusions="none",
                    reason=REASON_EMPTY_POPULATION,
                )
            )
    else:
        order_net_total = _decimal_sum(order_net)
        missing_order_net = sum(1 for v in order_net if v is None)
        order_units_total = sum(v for v in order_units if v is not None)
        order_lines_total = sum(v for v in order_lines if v is not None)
        loss_orders = sum(1 for v in order_profit if v is not None and v < 0)
        missing_order_profit = sum(1 for v in order_profit if v is None)
        results.extend(
            [
                _result(
                    "kpi.value.aov",
                    value=_fmt_money(order_net_total / n_orders),
                    status=STATUS_OK,
                    numerator=_fmt_money(order_net_total),
                    denominator=n_orders,
                    population=order_pop,
                    exclusions="none",
                    missing=missing_order_net,
                ),
                _result(
                    "kpi.units.per_order",
                    value=_fmt_mean(Decimal(order_units_total) / n_orders),
                    status=STATUS_OK,
                    numerator=order_units_total,
                    denominator=n_orders,
                    population=order_pop,
                    exclusions="none",
                ),
                _result(
                    "kpi.lines.per_order",
                    value=_fmt_mean(Decimal(order_lines_total) / n_orders),
                    status=STATUS_OK,
                    numerator=order_lines_total,
                    denominator=n_orders,
                    population=order_pop,
                    exclusions="none",
                ),
                _result(
                    "kpi.orders.loss_making_rate",
                    value=_fmt_rate(Decimal(loss_orders) / n_orders),
                    status=STATUS_OK,
                    numerator=loss_orders,
                    denominator=n_orders,
                    population=order_pop,
                    exclusions="none; negatives retained, never clamped",
                    missing=missing_order_profit,
                ),
            ]
        )
    results.append(_late_associated_net(orders, filters, group, n_orders))
    return results


def _late_associated_net(
    orders: pd.DataFrame,
    filters: KpiFilters,
    group: str | None,
    n_orders: int,
) -> KpiResult:
    """Net order value associated with late shipments (association only).

    Value is the late-associated recorded net; the share of in-scope net
    derives from numerator/denominator. Never "lost sales" (ADR-009/019).
    """
    suffix = _scope_suffix(filters, group)
    eligible = eligible_shipments(orders)
    late_nets = [
        v
        for v, late in zip(
            eligible["_net_value"].tolist(), eligible["_is_late"].tolist(), strict=True
        )
        if late is True and v is not None
    ]
    eligible_nets = [v for v in eligible["_net_value"].tolist() if v is not None]
    missing = sum(1 for v in eligible["_net_value"].tolist() if v is None)
    missing += missing_outcome_count(orders)
    n_eligible = int(len(eligible))
    population = f"{n_eligible} eligible shipment orders{suffix}"
    exclusions = (
        "shipping-cancelled orders excluded; association only, never lost sales"
    )
    if n_eligible == 0:
        return _unavailable(
            "kpi.value.net_associated_with_late",
            numerator=_fmt_money(Decimal("0")),
            denominator=_fmt_money(Decimal("0")),
            population=population,
            exclusions=exclusions,
            reason=REASON_EMPTY_POPULATION,
            missing=missing,
        )
    late_total = _decimal_sum(late_nets)
    eligible_total = _decimal_sum(eligible_nets)
    return _result(
        "kpi.value.net_associated_with_late",
        value=_fmt_money(late_total),
        status=STATUS_OK,
        numerator=_fmt_money(late_total),
        denominator=_fmt_money(eligible_total),
        population=population,
        exclusions=exclusions,
        missing=missing,
    )


# ---------------------------------------------------------------------------
# Delivery (order grain; eligible population only)
# ---------------------------------------------------------------------------


def compute_delivery(
    orders: pd.DataFrame,
    filters: KpiFilters,
    group: str | None = None,
) -> list[KpiResult]:
    """Shipment KPIs at order grain: one order contributes at most once."""
    suffix = _scope_suffix(filters, group)
    n_orders = int(len(orders))
    eligible = eligible_shipments(orders)
    n_eligible = int(len(eligible))
    n_cancelled = canceled_shipment_count(orders)
    exclusions = (
        f"{n_cancelled} shipping-cancelled orders excluded"
        f"{'; ' + filters.describe() if filters.is_active() else ''}"
        f"{'; group: ' + group if group is not None else ''}"
    )
    population = f"{n_eligible} eligible shipment orders{suffix}"
    late_flags = eligible["_is_late"].tolist()
    missing_flags = sum(1 for v in late_flags if v is None)
    # Rows excluded from the adherence population for unavailable
    # classification stay represented in missing-data accounting.
    missing_unclassifiable = missing_outcome_count(orders)
    missing_late = missing_unclassifiable + missing_flags
    # Cancelled rows carry is_late = null by derivation; a null flag inside
    # the eligible population is unclassifiable, never non-late.
    classifiable = [v for v in late_flags if v is not None]
    n_late = sum(1 for v in classifiable if v is True)
    n_onsched = sum(1 for v in classifiable if v is False)
    outcomes = eligible["shipment_outcome"].tolist()
    n_early = sum(1 for v in outcomes if v == EARLY_OUTCOME)
    n_exact = sum(1 for v in outcomes if v == EXACT_OUTCOME)

    results: list[KpiResult] = []
    if n_eligible == 0:
        for kpi_id in (
            "kpi.ship.late_rate",
            "kpi.ship.on_schedule_rate",
            "kpi.ship.early_rate",
            "kpi.ship.exact_rate",
        ):
            results.append(
                _unavailable(
                    kpi_id,
                    numerator=0,
                    denominator=0,
                    population=population,
                    exclusions=exclusions,
                    reason=REASON_EMPTY_POPULATION,
                    missing=missing_late,
                )
            )
    else:
        for kpi_id, count in (
            ("kpi.ship.late_rate", n_late),
            ("kpi.ship.on_schedule_rate", n_onsched),
            ("kpi.ship.early_rate", n_early),
            ("kpi.ship.exact_rate", n_exact),
        ):
            results.append(
                _result(
                    kpi_id,
                    value=_fmt_rate(Decimal(count) / n_eligible),
                    status=STATUS_OK,
                    numerator=count,
                    denominator=n_eligible,
                    population=population,
                    exclusions=exclusions,
                    missing=missing_late,
                )
            )
    results.extend(
        [
            _result(
                "kpi.ship.late_count",
                value=n_late,
                status=STATUS_OK,
                numerator=n_late,
                denominator=n_eligible,
                population=population,
                exclusions=exclusions,
                missing=missing_late,
            ),
            _result(
                "kpi.ship.early_count",
                value=n_early,
                status=STATUS_OK,
                numerator=n_early,
                denominator=n_eligible,
                population=population,
                exclusions=exclusions,
                missing=missing_late,
            ),
            _result(
                "kpi.ship.exact_count",
                value=n_exact,
                status=STATUS_OK,
                numerator=n_exact,
                denominator=n_eligible,
                population=population,
                exclusions=exclusions,
                missing=missing_late,
            ),
        ]
    )
    actuals = [v for v in eligible["_actual_shipping_days"].tolist() if v is not None]
    scheduled = [
        v for v in eligible["_scheduled_shipping_days"].tolist() if v is not None
    ]
    variances = [
        v for v in eligible["_schedule_variance_days"].tolist() if v is not None
    ]
    missing_actual = n_eligible - len(actuals) + missing_unclassifiable
    missing_scheduled = n_eligible - len(scheduled) + missing_unclassifiable
    missing_variance = n_eligible - len(variances) + missing_unclassifiable
    if actuals:
        results.append(
            _result(
                "kpi.ship.avg_actual_days",
                value=_fmt_mean(Decimal(sum(actuals)) / len(actuals)),
                status=STATUS_OK,
                numerator=sum(actuals),
                denominator=len(actuals),
                population=f"{len(actuals)} eligible orders with recorded "
                f"actual days{suffix}",
                exclusions=exclusions,
                missing=missing_actual,
            )
        )
    else:
        results.append(
            _unavailable(
                "kpi.ship.avg_actual_days",
                numerator=0,
                denominator=0,
                population=population,
                exclusions=exclusions,
                reason=REASON_EMPTY_POPULATION
                if n_eligible == 0
                else REASON_MISSING_FIELDS,
                missing=missing_actual,
            )
        )
    if scheduled:
        results.append(
            _result(
                "kpi.ship.avg_scheduled_days",
                value=_fmt_mean(Decimal(sum(scheduled)) / len(scheduled)),
                status=STATUS_OK,
                numerator=sum(scheduled),
                denominator=len(scheduled),
                population=f"{len(scheduled)} eligible orders with recorded "
                f"scheduled days{suffix}",
                exclusions=exclusions,
                missing=missing_scheduled,
            )
        )
    else:
        results.append(
            _unavailable(
                "kpi.ship.avg_scheduled_days",
                numerator=0,
                denominator=0,
                population=population,
                exclusions=exclusions,
                reason=REASON_EMPTY_POPULATION
                if n_eligible == 0
                else REASON_MISSING_FIELDS,
                missing=missing_scheduled,
            )
        )
    if variances:
        results.append(
            _result(
                "kpi.ship.variance_days",
                value=_fmt_mean(Decimal(sum(variances)) / len(variances)),
                status=STATUS_OK,
                numerator=sum(variances),
                denominator=len(variances),
                population=f"{len(variances)} eligible orders with recorded "
                f"actual and scheduled days{suffix}; negative = ahead",
                exclusions=exclusions,
                missing=missing_variance,
            )
        )
    else:
        results.append(
            _unavailable(
                "kpi.ship.variance_days",
                numerator=0,
                denominator=0,
                population=population,
                exclusions=exclusions,
                reason=REASON_EMPTY_POPULATION
                if n_eligible == 0
                else REASON_MISSING_FIELDS,
                missing=missing_variance,
            )
        )
    statuses = orders["order_status"].tolist()
    n_strict = sum(1 for v in statuses if v == STATUS_CANCELED)
    n_fraud = sum(1 for v in statuses if v == STATUS_FRAUD)
    missing_status = sum(1 for v in statuses if v == "")
    status_pop = f"{n_orders} orders{suffix}"
    status_excl = (
        "strict cancellation and suspected fraud counted separately"
        f"{'; ' + filters.describe() if filters.is_active() else ''}"
        f"{'; group: ' + group if group is not None else ''}"
    )
    if n_orders == 0:
        for kpi_id in (
            "kpi.orders.strict_cancel_rate",
            "kpi.orders.fraud_rate",
            "kpi.orders.blocked_rate",
        ):
            results.append(
                _unavailable(
                    kpi_id,
                    numerator=0,
                    denominator=0,
                    population=status_pop,
                    exclusions=status_excl,
                    reason=REASON_EMPTY_POPULATION,
                    missing=missing_status,
                )
            )
    else:
        for kpi_id, count in (
            ("kpi.orders.strict_cancel_rate", n_strict),
            ("kpi.orders.fraud_rate", n_fraud),
            ("kpi.orders.blocked_rate", n_cancelled),
        ):
            results.append(
                _result(
                    kpi_id,
                    value=_fmt_rate(Decimal(count) / n_orders),
                    status=STATUS_OK,
                    numerator=count,
                    denominator=n_orders,
                    population=status_pop,
                    exclusions=status_excl,
                    missing=missing_status,
                )
            )
    return results


# ---------------------------------------------------------------------------
# Headline set, groups, totals
# ---------------------------------------------------------------------------


def compute_headline(
    tables: KpiTables, filters: KpiFilters = NO_FILTERS
) -> list[KpiResult]:
    """All 30 headline KPIs in contract order for one population."""
    items, orders = apply_filters(tables, filters)
    return (
        compute_volume(tables, items, orders, filters)
        + compute_commercial(items, orders, filters)
        + compute_delivery(orders, filters)
    )


def compute_groups(
    tables: KpiTables, by: str, filters: KpiFilters, delivery: bool
) -> list[tuple[str, list[KpiResult]]]:
    """Re-sliced KPI sets per `by=` group under identical formulas."""
    items, orders = apply_filters(tables, filters)
    if delivery:
        # Shipment breakdowns group the all-orders frame: `compute_delivery`
        # derives adherence metrics from the classifiable grouped subset
        # while strict/fraud/blocked rates keep their governed all-orders
        # denominators re-sliced to the same group key (identical formulas).
        # Null/unclassifiable outcomes form no group (ADR-030 reporting).
        orders = orders.reset_index(drop=True)
    frame = orders if delivery else items
    grouped: list[tuple[str, list[KpiResult]]] = []
    for key, positions in group_keys(frame, by).items():
        label = f"{by}={key}"
        if delivery:
            order_slice = orders.iloc[positions].reset_index(drop=True)
            grouped.append((key, compute_delivery(order_slice, filters, label)))
        else:
            item_slice = items.iloc[positions].reset_index(drop=True)
            slice_order_ids = {v for v in item_slice["order_id"].tolist() if v != ""}
            order_slice = orders[orders["order_id"].isin(slice_order_ids)].reset_index(
                drop=True
            )
            grouped.append(
                (key, compute_commercial(item_slice, order_slice, filters, label))
            )
    return grouped


def headline_totals(
    tables: KpiTables, filters: KpiFilters = NO_FILTERS
) -> dict[str, int | str]:
    """Overview `totals`: population anchors the filtered views reconcile to."""
    items, orders = apply_filters(tables, filters)
    eligible = eligible_shipments(orders)
    gross = _decimal_sum(items["_gross_sales"].tolist())
    discount = _decimal_sum(items["_discount_amount"].tolist())
    net = _decimal_sum(items["_net_sales"].tolist())
    profit = _decimal_sum(items["_profit_amount"].tolist())
    units = sum(v for v in items["_quantity_units"].tolist() if v is not None)
    return {
        "items": int(len(items)),
        "orders": int(len(orders)),
        "eligibleOrders": int(len(eligible)),
        "grossValue": _fmt_money(gross),
        "discountTotal": _fmt_money(discount),
        "netValue": _fmt_money(net),
        "profitTotal": _fmt_money(profit),
        "units": units,
    }


# ---------------------------------------------------------------------------
# Lifecycle: ANALYZING -> READY (Phase-9 worker, Phase-6/7/8 pattern)
# ---------------------------------------------------------------------------


def _fail_kpi_analysis(
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
            "stage": STAGE_ANALYZING,
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
    logger.info("kpi_analysis_failed code=%s", error.code)
    return transitioned


def _artifact_matches_session(
    stored: KpiArtifact,
    manifest: SessionManifest,
    paths: session_store.SessionPaths,
    canonical: CanonicalArtifact,
) -> bool:
    """Provenance gate before adopting an on-disk KPI report.

    Stored results are never trusted on their own: the canonical report
    must be the recorded input (canonicalizedAt identity) with every
    listed table SHA recomputed, so a stale or foreign report cannot be
    adopted. App/schema versions pin the code.
    """
    if not (
        stored.sessionId == manifest.sessionId
        and stored.sourceSha256 == manifest.sha256
        and stored.appVersion == settings.app_version
        and stored.schemaVersion == settings.schema_version
        and stored.inputCanonicalizedAt == canonical.canonicalizedAt
        and stored.sourceRows == canonical.sourceRows
        and session_store.read_schema_report(paths) is not None
        and os.path.isfile(paths.raw)
    ):
        return False
    try:
        names = {table.name: table.sha256 for table in canonical.tables}
        for name, sha in stored.inputTableShas.items():
            if names.get(name) != sha:
                return False
            if sha256_file(os.path.join(paths.root, name)) != sha:
                return False
    except OSError:
        return False
    return True


def _adopt_report(
    paths: session_store.SessionPaths,
    manifest: SessionManifest,
    stored: KpiArtifact,
    now_iso: str,
) -> SessionManifest:
    """Adopt a verified report: READY with the KPI pointer set."""
    transitioned = manifest.model_copy(
        update={
            "state": STATE_READY,
            "stage": STATE_READY,
            "progress": session_store.make_ready_progress(),
            "kpiArtifact": (
                f"{session_store.DERIVED_DIRNAME}/{session_store.KPI_ARTIFACT_FILENAME}"
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
    logger.info("kpi_analysis_adopted")
    return transitioned


def ensure_kpis_analyzed(
    paths: session_store.SessionPaths, manifest: SessionManifest, now_iso: str
) -> SessionManifest:
    """Run Phase-9 KPI analysis once if still pending; else return stored.

    Only complete canonical builds are analyzable: anything parked at
    CANONICALIZING behind a governed quality gate never reaches this
    worker, so blockers are never bypassed (endpoints answer 409
    NOT_READY there). Never mutates raw; verified by SHA before and after.
    """
    if manifest.state != STATE_ANALYZING or manifest.kpiArtifact is not None:
        return manifest
    canonical = session_store.read_canonical_report(paths)
    if canonical is None or canonical.status != "complete":
        return manifest
    stored = session_store.read_kpi_report(paths)
    if stored is not None and _artifact_matches_session(
        stored, manifest, paths, canonical
    ):
        return _adopt_report(paths, manifest, stored, now_iso)
    if sha256_file(paths.raw) != manifest.sha256:
        logger.warning("kpi_analysis_self_check_failed")
        return _fail_kpi_analysis(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_ANALYZING,
                "The stored upload failed its integrity check. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    try:
        tables = load_canonical_tables(paths)
    except OSError:
        logger.warning("kpi_analysis_table_unreadable")
        return _fail_kpi_analysis(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_ANALYZING,
                "The canonical tables could not be read. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    except Exception:  # never leak values; terminal per ADR-028
        logger.warning("kpi_analysis_unexpected_error")
        return _fail_kpi_analysis(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_ANALYZING,
                "The upload could not be analyzed. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    try:
        kpis = compute_headline(tables)
    except Exception:  # never leak values; terminal per ADR-028
        logger.warning("kpi_analysis_unexpected_error")
        return _fail_kpi_analysis(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_ANALYZING,
                "The upload could not be analyzed. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    # Raw immutability proof: SHA unchanged across the analysis pass.
    if sha256_file(paths.raw) != manifest.sha256:
        logger.warning("kpi_analysis_self_check_failed")
        return _fail_kpi_analysis(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_ANALYZING,
                "The stored upload failed its integrity check. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    artifact = KpiArtifact(
        sessionId=manifest.sessionId,
        appVersion=settings.app_version,
        schemaVersion=settings.schema_version,
        sourceSha256=manifest.sha256,
        sourceRows=canonical.sourceRows,
        inputCanonicalizedAt=canonical.canonicalizedAt,
        inputTableShas={table.name: table.sha256 for table in canonical.tables},
        status="complete",
        kpis=kpis,
        computedAt=now_iso,
    )
    try:
        session_store.write_kpi_report(paths, artifact)
    except OSError:
        return manifest
    transitioned = manifest.model_copy(
        update={
            "state": STATE_READY,
            "stage": STATE_READY,
            "progress": session_store.make_ready_progress(),
            "kpiArtifact": (
                f"{session_store.DERIVED_DIRNAME}/{session_store.KPI_ARTIFACT_FILENAME}"
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
    logger.info("kpis_analyzed kpis=%d", len(kpis))
    return transitioned


__all__ = [
    "BY_COLUMN",
    "CLASSIFIABLE_OUTCOMES",
    "COMMERCIAL_KPI_IDS",
    "DELIVERY_KPI_IDS",
    "KPI_LABELS",
    "NO_FILTERS",
    "REASON_EMPTY_POPULATION",
    "REASON_MISSING_FIELDS",
    "REASON_ZERO_DENOMINATOR",
    "STATUS_OK",
    "STATUS_UNAVAILABLE",
    "VOLUME_KPI_IDS",
    "KpiFilters",
    "KpiTables",
    "apply_filters",
    "canceled_shipment_count",
    "compute_commercial",
    "compute_delivery",
    "compute_groups",
    "compute_headline",
    "compute_volume",
    "eligible_shipments",
    "ensure_kpis_analyzed",
    "group_keys",
    "headline_totals",
    "is_classifiable_outcome",
    "load_canonical_tables",
    "missing_outcome_count",
    "recover_analyzing_sessions",
    "run_kpi_analysis",
]


_KPI_ANALYSIS_IN_PROGRESS: set[str] = set()


def run_kpi_analysis(session_id: str) -> SessionManifest | None:
    """Execute one KPI analysis pass for a session (pipeline/recovery body).

    Safe against reset races: a deleted session (no manifest) is a no-op
    and is never resurrected. Returns the resulting manifest, or None when
    there was nothing to do.
    """
    if not session_store.is_valid_session_id(session_id):
        return None
    if session_id in _KPI_ANALYSIS_IN_PROGRESS:
        return None
    _KPI_ANALYSIS_IN_PROGRESS.add(session_id)
    try:
        paths = session_store.session_paths(settings.session_root, session_id)
        manifest = session_store.read_manifest(paths)
        if manifest is None:
            return None
        return ensure_kpis_analyzed(paths, manifest, session_store.utcnow_naive_iso())
    finally:
        _KPI_ANALYSIS_IN_PROGRESS.discard(session_id)


def recover_analyzing_sessions(session_root: str) -> int:
    """Startup recovery: analyze leftover ANALYZING sessions.

    Covers the crash window between canonicalization success and KPI
    completion, including the torn-write window where the KPI report was
    persisted but the manifest pointer/state update never landed: the
    orphaned report is validated through the normal adoption path (adopted
    when provenance matches, recomputed when stale/corrupt — never trusted
    by existence alone). Expired trees are left to the sweep; parked
    CANONICALIZING sessions are never analyzed.
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
            or manifest.state != STATE_ANALYZING
            or manifest.kpiArtifact is not None
        ):
            continue
        if session_store.is_expired(manifest, datetime.now()):
            continue
        run_kpi_analysis(entry)
        recovered += 1
    if recovered:
        logger.info("kpi_analysis_recovery_analyzed=%d", recovered)
    return recovered
