"""Phase-15A diagnostic query surfaces (domain service, no HTTP knowledge).

Backing logic for the two ADR-038 reads over the governed canonical
tables:

- filter facet domains (`GET .../filter-options` backing data);
- sanitized one-row-per-order drilldown reads (`GET .../orders` backing
  data).

Authority: ADR-038/039, api-contract sections 3/5/6, canonical-schema
sections 2/7. Filters reuse `KpiFilters`/`apply_filters` from `app.kpis`
(identical predicate machinery — filter-mechanics parity); nothing here
changes a formula, grain, or label. Order rows carry the stored
canonical order aggregates verbatim and are never reaggregated from
items; shipment truth is never rederived (`Late_delivery_risk` and
`Delivery Status` are never read).

Validation failures raise `ValueError`; the API layer maps them to the
contract `422 INVALID_PAGINATION` with session context.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.kpis import UNKNOWN_FLAGGED, KpiFilters, KpiTables, apply_filters

# Governed pagination bounds (ADR-038, api-contract section 3).
ORDERS_LIMIT_DEFAULT = 50
ORDERS_LIMIT_MAX = 200

# Opaque cursor payload version (bumped only if the encoding changes).
_CURSOR_VERSION = 1
_CURSOR_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"


def _fmt_money(value: Decimal) -> str:
    """Money display: exactly 2 dp, no currency symbol (api-contract §6).

    Same rule as `kpis._fmt_money`; commercial expectation ROUND_HALF_UP.
    """
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _display(text: object) -> str | None:
    """Canonical display value: empty cells are absent, never invented."""
    if text is None:
        return None
    rendered = str(text)
    return None if rendered == "" else rendered


def _domain_values(values: list[object]) -> list[str]:
    """Sorted distinct non-empty display values minus the unknown sentinel.

    Codepoint sorting (deterministic); no case-folding, no frequency
    ranking, no counts. `UNKNOWN_FLAGGED` is governed reportable state,
    never a selectable option (ADR-038).
    """
    options = {
        str(value)
        for value in values
        if value is not None and str(value) != "" and str(value) != UNKNOWN_FLAGGED
    }
    return sorted(options)


@dataclass(frozen=True)
class FilterOptions:
    """Session-wide facet domains plus the canonical order-date extent."""

    min_order_date: date | None
    max_order_date: date | None
    markets: list[str]
    regions: list[str]
    categories: list[str]


def build_filter_options(tables: KpiTables) -> FilterOptions:
    """Collect the UNFILTERED session domain (non-cascading by construction).

    Markets/regions come from the canonical orders table
    (order-destination geography, invariant); categories come from the
    canonical ITEMS table so multi-merch values stay discoverable
    (governed facet/drilldown asymmetry — ADR-038). No filter parameter
    is accepted, so active analytics filters can never narrow the
    returned options.
    """
    days = [day for day in tables.orders["_order_date"].tolist() if day is not None]
    return FilterOptions(
        min_order_date=min(days) if days else None,
        max_order_date=max(days) if days else None,
        markets=_domain_values(tables.orders["destination_market"].tolist()),
        regions=_domain_values(tables.orders["destination_region"].tolist()),
        categories=_domain_values(tables.items["category_name"].tolist()),
    )


@dataclass(frozen=True)
class OrderRecord:
    """One sanitized canonical order row (typed domain values)."""

    order_id: str
    order_timestamp: datetime | None
    order_status: str | None
    shipping_mode: str | None
    customer_segment: str | None
    destination_country: str | None
    destination_region: str | None
    destination_market: str | None
    scheduled_shipping_days: int | None
    actual_shipping_days: int | None
    shipment_outcome: str | None
    is_late: bool | None
    line_count: int
    total_units: int
    gross_value: str
    discount_total: str
    net_value: str
    profit_total: str


def _stored_money(value: object) -> str:
    """Render one stored order aggregate (always Decimal by construction).

    The `0.00` fallback is unreachable behind the canonical build (order
    aggregates are summed exactly once) and the artifact integrity gate;
    it keeps a tampered-but-readable artifact serving instead of crashing.
    """
    if isinstance(value, Decimal):
        return _fmt_money(value)
    return "0.00"


def select_orders(tables: KpiTables, filters: KpiFilters) -> list[OrderRecord]:
    """Filtered canonical orders in governed display order.

    Same predicate machinery as the KPI endpoints (`apply_filters`):
    direct equality on canonical order columns, so multi-merch orders
    (null order-level merch dims) are excluded by merch filters —
    order-frame semantics, never item-membership. Ordering is
    `order_timestamp` DESC, `order_id` ASC, null timestamps last
    (defensive; unreachable behind the NN schema plus invariance gate).
    """
    _, orders = apply_filters(tables, filters)
    order_ids = [str(v) for v in orders["order_id"].tolist()]
    stamps: list[datetime | None] = orders["_order_timestamp"].tolist()
    status = orders["order_status"].tolist()
    mode = orders["shipping_mode"].tolist()
    segment = orders["customer_segment"].tolist()
    country = orders["destination_country"].tolist()
    region = orders["destination_region"].tolist()
    market = orders["destination_market"].tolist()
    outcome = orders["shipment_outcome"].tolist()
    gross: list[object] = orders["_gross_value"].tolist()
    discount: list[object] = orders["_discount_total"].tolist()
    net: list[object] = orders["_net_value"].tolist()
    profit: list[object] = orders["_profit_total"].tolist()
    units: list[object] = orders["_total_units"].tolist()
    lines: list[object] = orders["_line_count"].tolist()
    actual: list[object] = orders["_actual_shipping_days"].tolist()
    scheduled: list[object] = orders["_scheduled_shipping_days"].tolist()
    late: list[object] = orders["_is_late"].tolist()
    records: list[OrderRecord] = []
    for index, (order_id, stamp) in enumerate(zip(order_ids, stamps, strict=True)):
        scheduled_raw = scheduled[index]
        actual_raw = actual[index]
        late_raw = late[index]
        lines_raw = lines[index]
        units_raw = units[index]
        records.append(
            OrderRecord(
                order_id=order_id,
                order_timestamp=stamp,
                order_status=_display(status[index]),
                shipping_mode=_display(mode[index]),
                customer_segment=_display(segment[index]),
                destination_country=_display(country[index]),
                destination_region=_display(region[index]),
                destination_market=_display(market[index]),
                scheduled_shipping_days=scheduled_raw
                if isinstance(scheduled_raw, int)
                else None,
                actual_shipping_days=actual_raw
                if isinstance(actual_raw, int)
                else None,
                shipment_outcome=_display(outcome[index]),
                is_late=late_raw if isinstance(late_raw, bool) else None,
                line_count=lines_raw if isinstance(lines_raw, int) else 0,
                total_units=units_raw if isinstance(units_raw, int) else 0,
                gross_value=_stored_money(gross[index]),
                discount_total=_stored_money(discount[index]),
                net_value=_stored_money(net[index]),
                profit_total=_stored_money(profit[index]),
            )
        )
    dated = sorted(
        (record for record in records if record.order_timestamp is not None),
        key=lambda record: record.order_id,
    )
    dated.sort(key=lambda record: record.order_timestamp or datetime.min, reverse=True)
    undated = sorted(
        (record for record in records if record.order_timestamp is None),
        key=lambda record: record.order_id,
    )
    return dated + undated


def parse_limit(raw: int | None) -> int:
    """Govern the `limit` parameter (missing → default; out-of-range → error)."""
    if raw is None:
        return ORDERS_LIMIT_DEFAULT
    if (
        not isinstance(raw, bool)
        and isinstance(raw, int)
        and 1 <= raw <= ORDERS_LIMIT_MAX
    ):
        return raw
    raise ValueError(
        f"Unknown orders limit '{raw}'. Use an integer 1..{ORDERS_LIMIT_MAX}."
    )


@dataclass(frozen=True)
class CursorPosition:
    """Decoded opaque cursor: ordering state plus filter-context binding."""

    order_timestamp: datetime | None
    order_id: str
    fingerprint: str


def _fingerprint(filters: KpiFilters) -> str:
    """Canonical machine identity for the normalized filter context.

    Deterministic JSON over explicit named fields — never the human
    display string (`describe()` stays human/display metadata only):
    structurally unambiguous even for punctuation-bearing open-domain
    values (commas, equals, colons, quotes, backslashes, Unicode).
    Dates are ISO strings; absent is explicit null. No hashing: the
    cursor is already opaque, and unambiguous identity (not
    authentication) is the requirement.
    """
    payload: dict[str, object] = {
        "from": filters.date_from.isoformat()
        if filters.date_from is not None
        else None,
        "to": filters.date_to.isoformat() if filters.date_to is not None else None,
        "market": filters.market,
        "region": filters.region,
        "category": filters.category,
        "department": filters.department,
        "shipping_mode": filters.shipping_mode,
        "order_status": filters.order_status,
        "shipment_outcome": filters.shipment_outcome,
        "customer_segment": filters.customer_segment,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def encode_cursor(record: OrderRecord, filters: KpiFilters) -> str:
    """Opaque keyset cursor for the given row under the active filters."""
    payload: dict[str, Any] = {
        "v": _CURSOR_VERSION,
        "ts": record.order_timestamp.strftime(_CURSOR_TIMESTAMP_FORMAT)
        if record.order_timestamp is not None
        else None,
        "oid": record.order_id,
        "f": _fingerprint(filters),
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _bad_cursor(raw: str) -> ValueError:
    """One governed malformed-cursor failure (mapped to INVALID_PAGINATION)."""
    return ValueError(f"Unknown orders cursor {raw!r}. Request a fresh page.")


def decode_cursor(raw: str) -> CursorPosition:
    """Decode an opaque cursor (malformed input → `ValueError`)."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode())
    except Exception:
        raise _bad_cursor(raw) from None
    if not isinstance(payload, dict):
        raise _bad_cursor(raw)
    version = payload.get("v")
    if type(version) is not int or version != _CURSOR_VERSION:
        raise _bad_cursor(raw)
    order_id = payload.get("oid")
    if not isinstance(order_id, str) or order_id == "":
        raise _bad_cursor(raw)
    raw_ts = payload.get("ts")
    stamp: datetime | None = None
    if raw_ts is not None:
        if not isinstance(raw_ts, str):
            raise _bad_cursor(raw)
        try:
            stamp = datetime.strptime(raw_ts, _CURSOR_TIMESTAMP_FORMAT)
        except ValueError:
            raise _bad_cursor(raw) from None
    fingerprint = payload.get("f")
    if not isinstance(fingerprint, str):
        raise _bad_cursor(raw)
    return CursorPosition(
        order_timestamp=stamp, order_id=order_id, fingerprint=fingerprint
    )


def _is_after(record: OrderRecord, position: CursorPosition) -> bool:
    """Whether a row sorts strictly after the cursor in governed order."""
    cursor_ts = position.order_timestamp
    if cursor_ts is None:
        # Cursor sits in the null-timestamp tail: only later order_ids follow.
        return record.order_timestamp is None and record.order_id > position.order_id
    if record.order_timestamp is None:
        # The entire null tail sorts after every dated row.
        return True
    if record.order_timestamp < cursor_ts:
        return True
    return record.order_timestamp == cursor_ts and record.order_id > position.order_id


@dataclass(frozen=True)
class OrderPage:
    """One paginated slice plus traversal state."""

    rows: list[OrderRecord]
    next_cursor: str | None
    total: int


def paginate(
    records: list[OrderRecord],
    limit: int,
    position: CursorPosition | None,
    filters: KpiFilters,
) -> OrderPage:
    """Slice the ordered records after the cursor (context-bound).

    A cursor created under different filters is rejected (`ValueError`)
    — silent cross-context traversal could skip or repeat rows.
    `total` is the pre-pagination match count, never the page length.
    """
    if position is not None and position.fingerprint != _fingerprint(filters):
        raise ValueError(
            "The orders cursor was created under different filters. "
            "Request a fresh page under the active filters."
        )
    start = 0
    if position is not None:
        for index, record in enumerate(records):
            if _is_after(record, position):
                start = index
                break
        else:
            return OrderPage(rows=[], next_cursor=None, total=len(records))
    page = records[start : start + limit]
    remaining = len(records) - (start + len(page))
    next_cursor = encode_cursor(page[-1], filters) if page and remaining > 0 else None
    return OrderPage(rows=page, next_cursor=next_cursor, total=len(records))
