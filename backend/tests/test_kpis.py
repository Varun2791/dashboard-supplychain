"""Phase-9 KPI formula and adversarial tests (synthetic data only).

Pure-unit tests build minimal canonical-grain frames (no session needed)
and assert every formula: numerators, denominators, grain, exclusions,
empty populations, null behavior, negatives, zero denominators, and
governed value representation. A session-driven test verifies the small
`canonical_small.csv` fixture against hand-computed expectations, and a
contract test pins every KPI ID to its approved display label.

No DataCo rows and no reference controls appear here as production
inputs; hand-computed numbers below derive from the synthetic fixture.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import kpis
from app.config import settings
from app.main import app

CANON_BYTES = (Path(__file__).parent / "fixtures" / "canonical_small.csv").read_bytes()

ITEM_STRING_COLUMNS = (
    "order_id",
    "customer_id",
    "product_id",
    "gross_sales",
    "discount_amount",
    "net_sales",
    "profit_amount",
    "quantity_units",
    "is_late",
    "order_timestamp",
    "order_date",
    "shipment_outcome",
    "shipping_mode",
    "order_status",
    "customer_segment",
    "destination_market",
    "destination_region",
    "destination_country",
    "department_name",
    "category_name",
    "product_name",
)

ORDER_STRING_COLUMNS = (
    "order_id",
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

PARSED_ITEM_COLUMNS = (
    "_gross_sales",
    "_discount_amount",
    "_net_sales",
    "_profit_amount",
    "_quantity_units",
    "_is_late",
    "_order_timestamp",
    "_order_date",
)

PARSED_ORDER_COLUMNS = (
    "_gross_value",
    "_discount_total",
    "_net_value",
    "_profit_total",
    "_total_units",
    "_line_count",
    "_is_late",
    "_actual_shipping_days",
    "_scheduled_shipping_days",
    "_schedule_variance_days",
    "_order_timestamp",
    "_order_date",
)


def _render(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def make_items(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Minimal order-item frame: typed values in, canonical strings stored."""
    string_rows = [
        {column: _render(row.get(column)) for column in ITEM_STRING_COLUMNS}
        for row in rows
    ]
    frame = pd.DataFrame(string_rows, columns=list(ITEM_STRING_COLUMNS)).astype(str)
    parsed = {
        "_gross_sales": [kpis._parse_money(v) for v in frame["gross_sales"].tolist()],
        "_discount_amount": [
            kpis._parse_money(v) for v in frame["discount_amount"].tolist()
        ],
        "_net_sales": [kpis._parse_money(v) for v in frame["net_sales"].tolist()],
        "_profit_amount": [
            kpis._parse_money(v) for v in frame["profit_amount"].tolist()
        ],
        "_quantity_units": [
            kpis._parse_int(v) for v in frame["quantity_units"].tolist()
        ],
        "_is_late": [kpis._parse_bool(v) for v in frame["is_late"].tolist()],
        "_order_timestamp": [
            kpis._parse_timestamp(v) for v in frame["order_timestamp"].tolist()
        ],
        "_order_date": [kpis._parse_date(v) for v in frame["order_date"].tolist()],
    }
    for column in PARSED_ITEM_COLUMNS:
        frame = frame.assign(**{column: kpis._obj(parsed[column])})
    return frame


def make_orders(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Minimal order frame: typed values in, canonical strings stored."""
    string_rows = [
        {column: _render(row.get(column)) for column in ORDER_STRING_COLUMNS}
        for row in rows
    ]
    frame = pd.DataFrame(string_rows, columns=list(ORDER_STRING_COLUMNS)).astype(str)
    parsed = {
        "_gross_value": [kpis._parse_money(v) for v in frame["gross_value"].tolist()],
        "_discount_total": [
            kpis._parse_money(v) for v in frame["discount_total"].tolist()
        ],
        "_net_value": [kpis._parse_money(v) for v in frame["net_value"].tolist()],
        "_profit_total": [kpis._parse_money(v) for v in frame["profit_total"].tolist()],
        "_total_units": [kpis._parse_int(v) for v in frame["total_units"].tolist()],
        "_line_count": [kpis._parse_int(v) for v in frame["line_count"].tolist()],
        "_is_late": [kpis._parse_bool(v) for v in frame["is_late"].tolist()],
        "_actual_shipping_days": [
            kpis._parse_int(v) for v in frame["actual_shipping_days"].tolist()
        ],
        "_scheduled_shipping_days": [
            kpis._parse_int(v) for v in frame["scheduled_shipping_days"].tolist()
        ],
        "_order_timestamp": [
            kpis._parse_timestamp(v) for v in frame["order_timestamp"].tolist()
        ],
    }
    for column in PARSED_ORDER_COLUMNS:
        if column == "_schedule_variance_days":
            actuals = parsed["_actual_shipping_days"]
            scheduled = parsed["_scheduled_shipping_days"]
            frame = frame.assign(
                **{
                    column: kpis._obj(
                        [
                            a - s if a is not None and s is not None else None
                            for a, s in zip(actuals, scheduled, strict=True)
                        ]
                    )
                }
            )
        elif column == "_order_date":
            frame = frame.assign(
                **{
                    column: kpis._obj(
                        [
                            s.date() if s is not None else None
                            for s in parsed["_order_timestamp"]
                        ]
                    )
                }
            )
        else:
            frame = frame.assign(**{column: kpis._obj(parsed[column])})
    return frame


def make_tables(
    items: list[dict[str, object]],
    orders: list[dict[str, object]],
    products: list[str] | None = None,
    customers: list[str] | None = None,
) -> kpis.KpiTables:
    """KpiTables from typed rows (products/customers default from frames)."""
    item_frame = make_items(items)
    order_frame = make_orders(orders)
    if products is None:
        products = sorted({str(v) for v in item_frame["product_id"] if v != ""})
    if customers is None:
        customers = sorted(
            {str(v) for v in item_frame["customer_id"] if v != ""}
            | {str(v) for v in order_frame["customer_id"] if v != ""}
        )
    return kpis.KpiTables(
        items=item_frame,
        orders=order_frame,
        product_ids=products,
        customer_ids=customers,
    )


def by_id(results: list[kpis.KpiResult]) -> dict[str, kpis.KpiResult]:
    return {result.id: result for result in results}


BASE_ITEM = {
    "customer_id": "C1",
    "product_id": "P1",
    "gross_sales": Decimal("30.00"),
    "discount_amount": Decimal("2.00"),
    "net_sales": Decimal("28.00"),
    "profit_amount": Decimal("6.00"),
    "quantity_units": 2,
    "order_timestamp": datetime(2021, 3, 15, 10, 0, 0),
    "order_date": date(2021, 3, 15),
    "shipping_mode": "STANDARD_CLASS",
    "order_status": "COMPLETE",
    "customer_segment": "CONSUMER",
    "destination_market": "M",
    "destination_region": "R",
    "destination_country": "C",
    "department_name": "D",
    "category_name": "G",
    "product_name": "W",
}


def base_order(
    order_id: str,
    outcome: str,
    late: bool | None,
    actual: int | None,
    scheduled: int | None,
    status: str = "COMPLETE",
    net: Decimal = Decimal("28.00"),
    profit: Decimal = Decimal("6.00"),
    units: int = 2,
    lines: int = 1,
    **overrides: object,
) -> dict[str, object]:
    """One order row with consistent money/line aggregates."""
    row: dict[str, object] = {
        "order_id": order_id,
        "customer_id": "C1",
        "order_timestamp": datetime(2021, 3, 15, 10, 0, 0),
        "order_status": status,
        "shipping_mode": "STANDARD_CLASS",
        "customer_segment": "CONSUMER",
        "destination_country": "C",
        "destination_region": "R",
        "destination_market": "M",
        "scheduled_shipping_days": scheduled,
        "actual_shipping_days": actual,
        "shipment_outcome": outcome,
        "is_late": late,
        "line_count": lines,
        "total_units": units,
        "gross_value": Decimal("30.00"),
        "discount_total": Decimal("2.00"),
        "net_value": net,
        "profit_total": profit,
    }
    row.update(overrides)
    return row


def base_item(order_id: str, **overrides: object) -> dict[str, object]:
    row = dict(BASE_ITEM)
    row["order_id"] = order_id
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Contract labels
# ---------------------------------------------------------------------------


def test_kpi_ids_and_labels_match_contract() -> None:
    catalogue = (
        Path(__file__).parent.parent.parent / "docs" / "kpi-contracts.md"
    ).read_text()
    assert len(kpis.KPI_LABELS) == 30
    assert set(kpis.VOLUME_KPI_IDS) | set(kpis.COMMERCIAL_KPI_IDS) | set(
        kpis.DELIVERY_KPI_IDS
    ) == set(kpis.KPI_LABELS)
    for kpi_id, label in kpis.KPI_LABELS.items():
        if kpi_id in ("kpi.ship.early_count", "kpi.ship.exact_count"):
            # The contract abbreviates these two IDs inside the shared
            # count row (`late_count` / `early_count` / `exact_count`).
            short = kpi_id.removeprefix("kpi.ship.")
            assert f"`{short}`" in catalogue, kpi_id
        else:
            assert f"`{kpi_id}`" in catalogue, kpi_id
        assert label in catalogue, label
    # Binding terminology: recorded value, never recognized revenue.
    assert "Recorded net order value" in kpis.KPI_LABELS.values()
    assert not any("revenue" in label.lower() for label in kpis.KPI_LABELS.values())
    assert "On-schedule shipment rate" in kpis.KPI_LABELS.values()
    assert not any("OTIF" in label for label in kpis.KPI_LABELS.values())


# ---------------------------------------------------------------------------
# Volume / entity counts
# ---------------------------------------------------------------------------


def test_volume_counts_use_canonical_grain() -> None:
    tables = make_tables(
        [base_item("O1"), base_item("O1"), base_item("O2")],
        [
            base_order("O1", "LATE", True, 5, 3),
            base_order("O2", "ON_SCHEDULE", False, 2, 2),
        ],
        products=["P1"],
        customers=["C1", "C2"],
    )
    results = by_id(
        kpis.compute_volume(tables, tables.items, tables.orders, kpis.NO_FILTERS)
    )
    assert results["kpi.items.count"].value == 3
    assert results["kpi.orders.count"].value == 2
    assert results["kpi.orders.shipment_eligible_count"].value == 2
    assert results["kpi.customers.count"].value == 2
    assert results["kpi.products.count"].value == 1
    assert results["kpi.units.total"].value == 6
    for result in results.values():
        assert result.status == "ok"
        assert isinstance(result.value, int)


def test_zero_orders_is_unavailable_not_zero() -> None:
    tables = make_tables([], [])
    results = by_id(
        kpis.compute_volume(tables, tables.items, tables.orders, kpis.NO_FILTERS)
    )
    assert results["kpi.items.count"].value == 0
    assert results["kpi.orders.count"].status == "unavailable"
    assert results["kpi.orders.count"].value is None
    assert results["kpi.orders.count"].reason == "empty-eligible-population"


# ---------------------------------------------------------------------------
# Commercial formulas
# ---------------------------------------------------------------------------


def test_commercial_sums_use_authoritative_net() -> None:
    # Gross minus discount (30.00 - 2.00 = 28.00) agrees here; the net
    # column stays authoritative even when it disagrees (next test).
    tables = make_tables(
        [base_item("O1"), base_item("O2", net_sales=Decimal("50.00"))],
        [
            base_order("O1", "LATE", True, 5, 3),
            base_order("O2", "ON_SCHEDULE", False, 2, 2, net=Decimal("50.00")),
        ],
    )
    results = by_id(
        kpis.compute_commercial(tables.items, tables.orders, kpis.NO_FILTERS)
    )
    assert results["kpi.value.gross"].value == "60.00"
    assert results["kpi.value.discount"].value == "4.00"
    assert results["kpi.value.net"].value == "78.00"
    assert results["kpi.profit.recorded"].value == "12.00"
    assert results["kpi.value.net"].label == "Recorded net order value"


def test_gross_discount_disagreement_does_not_rewrite_net() -> None:
    # Recorded net (25.00) disagrees with gross minus discount (28.00):
    # the authoritative net wins; nothing is recomputed (ADR-008).
    tables = make_tables(
        [base_item("O1", net_sales=Decimal("25.00"))],
        [base_order("O1", "LATE", True, 5, 3, net=Decimal("25.00"))],
    )
    results = by_id(
        kpis.compute_commercial(tables.items, tables.orders, kpis.NO_FILTERS)
    )
    assert results["kpi.value.net"].value == "25.00"
    assert results["kpi.value.gross"].value == "30.00"


def test_negative_profit_retained() -> None:
    tables = make_tables(
        [
            base_item("O1", profit_amount=Decimal("-5.00")),
            base_item("O2", profit_amount=Decimal("1.00")),
        ],
        [
            base_order("O1", "LATE", True, 5, 3, profit=Decimal("-5.00")),
            base_order("O2", "ON_SCHEDULE", False, 2, 2, profit=Decimal("1.00")),
        ],
    )
    results = by_id(
        kpis.compute_commercial(tables.items, tables.orders, kpis.NO_FILTERS)
    )
    assert results["kpi.profit.recorded"].value == "-4.00"
    assert results["kpi.orders.loss_making_rate"].value == "0.5000"
    assert results["kpi.orders.loss_making_rate"].numerator == 1
    assert results["kpi.orders.loss_making_rate"].denominator == 2


def test_margin_is_ratio_of_sums_not_mean_of_margins() -> None:
    # Line margins 50% (10/20) and 10% (8/80): the mean of margins is
    # 30%, the governed amount-weighted margin is 18/100 = 18%.
    tables = make_tables(
        [
            base_item(
                "O1",
                gross_sales=Decimal("20.00"),
                discount_amount=Decimal("0.00"),
                net_sales=Decimal("20.00"),
                profit_amount=Decimal("10.00"),
            ),
            base_item(
                "O2",
                gross_sales=Decimal("80.00"),
                discount_amount=Decimal("0.00"),
                net_sales=Decimal("80.00"),
                profit_amount=Decimal("8.00"),
            ),
        ],
        [
            base_order(
                "O1", "LATE", True, 5, 3, net=Decimal("20.00"), profit=Decimal("10.00")
            ),
            base_order(
                "O2",
                "ON_SCHEDULE",
                False,
                2,
                2,
                net=Decimal("80.00"),
                profit=Decimal("8.00"),
            ),
        ],
    )
    results = by_id(
        kpis.compute_commercial(tables.items, tables.orders, kpis.NO_FILTERS)
    )
    assert results["kpi.margin.profit"].value == "0.1800"
    assert results["kpi.margin.profit"].numerator == "18.00"
    assert results["kpi.margin.profit"].denominator == "100.00"


def test_zero_net_denominator_is_unavailable() -> None:
    tables = make_tables(
        [base_item("O1", net_sales=Decimal("0.00"), profit_amount=Decimal("1.00"))],
        [base_order("O1", "LATE", True, 5, 3, net=Decimal("0.00"))],
    )
    results = by_id(
        kpis.compute_commercial(tables.items, tables.orders, kpis.NO_FILTERS)
    )
    margin = results["kpi.margin.profit"]
    assert margin.status == "unavailable"
    assert margin.value is None
    assert margin.reason == "zero-denominator"


def test_zero_gross_denominator_is_unavailable() -> None:
    tables = make_tables(
        [base_item("O1", gross_sales=Decimal("0.00"))],
        [base_order("O1", "LATE", True, 5, 3)],
    )
    results = by_id(
        kpis.compute_commercial(tables.items, tables.orders, kpis.NO_FILTERS)
    )
    rate = results["kpi.rate.discount"]
    assert rate.status == "unavailable"
    assert rate.reason == "zero-denominator"


def test_missing_money_excluded_and_counted() -> None:
    tables = make_tables(
        [base_item("O1"), base_item("O2", net_sales=None, profit_amount=None)],
        [
            base_order("O1", "LATE", True, 5, 3),
            base_order("O2", "ON_SCHEDULE", False, 2, 2),
        ],
    )
    results = by_id(
        kpis.compute_commercial(tables.items, tables.orders, kpis.NO_FILTERS)
    )
    assert results["kpi.value.net"].value == "28.00"
    assert results["kpi.value.net"].missingDataCount == 1
    assert results["kpi.margin.profit"].value == "0.2143"  # 6/28
    assert results["kpi.margin.profit"].missingDataCount == 1


def test_per_order_means_and_aov() -> None:
    tables = make_tables(
        [
            base_item("O1"),
            base_item("O1", quantity_units=4),
            base_item("O2", net_sales=Decimal("50.00"), quantity_units=3),
        ],
        [
            base_order(
                "O1", "LATE", True, 5, 3, net=Decimal("56.00"), units=6, lines=2
            ),
            base_order("O2", "ON_SCHEDULE", False, 2, 2, net=Decimal("50.00"), units=3),
        ],
    )
    results = by_id(
        kpis.compute_commercial(tables.items, tables.orders, kpis.NO_FILTERS)
    )
    assert results["kpi.value.aov"].value == "53.00"  # 106/2
    assert results["kpi.value.aov"].numerator == "106.00"
    assert results["kpi.value.aov"].denominator == 2
    assert results["kpi.units.per_order"].value == "4.50"  # 9/2
    assert results["kpi.lines.per_order"].value == "1.50"  # 3/2


def test_no_currency_in_money_values() -> None:
    tables = make_tables([base_item("O1")], [base_order("O1", "LATE", True, 5, 3)])
    for result in kpis.compute_commercial(tables.items, tables.orders, kpis.NO_FILTERS):
        if isinstance(result.value, str) and result.id not in (
            "kpi.units.per_order",
            "kpi.lines.per_order",
        ):
            assert not any(
                symbol in result.value
                for symbol in ("$", "£", "€", "USD", "GBP", "EUR")
            )


# ---------------------------------------------------------------------------
# Delivery formulas and adversarial grain/exclusion cases
# ---------------------------------------------------------------------------


def test_multi_item_order_counts_once() -> None:
    tables = make_tables(
        [base_item("O1"), base_item("O1"), base_item("O1")],
        [base_order("O1", "LATE", True, 5, 3, units=6, lines=3)],
    )
    results = by_id(kpis.compute_delivery(tables.orders, kpis.NO_FILTERS))
    assert results["kpi.ship.late_rate"].numerator == 1
    assert results["kpi.ship.late_rate"].denominator == 1
    assert results["kpi.ship.late_rate"].value == "1.0000"
    assert results["kpi.ship.late_count"].value == 1


def test_early_and_exact_compose_on_schedule() -> None:
    tables = make_tables(
        [base_item("O1"), base_item("O2"), base_item("O3")],
        [
            base_order("O1", "LATE", True, 5, 3),
            base_order("O2", "EARLY", False, 1, 4),
            base_order("O3", "ON_SCHEDULE", False, 2, 2),
        ],
    )
    results = by_id(kpis.compute_delivery(tables.orders, kpis.NO_FILTERS))
    assert results["kpi.ship.late_rate"].value == "0.3333"
    assert results["kpi.ship.on_schedule_rate"].value == "0.6667"
    assert results["kpi.ship.early_rate"].value == "0.3333"
    assert results["kpi.ship.exact_rate"].value == "0.3333"
    assert results["kpi.ship.late_count"].value == 1
    assert results["kpi.ship.early_count"].value == 1
    assert results["kpi.ship.exact_count"].value == 1
    # Algebraic invariants: late + on-schedule = eligible;
    # early + exact = on-schedule.
    assert (
        results["kpi.ship.late_count"].value
        + results["kpi.ship.early_count"].value
        + results["kpi.ship.exact_count"].value
        == 3
    )


def test_cancelled_excluded_and_null_not_non_late() -> None:
    tables = make_tables(
        [base_item("O1"), base_item("O2")],
        [
            base_order("O1", "LATE", True, 5, 3),
            base_order(
                "O2",
                "SHIPPING_CANCELED",
                None,
                None,
                3,
                status="CANCELED",
                net=Decimal("9.00"),
                profit=Decimal("-3.00"),
            ),
        ],
    )
    results = by_id(kpis.compute_delivery(tables.orders, kpis.NO_FILTERS))
    assert results["kpi.ship.late_rate"].denominator == 1
    assert results["kpi.ship.late_rate"].value == "1.0000"
    assert results["kpi.ship.on_schedule_rate"].value == "0.0000"
    # The cancelled order is excluded, not counted as non-late.
    assert (
        "1 shipping-cancelled orders excluded"
        in results["kpi.ship.late_rate"].exclusions
    )
    # Strict cancellation and suspected fraud stay distinct.
    assert results["kpi.orders.strict_cancel_rate"].numerator == 1
    assert results["kpi.orders.fraud_rate"].numerator == 0
    assert results["kpi.orders.blocked_rate"].numerator == 1
    assert results["kpi.orders.strict_cancel_rate"].denominator == 2


def test_fraud_distinct_from_cancellation() -> None:
    tables = make_tables(
        [base_item("O1"), base_item("O2")],
        [
            base_order(
                "O1", "SHIPPING_CANCELED", None, None, 3, status="SUSPECTED_FRAUD"
            ),
            base_order("O2", "LATE", True, 5, 3),
        ],
    )
    results = by_id(kpis.compute_delivery(tables.orders, kpis.NO_FILTERS))
    assert results["kpi.orders.strict_cancel_rate"].value == "0.0000"
    assert results["kpi.orders.fraud_rate"].value == "0.5000"
    assert results["kpi.orders.blocked_rate"].value == "0.5000"


def test_empty_eligible_population_is_unavailable() -> None:
    tables = make_tables(
        [base_item("O1")],
        [base_order("O1", "SHIPPING_CANCELED", None, None, 3, status="CANCELED")],
    )
    results = by_id(kpis.compute_delivery(tables.orders, kpis.NO_FILTERS))
    for kpi_id in (
        "kpi.ship.late_rate",
        "kpi.ship.on_schedule_rate",
        "kpi.ship.early_rate",
        "kpi.ship.exact_rate",
    ):
        assert results[kpi_id].status == "unavailable"
        assert results[kpi_id].value is None
        assert results[kpi_id].reason == "empty-eligible-population"
    late_net = by_id(
        kpis.compute_commercial(tables.items, tables.orders, kpis.NO_FILTERS)
    )["kpi.value.net_associated_with_late"]
    assert late_net.status == "unavailable"


def test_null_outcome_excluded_from_adherence() -> None:
    """Non-cancelled orders with unavailable classification dilute nothing.

    O4 is not shipping-cancelled but misses its day inputs, so canonical
    outcome/is_late are null: it must leave every adherence numerator and
    denominator alone, surface in missingDataCount, and keep
    late + early + exact = eligible over the classifiable population.
    """
    tables = make_tables(
        [
            base_item("O1"),
            base_item("O2"),
            base_item("O3"),
            base_item("O4"),
            base_item("O5"),
        ],
        [
            base_order("O1", "LATE", True, 5, 3),
            base_order("O2", "EARLY", False, 1, 4),
            base_order("O3", "ON_SCHEDULE", False, 2, 2),
            base_order("O4", "", None, None, None),
            base_order("O5", "SHIPPING_CANCELED", None, None, 3, status="CANCELED"),
        ],
    )
    volume = by_id(
        kpis.compute_volume(tables, tables.items, tables.orders, kpis.NO_FILTERS)
    )
    assert volume["kpi.orders.shipment_eligible_count"].value == 3
    assert volume["kpi.orders.shipment_eligible_count"].missingDataCount == 1
    delivery = by_id(kpis.compute_delivery(tables.orders, kpis.NO_FILTERS))
    assert delivery["kpi.ship.late_count"].value == 1
    assert delivery["kpi.ship.early_count"].value == 1
    assert delivery["kpi.ship.exact_count"].value == 1
    assert (
        delivery["kpi.ship.late_count"].value
        + delivery["kpi.ship.early_count"].value
        + delivery["kpi.ship.exact_count"].value
        == volume["kpi.orders.shipment_eligible_count"].value
    )
    assert delivery["kpi.ship.late_rate"].denominator == 3
    assert delivery["kpi.ship.late_rate"].value == "0.3333"
    assert delivery["kpi.ship.on_schedule_rate"].value == "0.6667"
    assert delivery["kpi.ship.late_rate"].missingDataCount == 1
    totals = kpis.headline_totals(tables)
    assert totals["eligibleOrders"] == 3
    commercial = by_id(
        kpis.compute_commercial(tables.items, tables.orders, kpis.NO_FILTERS)
    )
    late_net = commercial["kpi.value.net_associated_with_late"]
    assert late_net.numerator == "28.00"
    assert late_net.denominator == "84.00"


def test_all_unclassifiable_eligible_count_is_unavailable() -> None:
    """Zero classifiable orders: eligible count is unavailable, never 0/ok."""
    tables = make_tables(
        [base_item("O1"), base_item("O2")],
        [
            base_order("O1", "SHIPPING_CANCELED", None, None, 3, status="CANCELED"),
            base_order("O2", "", None, None, None),
        ],
    )
    volume = by_id(
        kpis.compute_volume(tables, tables.items, tables.orders, kpis.NO_FILTERS)
    )
    eligible = volume["kpi.orders.shipment_eligible_count"]
    assert eligible.status == "unavailable"
    assert eligible.value is None
    assert eligible.reason == "empty-eligible-population"
    assert eligible.missingDataCount == 1
    delivery = by_id(kpis.compute_delivery(tables.orders, kpis.NO_FILTERS))
    for kpi_id in (
        "kpi.ship.late_rate",
        "kpi.ship.on_schedule_rate",
        "kpi.ship.early_rate",
        "kpi.ship.exact_rate",
    ):
        assert delivery[kpi_id].status == "unavailable"
        assert delivery[kpi_id].value is None


def test_filtered_entity_counts_narrow_to_population() -> None:
    """Filtered headline counts participants; unfiltered keeps table authority."""
    tables = make_tables(
        [
            base_item(
                "O1", customer_id="C1", product_id="P1", destination_region="North"
            ),
            base_item(
                "O2", customer_id="C2", product_id="P2", destination_region="South"
            ),
        ],
        [
            base_order("O1", "LATE", True, 5, 3, destination_region="North"),
            base_order(
                "O2",
                "EARLY",
                False,
                1,
                4,
                destination_region="South",
                customer_id="C2",
            ),
        ],
        products=["P1", "P2", "P9-STALE"],
        customers=["C1", "C2", "C9-STALE"],
    )
    plain = by_id(kpis.compute_headline(tables))
    assert plain["kpi.customers.count"].value == 3
    assert plain["kpi.products.count"].value == 3
    narrowed = by_id(kpis.compute_headline(tables, kpis.KpiFilters(region="South")))
    assert narrowed["kpi.orders.count"].value == 1
    assert narrowed["kpi.customers.count"].value == 1
    assert narrowed["kpi.products.count"].value == 1
    # Count computation moves no amounts.
    assert narrowed["kpi.value.net"].value == "28.00"
    assert narrowed["kpi.units.total"].value == 2


def test_grouped_delivery_cancel_rates_use_all_orders_frame() -> None:
    """Adherence from the classifiable slice; cancel rates from all orders."""
    tables = make_tables(
        [
            base_item("O1", shipping_mode="MODE_A"),
            base_item("O2", shipping_mode="MODE_A"),
            base_item("O3", shipping_mode="MODE_A"),
            base_item("O4", shipping_mode="MODE_A"),
            base_item("O5", shipping_mode="MODE_B"),
        ],
        [
            base_order("O1", "LATE", True, 5, 3, shipping_mode="MODE_A"),
            base_order(
                "O2",
                "SHIPPING_CANCELED",
                None,
                None,
                3,
                status="CANCELED",
                shipping_mode="MODE_A",
            ),
            base_order(
                "O3",
                "SHIPPING_CANCELED",
                None,
                None,
                3,
                status="SUSPECTED_FRAUD",
                shipping_mode="MODE_A",
            ),
            base_order(
                "O4",
                "SHIPPING_CANCELED",
                None,
                None,
                3,
                status="COMPLETE",
                shipping_mode="MODE_A",
            ),
            base_order("O5", "EARLY", False, 1, 4, shipping_mode="MODE_B"),
        ],
    )
    groups = dict(kpis.compute_groups(tables, "shipping_mode", kpis.NO_FILTERS, True))
    assert set(groups) == {"MODE_A", "MODE_B"}
    mode_a = by_id(groups["MODE_A"])
    # Adherence sees only the one classifiable order in MODE_A.
    assert mode_a["kpi.ship.late_count"].value == 1
    assert mode_a["kpi.ship.late_rate"].denominator == 1
    # Cancellation rates see all four MODE_A orders.
    assert mode_a["kpi.orders.strict_cancel_rate"].numerator == 1
    assert mode_a["kpi.orders.strict_cancel_rate"].denominator == 4
    assert mode_a["kpi.orders.fraud_rate"].numerator == 1
    assert mode_a["kpi.orders.fraud_rate"].denominator == 4
    assert mode_a["kpi.orders.blocked_rate"].numerator == 3
    assert mode_a["kpi.orders.blocked_rate"].denominator == 4
    assert mode_a["kpi.orders.blocked_rate"].value == "0.7500"
    mode_b = by_id(groups["MODE_B"])
    assert mode_b["kpi.ship.early_count"].value == 1
    assert mode_b["kpi.orders.blocked_rate"].value == "0.0000"


def test_day_averages_and_variance() -> None:
    tables = make_tables(
        [base_item("O1"), base_item("O2")],
        [
            base_order("O1", "LATE", True, 5, 3),
            base_order("O2", "EARLY", False, 1, 4),
        ],
    )
    results = by_id(kpis.compute_delivery(tables.orders, kpis.NO_FILTERS))
    assert results["kpi.ship.avg_actual_days"].value == "3.00"  # (5+1)/2
    assert results["kpi.ship.avg_actual_days"].numerator == 6
    assert results["kpi.ship.avg_actual_days"].denominator == 2
    assert results["kpi.ship.avg_scheduled_days"].value == "3.50"  # (3+4)/2
    assert results["kpi.ship.variance_days"].value == "-0.50"  # (2-3)/2
    assert results["kpi.ship.variance_days"].numerator == -1


def test_late_associated_net_is_association_only() -> None:
    tables = make_tables(
        [base_item("O1"), base_item("O2")],
        [
            base_order("O1", "LATE", True, 5, 3),
            base_order("O2", "ON_SCHEDULE", False, 2, 2, net=Decimal("50.00")),
        ],
    )
    results = by_id(
        kpis.compute_commercial(tables.items, tables.orders, kpis.NO_FILTERS)
    )
    late_net = results["kpi.value.net_associated_with_late"]
    assert late_net.value == "28.00"
    assert late_net.numerator == "28.00"
    assert late_net.denominator == "78.00"
    assert "never lost sales" in late_net.exclusions


# ---------------------------------------------------------------------------
# Session-driven fixture check (hand-computed from canonical_small.csv)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def session_root(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", root)
    return root


def _overview_kpis(client: TestClient, session_id: str) -> dict[str, dict]:
    response = client.get(f"/api/v1/sessions/{session_id}/kpis/overview")
    assert response.status_code == 200
    return {entry["id"]: entry for entry in response.json()["data"]["kpis"]}


def test_small_fixture_headline_matches_hand_computation(
    client: TestClient, session_root: str
) -> None:
    response = client.post(
        "/api/v1/sessions/uploads",
        files={"file": ("data.csv", CANON_BYTES, "text/csv")},
    )
    assert response.status_code == 202
    session_id = response.json()["data"]["sessionId"]
    status = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert status["state"] == "READY"
    entry = _overview_kpis(client, session_id)

    # Volume: 6 lines, 4 orders, 3 eligible, 4 customers, 4 products, 9 units.
    assert entry["kpi.items.count"]["value"] == 6
    assert entry["kpi.orders.count"]["value"] == 4
    assert entry["kpi.orders.shipment_eligible_count"]["value"] == 3
    assert entry["kpi.customers.count"]["value"] == 4
    assert entry["kpi.products.count"]["value"] == 4
    assert entry["kpi.units.total"]["value"] == 9
    # Commercial: gross 129.98, discounts 6.50, net 123.48, profit 15.15.
    assert entry["kpi.value.gross"]["value"] == "129.98"
    assert entry["kpi.value.discount"]["value"] == "6.50"
    assert entry["kpi.value.net"]["value"] == "123.48"
    assert entry["kpi.profit.recorded"]["value"] == "15.15"
    assert entry["kpi.margin.profit"]["value"] == "0.1227"
    assert entry["kpi.rate.discount"]["value"] == "0.0500"
    assert entry["kpi.value.aov"]["value"] == "30.87"
    assert entry["kpi.units.per_order"]["value"] == "2.25"
    assert entry["kpi.lines.per_order"]["value"] == "1.50"
    assert entry["kpi.orders.loss_making_rate"]["value"] == "0.2500"
    assert entry["kpi.value.net_associated_with_late"]["value"] == "47.48"
    # Delivery: 1 late / 1 early / 1 exact of 3 eligible; 1 cancelled.
    assert entry["kpi.ship.late_rate"]["value"] == "0.3333"
    assert entry["kpi.ship.on_schedule_rate"]["value"] == "0.6667"
    assert entry["kpi.ship.early_rate"]["value"] == "0.3333"
    assert entry["kpi.ship.exact_rate"]["value"] == "0.3333"
    assert entry["kpi.ship.late_count"]["value"] == 1
    assert entry["kpi.ship.avg_actual_days"]["value"] == "2.67"
    assert entry["kpi.ship.avg_scheduled_days"]["value"] == "3.00"
    assert entry["kpi.ship.variance_days"]["value"] == "-0.33"
    assert entry["kpi.orders.strict_cancel_rate"]["value"] == "0.2500"
    assert entry["kpi.orders.fraud_rate"]["value"] == "0.0000"
    assert entry["kpi.orders.blocked_rate"]["value"] == "0.2500"
    for payload in entry.values():
        assert payload["status"] == "ok"
        assert payload["label"] == kpis.KPI_LABELS[payload["id"]]
