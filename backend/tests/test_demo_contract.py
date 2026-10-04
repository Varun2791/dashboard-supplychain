"""Phase-18B bundled synthetic reviewer-demo contract (no DataCo bytes).

Locks the governed artifact at `demo/supply-chain-demo.csv` (ADR-044):

- artifact/scale/schema headers (Layer 1);
- synthetic + privacy posture (Layer 2);
- grain/invariance semantics (Layer 3);
- coverage populations (Layer 4);
- real-pipeline READY with zero blocking DQ errors (Layer 5);
- deliberate DQ behaviors only (Layer 6);
- marker quarantine through schema mapping, not the DQ issue list (Layer 7);
- canonical outputs (Layer 8);
- analytical usability without exact synthetic totals (Layer 9).

Deliberately NOT asserted (incidental/internal accounting): DQ-KEY-002 /
DQ-DATE-004 counts, rulesEvaluated/triggered totals, cleaning detected /
unchanged aggregates, negative-row counts, margins, or exact KPI totals.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.sessions as session_store
from app import kpis as kpi_service
from app.config import settings
from app.main import app
from app.profile_checks import (
    CUSTOMER_INVARIANCE_FIELDS,
    INVARIANCE_FIELDS,
    PRODUCT_INVARIANCE_FIELDS,
)
from app.schema_registry import OPTIONAL_MAPPINGS, REQUIRED_MAPPINGS

DEMO_CSV = Path(__file__).resolve().parents[2] / "demo" / "supply-chain-demo.csv"

MARKER_HEADER = "Synthetic Demo Marker"
EXTREME_ITEM = "SYN-ITEM-120"
MISMATCH_ITEM = "SYN-ITEM-121"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def load_demo_rows() -> tuple[list[str], list[dict[str, str]]]:
    with open(DEMO_CSV, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        return headers, [dict(row) for row in reader]


def upload_demo(client: TestClient) -> str:
    response = client.post(
        "/api/v1/sessions/uploads",
        files={"file": ("supply-chain-demo.csv", DEMO_CSV.read_bytes(), "text/csv")},
    )
    assert response.status_code == 202
    return response.json()["data"]["sessionId"]


def quality_by_rule(client: TestClient, session_id: str) -> tuple[dict, dict]:
    response = client.get(f"/api/v1/sessions/{session_id}/data-quality")
    assert response.status_code == 200
    data = response.json()["data"]
    return {issue["ruleId"]: issue for issue in data["issues"]}, data["summary"]


def canonical_source_of(canonical_field: str) -> str:
    for entry in (*REQUIRED_MAPPINGS, *OPTIONAL_MAPPINGS):
        if entry.canonical_field == canonical_field:
            return entry.source_header
    raise AssertionError(f"no governed source header for {canonical_field!r}")


def order_month(value: str) -> str:
    return datetime.strptime(value, "%m-%d-%Y %H:%M").strftime("%Y-%m")


# ---------------------------------------------------------------------------
# Layer 1 — artifact / schema contract
# ---------------------------------------------------------------------------


def test_demo_artifact_scale() -> None:
    headers, rows = load_demo_rows()
    assert len(headers) == 26
    assert len(rows) == 121
    assert len({row["Order Item Id"] for row in rows}) == 121
    assert len({row["Order Id"] for row in rows}) == 50
    assert len({row["Customer Id"] for row in rows}) == 16
    assert len({row["Product Card Id"] for row in rows}) == 8
    assert len({order_month(row["order date (DateOrders)"]) for row in rows}) == 6


def test_demo_headers_match_governed_registry() -> None:
    headers, _ = load_demo_rows()
    required = {entry.source_header for entry in REQUIRED_MAPPINGS}
    optional = {entry.source_header for entry in OPTIONAL_MAPPINGS}
    assert len(required) == 18
    assert len(optional) == 7
    assert required <= set(headers)
    assert optional <= set(headers)
    assert set(headers) - required - optional == {MARKER_HEADER}


# ---------------------------------------------------------------------------
# Layer 2 — synthetic / privacy contract
# ---------------------------------------------------------------------------


def test_demo_ids_are_unmistakably_synthetic() -> None:
    _, rows = load_demo_rows()
    for column in (
        "Order Id",
        "Order Item Id",
        "Customer Id",
        "Product Card Id",
        "Product Category Id",
    ):
        values = {row[column] for row in rows}
        assert values, column
        assert all(value.startswith("SYN-") for value in values), column


def test_demo_marker_labels_every_row_synthetic() -> None:
    _, rows = load_demo_rows()
    markers = {row[MARKER_HEADER] for row in rows}
    assert len(markers) == 1
    marker = next(iter(markers)).casefold()
    assert "synthetic" in marker and "not real" in marker


def test_demo_headers_carry_no_direct_pii_or_precise_geo() -> None:
    headers, _ = load_demo_rows()
    lowered = [header.casefold() for header in headers]
    for token in (
        "first name",
        "last name",
        "email",
        "password",
        "street",
        "address",
        "phone",
        "latitude",
        "longitude",
    ):
        assert all(token not in header for header in lowered), token


# ---------------------------------------------------------------------------
# Layer 3 — grain / invariance
# ---------------------------------------------------------------------------


def test_demo_grain_item_unique_order_repeats() -> None:
    _, rows = load_demo_rows()
    item_ids = [row["Order Item Id"] for row in rows]
    assert len(set(item_ids)) == len(item_ids) == 121
    order_ids = [row["Order Id"] for row in rows]
    assert len(set(order_ids)) == 50 < len(order_ids)


def test_demo_order_level_fields_invariant() -> None:
    _, rows = load_demo_rows()
    by_order: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_order[row["Order Id"]].append(row)
    assert any(len(lines) > 1 for lines in by_order.values())
    for field in INVARIANCE_FIELDS:
        source = canonical_source_of(field)
        for order_id, lines in by_order.items():
            # Profiling compares stripped text; the deliberate CAT-005 trim
            # case lives inside one order and must not read as a conflict.
            values = {line[source].strip() for line in lines}
            assert len(values) == 1, (order_id, field, values)


def test_demo_product_and_customer_dims_invariant() -> None:
    _, rows = load_demo_rows()
    by_product: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_customer: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_product[row["Product Card Id"]].append(row)
        by_customer[row["Customer Id"]].append(row)
    for field in PRODUCT_INVARIANCE_FIELDS:
        source = canonical_source_of(field)
        for product_id, lines in by_product.items():
            assert len({line[source] for line in lines}) == 1, (product_id, field)
    for field in CUSTOMER_INVARIANCE_FIELDS:
        source = canonical_source_of(field)
        for customer_id, lines in by_customer.items():
            assert len({line[source] for line in lines}) == 1, (customer_id, field)


# ---------------------------------------------------------------------------
# Layer 4 — coverage populations
# ---------------------------------------------------------------------------


def test_demo_coverage_populations() -> None:
    _, rows = load_demo_rows()
    assert {row["Customer Segment"] for row in rows} == {
        "Consumer",
        "Corporate",
        "Home Office",
    }
    assert {row["Shipping Mode"] for row in rows} == {
        "Standard Class",
        "Second Class",
        "First Class",
        "Same Day",
    }
    assert len({row["Market"] for row in rows}) >= 2
    assert len({row["Order Region"].strip() for row in rows}) >= 3
    assert len({row["Category Name"] for row in rows}) >= 3

    by_order: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_order[row["Order Id"]].append(row)
    late = early = exact = strict_cancel = fraud = 0
    for lines in by_order.values():
        first = lines[0]
        if first["Delivery Status"] == "Shipping canceled":
            if first["Order Status"] == "CANCELED":
                strict_cancel += 1
            elif first["Order Status"] == "SUSPECTED_FRAUD":
                fraud += 1
            continue
        actual = int(first["Days for shipping (real)"])
        scheduled = int(first["Days for shipment (scheduled)"])
        if actual > scheduled:
            late += 1
        elif actual < scheduled:
            early += 1
        else:
            exact += 1
    assert late > 0 and early > 0 and exact > 0
    assert strict_cancel > 0 and fraud > 0

    profits = [Decimal(row["Benefit per order"]) for row in rows]
    assert any(profit > 0 for profit in profits)
    ordinary_loss = [
        row["Order Item Id"]
        for row in rows
        if Decimal(row["Benefit per order"]) < 0
        and row["Order Item Id"] != EXTREME_ITEM
    ]
    assert ordinary_loss, "loss story must not depend on the extreme row alone"


# ---------------------------------------------------------------------------
# Layers 5–6 — real pipeline READY, zero blocking, deliberate DQ only
# ---------------------------------------------------------------------------


def test_demo_pipeline_reaches_ready_with_zero_blocking(
    client: TestClient,
) -> None:
    session_id = upload_demo(client)
    status = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert status["state"] == "READY"
    assert status["stage"] == "READY"
    assert status["error"] is None
    by_rule, summary = quality_by_rule(client, session_id)
    assert summary["errors"] == 0
    assert summary["blockingIssues"] == 0
    assert all(issue["severity"] != "ERROR" for issue in by_rule.values())


def test_demo_deliberate_dq_behaviors(client: TestClient) -> None:
    session_id = upload_demo(client)
    by_rule, _ = quality_by_rule(client, session_id)
    assert by_rule["DQ-CAT-005"]["count"] == 2
    assert by_rule["DQ-CAT-001"]["count"] == 2
    assert by_rule["DQ-NUM-002"]["count"] == 1
    assert by_rule["DQ-NUM-003"]["count"] == 1


# ---------------------------------------------------------------------------
# Layer 7 — marker / schema quarantine
# ---------------------------------------------------------------------------


def test_demo_marker_quarantined_from_canonical(client: TestClient) -> None:
    session_id = upload_demo(client)
    schema = client.get(f"/api/v1/sessions/{session_id}/schema").json()["data"]
    marker = next(m for m in schema["mapping"] if m["source"] == MARKER_HEADER)
    assert marker["canonical"] is None
    assert marker["class"] == "unknown"

    # The normal DQ issue-list representation of the marker is intentionally
    # not part of this contract: neither presence nor absence of DQ-SCHEMA-003
    # in that list is asserted here.
    paths = session_store.session_paths(settings.session_root, session_id)
    tables = kpi_service.load_canonical_tables(paths)
    for frame in (tables.items, tables.orders):
        assert not any("marker" in column.casefold() for column in frame.columns)


# ---------------------------------------------------------------------------
# Layer 8 — canonical output
# ---------------------------------------------------------------------------


def test_demo_canonical_outputs(client: TestClient) -> None:
    session_id = upload_demo(client)
    paths = session_store.session_paths(settings.session_root, session_id)
    report = session_store.read_canonical_report(paths)
    assert report is not None
    assert report.sourceRows == 121
    rows_by_table = {table.name.split("/")[-1]: table.rows for table in report.tables}
    assert rows_by_table["canonical_order_items.csv"] == 121
    assert rows_by_table["canonical_orders.csv"] == 50
    assert rows_by_table["canonical_customers.csv"] == 16
    assert rows_by_table["canonical_products.csv"] == 8
    assert rows_by_table["canonical_calendar.csv"] > 0
    assert rows_by_table["canonical_data_quality_issues.csv"] > 0


# ---------------------------------------------------------------------------
# Layer 9 — analytical usability (semantic, no exact synthetic totals)
# ---------------------------------------------------------------------------


def test_demo_analytical_usability(client: TestClient) -> None:
    session_id = upload_demo(client)

    overview = client.get(f"/api/v1/sessions/{session_id}/kpis/overview").json()["data"]
    assert overview["kpis"]
    headline = {entry["id"]: entry for entry in overview["kpis"]}
    # Presence + usability of the headline KPIs the demo exercises. Total
    # response length is the application's own catalogue contract (pinned
    # separately in test_kpis.py), not this demo's: a future legitimate KPI
    # addition must not fail the synthetic-demo contract.
    for kpi_id in (
        "kpi.value.net",
        "kpi.orders.loss_making_rate",
        "kpi.ship.late_rate",
        "kpi.ship.on_schedule_rate",
    ):
        assert headline[kpi_id]["status"] == "ok", kpi_id
        assert Decimal(str(headline[kpi_id]["value"])).is_finite(), kpi_id
    assert Decimal(str(headline["kpi.orders.loss_making_rate"]["value"])) > 0

    months = client.get(
        f"/api/v1/sessions/{session_id}/kpis/commercial?by=order_month"
    ).json()["data"]["groups"]
    assert len(months) == 6

    delivery = client.get(
        f"/api/v1/sessions/{session_id}/kpis/delivery?by=shipment_outcome"
    ).json()["data"]["groups"]
    by_outcome = {group["key"]: group for group in delivery}
    assert {"LATE", "EARLY", "ON_SCHEDULE"} <= set(by_outcome)
    for key in ("LATE", "EARLY", "ON_SCHEDULE"):
        kpis = {entry["id"]: entry for entry in by_outcome[key]["kpis"]}
        count_id = {
            "LATE": "kpi.ship.late_count",
            "EARLY": "kpi.ship.early_count",
            "ON_SCHEDULE": "kpi.ship.exact_count",
        }[key]
        assert kpis[count_id]["value"] > 0

    modes = client.get(
        f"/api/v1/sessions/{session_id}/kpis/delivery?by=shipping_mode"
    ).json()["data"]["groups"]
    assert len(modes) == 4

    commercial = client.get(
        f"/api/v1/sessions/{session_id}/kpis/commercial?by=category_name"
    ).json()["data"]["groups"]
    assert len(commercial) >= 3
    products = client.get(
        f"/api/v1/sessions/{session_id}/kpis/commercial?by=product_name"
    ).json()["data"]["groups"]
    assert len(products) > 1

    options = client.get(f"/api/v1/sessions/{session_id}/filter-options").json()["data"]
    assert len(options["markets"]) >= 2
    assert len(options["regions"]) >= 3
    assert len(options["categories"]) >= 3

    narrowed = client.get(
        f"/api/v1/sessions/{session_id}/kpis/overview?region=South"
    ).json()["data"]["totals"]
    assert 0 < narrowed["orders"] < overview["totals"]["orders"]
    assert 0 < narrowed["items"] < overview["totals"]["items"]


# ---------------------------------------------------------------------------
# Extreme-profit independence + net-mismatch isolation
# ---------------------------------------------------------------------------


def test_demo_loss_story_independent_of_extreme_row(client: TestClient) -> None:
    session_id = upload_demo(client)
    paths = session_store.session_paths(settings.session_root, session_id)
    items = kpi_service.load_canonical_tables(paths).items
    other_negatives = [
        item_id
        for item_id, profit in zip(items["order_item_id"], items["_profit_amount"])
        if profit < 0 and item_id != EXTREME_ITEM
    ]
    assert other_negatives

    totals: dict[str, Decimal] = defaultdict(Decimal)
    for product_id, item_id, profit in zip(
        items["product_id"], items["order_item_id"], items["_profit_amount"]
    ):
        if item_id != EXTREME_ITEM:
            totals[product_id] += profit
    assert [product for product, total in totals.items() if total < 0]


def test_demo_net_mismatch_row_stays_authoritative(client: TestClient) -> None:
    session_id = upload_demo(client)
    paths = session_store.session_paths(settings.session_root, session_id)
    items = kpi_service.load_canonical_tables(paths).items
    row = items[items["order_item_id"] == MISMATCH_ITEM].iloc[0]
    assert Decimal(str(row["_net_sales"])) == Decimal("50.00")
    assert Decimal(str(row["_gross_sales"])) - Decimal(
        str(row["_discount_amount"])
    ) != Decimal(str(row["_net_sales"]))
