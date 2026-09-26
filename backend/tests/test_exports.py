"""Phase-16 backend export tests (synthetic data only, no DataCo rows).

Covers the governed export surface: four-kind enforcement, READY gating,
the 8-key filter vocabulary, report filter rejection, grain-specific
category semantics with a multi-merchandise order, explicit allowlists,
DQ-PRIVACY-003 (including hostile headers), CSV injection rules, exact
serialization, reconciliation, provenance, atomic publication, download
integrity, lifecycle, and reproducibility. Every expectation recomputes
from the fixture below; nothing hardcodes reference controls.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.sessions as session_store
from app import exports as export_module
from app.config import settings
from app.main import app

HEADER = (
    "Order Id,Order Item Id,Customer Id,Product Card Id,"
    "Product Category Id,order date (DateOrders),shipping date (DateOrders),"
    "Sales,Order Item Discount,Order Item Total,Benefit per order,"
    "Order Item Product Price,Order Item Quantity,"
    "Days for shipping (real),Days for shipment (scheduled),"
    "Delivery Status,Order Status,Shipping Mode,"
    "Customer Segment,Order Country,Order Region,Market,"
    "Department Name,Category Name,Product Name"
)

BASE = {
    "Customer Id": "SYN-CUST-X",
    "order date (DateOrders)": "03-15-2021 10:00",
    "shipping date (DateOrders)": "03-18-2021 09:00",
    "Order Item Discount": "0.00",
    "Order Item Product Price": "50.00",
    "Order Item Quantity": "1",
    "Days for shipping (real)": "2",
    "Days for shipment (scheduled)": "2",
    "Delivery Status": "Shipped",
    "Order Status": "COMPLETE",
    "Shipping Mode": "Standard Class",
    "Customer Segment": "Consumer",
    "Order Country": "C-Land",
    "Order Region": "R1",
    "Market": "M1",
    "Department Name": "D1",
}

COLUMNS = HEADER.split(",")


def row(**overrides: str) -> str:
    values = dict(BASE)
    values.update(overrides)
    return ",".join(values[name] for name in COLUMNS)


def fixture_csv() -> bytes:
    rows = [
        # M-ORD-A: three Alpha lines (negative line profit + formula text).
        row(
            **{
                "Order Id": "M-ORD-A",
                "Order Item Id": "M-ITM-A1",
                "Customer Id": "SYN-CUST-A",
                "Product Card Id": "PROD-PA1",
                "Product Category Id": "CAT-A",
                "Sales": "90.00",
                "Order Item Total": "90.00",
                "Benefit per order": "9.00",
                "Order Item Quantity": "2",
                "Days for shipping (real)": "3",
                "Days for shipment (scheduled)": "5",
                "Category Name": "Alpha",
                "Product Name": "Widget A1",
            }
        ),
        row(
            **{
                "Order Id": "M-ORD-A",
                "Order Item Id": "M-ITM-A2",
                "Customer Id": "SYN-CUST-A",
                "Product Card Id": "PROD-PA2",
                "Product Category Id": "CAT-A",
                "Sales": "45.00",
                "Order Item Total": "45.00",
                "Benefit per order": "-4.00",
                "Order Item Quantity": "1",
                "Days for shipping (real)": "3",
                "Days for shipment (scheduled)": "5",
                "Category Name": "Alpha",
                "Product Name": "Widget A2",
            }
        ),
        row(
            **{
                "Order Id": "M-ORD-A",
                "Order Item Id": "M-ITM-A3",
                "Customer Id": "SYN-CUST-A",
                "Product Card Id": "PROD-PA3",
                "Product Category Id": "CAT-A",
                "Sales": "10.00",
                "Order Item Total": "10.00",
                "Benefit per order": "1.00",
                "Order Item Quantity": "1",
                "Days for shipping (real)": "3",
                "Days for shipment (scheduled)": "5",
                "Category Name": "Alpha",
                "Product Name": "=SUM(A1:A2)",
            }
        ),
        # M-ORD-X: multi-merchandise (Alpha + Beta) → null order category.
        row(
            **{
                "Order Id": "M-ORD-X",
                "Order Item Id": "M-ITM-X1",
                "Customer Id": "SYN-CUST-X",
                "Product Card Id": "PROD-PX1",
                "Product Category Id": "CAT-A",
                "order date (DateOrders)": "03-16-2021 11:00",
                "Sales": "10.00",
                "Order Item Total": "10.00",
                "Benefit per order": "1.00",
                "Category Name": "Alpha",
                "Product Name": "Widget X1",
            }
        ),
        row(
            **{
                "Order Id": "M-ORD-X",
                "Order Item Id": "M-ITM-X2",
                "Customer Id": "SYN-CUST-X",
                "Product Card Id": "PROD-PX2",
                "Product Category Id": "CAT-B",
                "order date (DateOrders)": "03-16-2021 11:00",
                "Sales": "20.00",
                "Order Item Total": "20.00",
                "Benefit per order": "2.00",
                "Order Item Quantity": "3",
                "Category Name": "Beta",
                "Product Name": "cmd|/c calc",
            }
        ),
        # M-ORD-B: single Beta order (negative order profit).
        row(
            **{
                "Order Id": "M-ORD-B",
                "Order Item Id": "M-ITM-B1",
                "Customer Id": "SYN-CUST-B",
                "Product Card Id": "PROD-PB1",
                "Product Category Id": "CAT-B",
                "order date (DateOrders)": "03-16-2021 11:00",
                "Sales": "40.00",
                "Order Item Total": "40.00",
                "Benefit per order": "-50.00",
                "Order Item Quantity": "2",
                "Days for shipping (real)": "1",
                "Days for shipment (scheduled)": "4",
                "Order Status": "PROCESSING",
                "Shipping Mode": "Same Day",
                "Customer Segment": "Home Office",
                "Order Region": "R2",
                "Market": "M2",
                "Department Name": "D2",
                "Category Name": "Beta",
                "Product Name": "Widget B1",
            }
        ),
        # M-ORD-C: shipping-cancelled strict CANCELED order (is_late null).
        row(
            **{
                "Order Id": "M-ORD-C",
                "Order Item Id": "M-ITM-C1",
                "Customer Id": "SYN-CUST-C",
                "Product Card Id": "PROD-PC1",
                "Product Category Id": "CAT-A",
                "order date (DateOrders)": "03-10-2021 09:00",
                "Sales": "60.00",
                "Order Item Total": "60.00",
                "Benefit per order": "6.00",
                "Days for shipping (real)": "9",
                "Days for shipment (scheduled)": "3",
                "Delivery Status": "Shipping canceled",
                "Order Status": "CANCELED",
                "Category Name": "Alpha",
                "Product Name": "Widget C1",
            }
        ),
        # M-ORD-F: suspected-fraud late order (latest timestamp).
        row(
            **{
                "Order Id": "M-ORD-F",
                "Order Item Id": "M-ITM-F1",
                "Customer Id": "SYN-CUST-F",
                "Product Card Id": "PROD-PF1",
                "Product Category Id": "CAT-G",
                "order date (DateOrders)": "03-20-2021 08:00",
                "Sales": "70.00",
                "Order Item Total": "70.00",
                "Benefit per order": "7.00",
                "Order Item Quantity": "2",
                "Days for shipping (real)": "6",
                "Days for shipment (scheduled)": "5",
                "Order Status": "SUSPECTED_FRAUD",
                "Shipping Mode": "Same Day",
                "Order Region": "R2",
                "Market": "M2",
                "Department Name": "D2",
                "Category Name": "Gamma",
                "Product Name": "Widget F1",
            }
        ),
    ]
    return (HEADER + "\n" + "\n".join(rows) + "\n").encode()


EXPORT_BYTES = fixture_csv()

EXPECTED_ITEMS_ALLOWLIST = [
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
]

EXPECTED_ORDERS_ALLOWLIST = [
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
]

PROVENANCE_KEYS = {
    "appVersion",
    "schemaVersion",
    "sessionId",
    "sourceFilenameSafe",
    "sourceSha256",
    "sourceBytes",
    "generatedAt",
    "filtersApplied",
    "exportKind",
    "dataProvenance",
    "currencyNote",
    "syntheticDataNote",
}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", root)
    return root


def upload_ok(client: TestClient, content: bytes, name: str = "data.csv") -> str:
    response = client.post(
        "/api/v1/sessions/uploads",
        files={"file": (name, content, "text/csv")},
    )
    assert response.status_code == 202, response.text
    return str(response.json()["data"]["sessionId"])


def ready_session(client: TestClient, content: bytes = EXPORT_BYTES) -> str:
    session_id = upload_ok(client, content)
    state = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert state["state"] == "READY", state
    return session_id


def post_export(
    client: TestClient, session_id: str, kind: str, filters: Any = None
) -> Any:
    body: dict[str, Any] = {"kind": kind}
    if filters is not None:
        body["filters"] = filters
    return client.post(f"/api/v1/sessions/{session_id}/exports", json=body)


def parse_csv(content: bytes) -> tuple[list[str], list[list[str]]]:
    text = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    return rows[0], rows[1:]


# ---------------------------------------------------------------------------
# Kind set and lifecycle gating
# ---------------------------------------------------------------------------


def test_allowlists_match_contract_exactly() -> None:
    assert list(export_module.CLEANED_ITEMS_COLUMNS) == EXPECTED_ITEMS_ALLOWLIST
    assert list(export_module.ORDERS_COLUMNS) == EXPECTED_ORDERS_ALLOWLIST
    for kind in ("cleaned_items", "orders"):
        assert (
            export_module.run_privacy_gate(
                kind, list(export_module.KIND_ALLOWLIST[kind])
            )
            == []
        )


def test_unknown_kind_rejected(client: TestClient) -> None:
    session_id = ready_session(client)
    for kind in ("raw", "kpis", "dashboard", "cleaned.csv", "", "CLEANED_ITEMS"):
        response = post_export(client, session_id, kind)
        assert response.status_code == 400, (kind, response.text)
        assert response.json()["error"]["code"] == "INVALID_EXPORT_KIND"


def test_unknown_session_rejected(client: TestClient) -> None:
    response = post_export(client, "00000000-0000-4000-8000-000000000000", "orders")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_pre_ready_session_rejected(client: TestClient, session_root: str) -> None:
    import uuid as uuid_module

    from app.canonicalization import ensure_canonicalized
    from app.cleaning import ensure_cleaned
    from app.profiling import ensure_profiled
    from app.schema_validation import ensure_schema_validated

    session_id = str(uuid_module.uuid4())
    paths = session_store.session_paths(session_root, session_id)
    os.makedirs(paths.derived)
    os.makedirs(paths.exports)
    with open(paths.raw, "wb") as handle:
        handle.write(EXPORT_BYTES)
    now = session_store.utcnow_naive_iso()
    manifest = session_store.build_manifest(
        session_id=session_id,
        filename_safe="data.csv",
        size_bytes=len(EXPORT_BYTES),
        sha256_hex=hashlib.sha256(EXPORT_BYTES).hexdigest(),
        encoding="utf-8",
        now=now,
    )
    session_store.write_manifest(paths, manifest)
    validated = ensure_schema_validated(paths, manifest, now)
    profiled = ensure_profiled(paths, validated, now)
    cleaned = ensure_cleaned(paths, profiled, now)
    canonicalized = ensure_canonicalized(paths, cleaned, now)
    assert canonicalized.state == "ANALYZING"
    response = post_export(client, session_id, "orders")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NOT_READY"


def test_failed_session_resurfaces_stored_error(client: TestClient) -> None:
    bad = EXPORT_BYTES.replace(b"Order Id,", b"Gone Id,", 1)
    session_id = upload_ok(client, bad)
    state = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert state["state"] == "FAILED", state
    response = post_export(client, session_id, "orders")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SCHEMA_MISSING_COLUMN"


# ---------------------------------------------------------------------------
# Filter vocabulary and report rejection
# ---------------------------------------------------------------------------


def test_export_filter_vocabulary_exact(client: TestClient) -> None:
    session_id = ready_session(client)
    assert list(export_module.EXPORT_FILTER_KEYS) == [
        "from",
        "to",
        "market",
        "region",
        "category",
        "shipping_mode",
        "order_status",
        "shipment_outcome",
    ]
    good = [
        {"market": "M1"},
        {"region": "R2"},
        {"category": "Alpha"},
        {"shipping_mode": "SAME_DAY"},
        {"order_status": "COMPLETE"},
        {"shipment_outcome": "LATE"},
        {"from": "2021-03-12", "to": "2021-03-16"},
    ]
    for filters in good:
        response = post_export(client, session_id, "orders", filters)
        assert response.status_code == 201, (filters, response.text)


def test_export_filter_rejections(client: TestClient) -> None:
    session_id = ready_session(client)
    bad = [
        {"department": "D1"},
        {"customer_segment": "CONSUMER"},
        {"nonsense": "x"},
        {"market": "M1", "department": "D1"},
        {"shipping_mode": "Rocket"},
        {"order_status": "COMPLETE " + "X"},
        {"shipment_outcome": "late"},
        {"from": "not-a-date"},
        {"market": 123},
        ["market"],
    ]
    for filters in bad:
        response = post_export(client, session_id, "orders", filters)
        assert response.status_code == 422, (filters, response.text)
        assert response.json()["error"]["code"] == "INVALID_FILTER_VALUE"


def test_reports_reject_nonempty_filters(client: TestClient) -> None:
    session_id = ready_session(client)
    for kind in ("quality_report", "cleaning_report"):
        rejected = post_export(client, session_id, kind, {"market": "M1"})
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["error"]["code"] == "INVALID_FILTER_VALUE"
        for accepted in (None, {}, {"market": ""}, {"market": "   "}):
            response = post_export(client, session_id, kind, accepted)
            assert response.status_code == 201, (kind, accepted, response.text)
            assert response.json()["data"]["metadata"] is None


# ---------------------------------------------------------------------------
# Data exports: content, grain, reconciliation
# ---------------------------------------------------------------------------


def test_cleaned_items_unfiltered_content(client: TestClient) -> None:
    session_id = ready_session(client)
    response = post_export(client, session_id, "cleaned_items")
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert re.fullmatch(r"[0-9a-f]{32}", data["exportId"])
    assert data["metadata"] is not None
    download = client.get(f"/api/v1/sessions/{session_id}/exports/{data['exportId']}")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/csv")
    assert download.headers["content-disposition"] == (
        f'attachment; filename="{data["filename"]}"'
    )
    assert download.content.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in download.content
    header, rows = parse_csv(download.content)
    assert header == EXPECTED_ITEMS_ALLOWLIST
    assert len(rows) == 8  # one row per canonical order item
    by_item = {cells[2]: cells for cells in rows}
    assert set(by_item) == {
        "M-ITM-A1",
        "M-ITM-A2",
        "M-ITM-A3",
        "M-ITM-X1",
        "M-ITM-X2",
        "M-ITM-B1",
        "M-ITM-C1",
        "M-ITM-F1",
    }
    net = sum(Decimal(cells[11]) for cells in rows)
    assert net == Decimal("345.00")
    profit = sum(Decimal(cells[12]) for cells in rows)
    assert profit == Decimal("-28.00")
    # Cancelled line keeps null lateness; dates/money render per contract.
    cancelled = by_item["M-ITM-C1"]
    assert cancelled[21] == ""
    assert cancelled[16].startswith("2021-03-10T")
    assert cancelled[23] == "2021-03-10"
    assert hashlib.sha256(download.content).hexdigest() == data["sha256"]
    assert data["bytes"] == len(download.content)


def test_cleaned_items_category_is_item_grain(client: TestClient) -> None:
    session_id = ready_session(client)
    response = post_export(client, session_id, "cleaned_items", {"category": "Alpha"})
    assert response.status_code == 201, response.text
    download = client.get(
        f"/api/v1/sessions/{session_id}/exports/{response.json()['data']['exportId']}"
    )
    _, rows = parse_csv(download.content)
    # Multi-merch order M-ORD-X still contributes its matching Alpha line.
    assert sorted(cells[2] for cells in rows) == [
        "M-ITM-A1",
        "M-ITM-A2",
        "M-ITM-A3",
        "M-ITM-C1",
        "M-ITM-X1",
    ]
    assert sum(Decimal(cells[11]) for cells in rows) == Decimal("215.00")


def test_orders_category_excludes_multi_merch(client: TestClient) -> None:
    session_id = ready_session(client)
    response = post_export(client, session_id, "orders", {"category": "Alpha"})
    assert response.status_code == 201, response.text
    download = client.get(
        f"/api/v1/sessions/{session_id}/exports/{response.json()['data']['exportId']}"
    )
    header, rows = parse_csv(download.content)
    assert header == EXPECTED_ORDERS_ALLOWLIST
    assert sorted(cells[0] for cells in rows) == ["M-ORD-A", "M-ORD-C"]
    by_order = {cells[0]: cells for cells in rows}
    assert by_order["M-ORD-A"][17] == "145.00"  # whole-order aggregate
    assert by_order["M-ORD-A"][13] == "3"
    assert by_order["M-ORD-C"][12] == ""  # cancelled: null lateness


def test_cross_grain_totals_not_forced_equal(client: TestClient) -> None:
    """Governed asymmetry: item lines from excluded multi-merch orders
    count for cleaned_items but never for the order-frame export."""
    session_id = ready_session(client)
    items_id = post_export(
        client, session_id, "cleaned_items", {"category": "Alpha"}
    ).json()["data"]["exportId"]
    orders_id = post_export(client, session_id, "orders", {"category": "Alpha"}).json()[
        "data"
    ]["exportId"]
    _, item_rows = parse_csv(
        client.get(f"/api/v1/sessions/{session_id}/exports/{items_id}").content
    )
    _, order_rows = parse_csv(
        client.get(f"/api/v1/sessions/{session_id}/exports/{orders_id}").content
    )
    items_net = sum(Decimal(cells[11]) for cells in item_rows)
    orders_net = sum(Decimal(cells[17]) for cells in order_rows)
    assert items_net == Decimal("215.00")
    assert orders_net == Decimal("205.00")
    assert items_net != orders_net


def test_orders_unfiltered_reconciles(client: TestClient) -> None:
    session_id = ready_session(client)
    export_id = post_export(client, session_id, "orders").json()["data"]["exportId"]
    _, rows = parse_csv(
        client.get(f"/api/v1/sessions/{session_id}/exports/{export_id}").content
    )
    assert len(rows) == 5
    assert sum(Decimal(cells[17]) for cells in rows) == Decimal("345.00")
    assert sum(int(cells[13]) for cells in rows) == 8  # line counts sum to items


def test_other_data_filters(client: TestClient) -> None:
    session_id = ready_session(client)

    def order_ids(filters: dict[str, str]) -> list[str]:
        export_id = post_export(client, session_id, "orders", filters).json()["data"][
            "exportId"
        ]
        _, rows = parse_csv(
            client.get(f"/api/v1/sessions/{session_id}/exports/{export_id}").content
        )
        return sorted(cells[0] for cells in rows)

    assert order_ids({"market": "M2"}) == ["M-ORD-B", "M-ORD-F"]
    assert order_ids({"shipping_mode": "SAME_DAY"}) == ["M-ORD-B", "M-ORD-F"]
    assert order_ids({"order_status": "CANCELED"}) == ["M-ORD-C"]
    assert order_ids({"shipment_outcome": "LATE"}) == ["M-ORD-F"]
    assert order_ids({"from": "2021-03-12", "to": "2021-03-16"}) == [
        "M-ORD-A",
        "M-ORD-B",
        "M-ORD-X",
    ]
    assert order_ids({"region": "R9"}) == []


# ---------------------------------------------------------------------------
# Serialization: BOM, injection, typed values
# ---------------------------------------------------------------------------


def test_csv_injection_text_only(client: TestClient) -> None:
    session_id = ready_session(client)
    export_id = post_export(client, session_id, "cleaned_items").json()["data"][
        "exportId"
    ]
    _, rows = parse_csv(
        client.get(f"/api/v1/sessions/{session_id}/exports/{export_id}").content
    )
    by_item = {cells[2]: cells for cells in rows}
    # String cells with formula/DDE forms are neutralized as text.
    assert by_item["M-ITM-A3"][29] == "'=SUM(A1:A2)"
    assert by_item["M-ITM-X2"][29] == "'cmd|/c calc"
    # Typed negatives stay directly computable (no quote prefix).
    assert Decimal(by_item["M-ITM-A2"][12]) == Decimal("-4.00")
    assert Decimal(by_item["M-ITM-B1"][12]) == Decimal("-50.00")
    assert not by_item["M-ITM-A2"][12].startswith("'")
    # Ordinary labels pass through untouched.
    assert by_item["M-ITM-A1"][29] == "Widget A1"


def test_csv_money_two_dp(client: TestClient) -> None:
    session_id = ready_session(client)
    export_id = post_export(client, session_id, "orders").json()["data"]["exportId"]
    _, rows = parse_csv(
        client.get(f"/api/v1/sessions/{session_id}/exports/{export_id}").content
    )
    for cells in rows:
        for position in (15, 16, 17, 18):
            assert re.fullmatch(r"-?\d+\.\d{2}", cells[position]), cells


# ---------------------------------------------------------------------------
# Privacy gate
# ---------------------------------------------------------------------------


BANNED_PROBES = [
    "customer_first_name",
    "customer_last_name",
    "customer_street",
    "customer_email",
    "customer_password",
    "customer_latitude",
    "customer_longitude",
    "destination_postal_code",
    "ip_address",
    "mystery_unknown_column",
    "Sales",
]


def test_privacy_gate_blocks_banned_classes() -> None:
    for kind in ("cleaned_items", "orders"):
        for banned in BANNED_PROBES:
            hits = export_module.run_privacy_gate(
                kind, [*export_module.KIND_ALLOWLIST[kind], banned]
            )
            assert hits == [banned], (kind, banned)


def test_privacy_gate_blocks_export_end_to_end(
    client: TestClient, session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = ready_session(client)
    poisoned = dict(export_module.KIND_ALLOWLIST)
    poisoned["cleaned_items"] = export_module.CLEANED_ITEMS_COLUMNS + (
        "customer_email",
    )
    monkeypatch.setattr(export_module, "KIND_ALLOWLIST", poisoned)
    response = post_export(client, session_id, "cleaned_items")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EXPORT_BLOCKED"
    exports_dir = os.path.join(session_root, session_id, "exports")
    leftovers = [
        name for name in os.listdir(exports_dir) if name.endswith(".record.json")
    ]
    assert leftovers == []


def test_safe_ids_remain_exportable(client: TestClient) -> None:
    session_id = ready_session(client)
    export_id = post_export(client, session_id, "cleaned_items").json()["data"][
        "exportId"
    ]
    _, rows = parse_csv(
        client.get(f"/api/v1/sessions/{session_id}/exports/{export_id}").content
    )
    assert {cells[4] for cells in rows} >= {"SYN-CUST-A", "SYN-CUST-X"}


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def test_quality_report_whole_session(client: TestClient) -> None:
    session_id = ready_session(client)
    response = post_export(client, session_id, "quality_report")
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["metadata"] is None
    assert response.json()["meta"]["filters"] == {}
    download = client.get(f"/api/v1/sessions/{session_id}/exports/{data['exportId']}")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/json")
    payload = json.loads(download.content)
    assert set(payload["provenance"]) == PROVENANCE_KEYS
    assert payload["provenance"]["filtersApplied"] == {}
    assert payload["provenance"]["exportKind"] == "quality_report"
    assert payload["provenance"]["dataProvenance"] == "report"
    assert payload["profile"]["rows"] == 8
    assert payload["profile"]["grain"]
    for issue in payload["dataQuality"]["issues"]:
        assert set(issue) >= {
            "ruleId",
            "severity",
            "count",
            "treatment",
            "blockedStage",
        }
    assert payload["schema"]["sourceColumns"]
    assert payload["schema"]["mapping"]
    text = download.content.decode("utf-8")
    for forbidden in ("raw.csv", ".tmp/", "password", "upload part", "EXPORT_BYTES"):
        assert forbidden not in text
    assert hashlib.sha256(download.content).hexdigest() == data["sha256"]


def test_cleaning_report_audit_shape(client: TestClient) -> None:
    session_id = ready_session(client)
    response = post_export(client, session_id, "cleaning_report")
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    download = client.get(f"/api/v1/sessions/{session_id}/exports/{data['exportId']}")
    payload = json.loads(download.content)
    assert set(payload["provenance"]) == PROVENANCE_KEYS
    assert payload["provenance"]["filtersApplied"] == {}
    assert payload["steps"]
    for step in payload["steps"]:
        assert set(step) >= {
            "ruleId",
            "field",
            "detected",
            "fixed",
            "flagged",
            "excluded",
            "unchanged",
            "reason",
        }
        assert step["detected"] == (
            step["fixed"] + step["flagged"] + step["excluded"] + step["unchanged"]
        )
    assert payload["totals"]
    assert payload["reconciliation"]["netPre"] == payload["reconciliation"]["netPost"]
    text = download.content.decode("utf-8")
    for forbidden in ("raw.csv", ".tmp/", "password"):
        assert forbidden not in text


def test_report_metadata_get_is_not_found(client: TestClient) -> None:
    session_id = ready_session(client)
    export_id = post_export(client, session_id, "quality_report").json()["data"][
        "exportId"
    ]
    response = client.get(f"/api/v1/sessions/{session_id}/exports/{export_id}/metadata")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EXPORT_NOT_FOUND"


# ---------------------------------------------------------------------------
# Provenance, filenames, identity
# ---------------------------------------------------------------------------


def test_provenance_and_sidecar(client: TestClient) -> None:
    session_id = ready_session(client)
    response = post_export(client, session_id, "cleaned_items", {"category": "Alpha"})
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert response.json()["meta"]["filters"] == {"category": "Alpha"}
    assert re.fullmatch(
        r"[A-Za-z0-9\-_]{1,40}_cleaned_items_app0\.1\.0_schema1_\d{8}T\d{6}\.csv",
        data["filename"],
    )
    assert data["metadata"] is not None
    assert data["metadata"]["filename"].endswith(".meta.json")
    meta_response = client.get(
        f"/api/v1/sessions/{session_id}/exports/{data['exportId']}/metadata"
    )
    assert meta_response.status_code == 200
    assert meta_response.headers["content-type"].startswith("application/json")
    sidecar = json.loads(meta_response.content)
    assert set(sidecar) == PROVENANCE_KEYS
    assert sidecar["filtersApplied"] == {"category": "Alpha"}
    assert sidecar["exportKind"] == "cleaned_items"
    assert sidecar["dataProvenance"] == "cleaned"
    assert sidecar["sessionId"] == session_id
    assert sidecar["currencyNote"] == "currency unspecified — numeric units only"
    assert "raw.csv" not in json.dumps(sidecar)
    assert (
        hashlib.sha256(meta_response.content).hexdigest() == data["metadata"]["sha256"]
    )
    assert data["metadata"]["bytes"] == len(meta_response.content)
    assert meta_response.headers["content-disposition"] == (
        f'attachment; filename="{data["metadata"]["filename"]}"'
    )


def test_filters_applied_key_order_deterministic(client: TestClient) -> None:
    session_id = ready_session(client)
    response = post_export(
        client,
        session_id,
        "orders",
        {"shipment_outcome": "LATE", "market": "M2", "from": "2021-03-01"},
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    sidecar_filters = json.loads(
        client.get(
            f"/api/v1/sessions/{session_id}/exports/{data['exportId']}/metadata"
        ).content
    )["filtersApplied"]
    assert list(sidecar_filters) == ["from", "market", "shipment_outcome"]
    assert sidecar_filters == {
        "from": "2021-03-01",
        "market": "M2",
        "shipment_outcome": "LATE",
    }


def test_hostile_source_filename_sanitized(client: TestClient) -> None:
    session_id = upload_ok(client, EXPORT_BYTES, name="../../tricky?.csv")
    state = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert state["state"] == "READY"
    data = post_export(client, session_id, "orders").json()["data"]
    stem = data["filename"].split("_orders_")[0]
    assert stem
    assert re.fullmatch(r"[A-Za-z0-9\-_]{1,40}", stem)
    assert ".." not in data["filename"] and "/" not in data["filename"]


def test_unknown_export_id_rejected(client: TestClient) -> None:
    session_id = ready_session(client)
    # Single-segment unknown IDs reach the handler (multi-segment paths
    # never match the route and get the framework 404 instead).
    for bad in ("0" * 32, "not-hex"):
        for url in (
            f"/api/v1/sessions/{session_id}/exports/{bad}",
            f"/api/v1/sessions/{session_id}/exports/{bad}/metadata",
        ):
            response = client.get(url)
            assert response.status_code == 404, (bad, url)
            assert response.json()["error"]["code"] == "EXPORT_NOT_FOUND"


# ---------------------------------------------------------------------------
# Integrity, lifecycle, failure recovery
# ---------------------------------------------------------------------------


def test_tampered_artifact_not_served(client: TestClient, session_root: str) -> None:
    session_id = ready_session(client)
    export_id = post_export(client, session_id, "orders").json()["data"]["exportId"]
    primary = os.path.join(session_root, session_id, "exports", export_id + ".primary")
    with open(primary, "wb") as handle:
        handle.write(b"tampered")
    response = client.get(f"/api/v1/sessions/{session_id}/exports/{export_id}")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_STAGE_ERROR"


def test_reset_removes_exports(client: TestClient) -> None:
    session_id = ready_session(client)
    export_id = post_export(client, session_id, "orders").json()["data"]["exportId"]
    assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 200
    response = client.get(f"/api/v1/sessions/{session_id}/exports/{export_id}")
    assert response.status_code == 404


def test_partial_publication_leaves_no_record(
    client: TestClient, session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = ready_session(client)
    calls = {"count": 0}
    original = export_module._write_atomic_bytes

    def failing(path: str, content: bytes) -> None:
        calls["count"] += 1
        if calls["count"] >= 2:
            raise OSError("injected publication failure")
        original(path, content)

    monkeypatch.setattr(export_module, "_write_atomic_bytes", failing)
    response = post_export(client, session_id, "cleaned_items")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_STAGE_ERROR"
    exports_dir = os.path.join(session_root, session_id, "exports")
    leftovers = (
        [name for name in os.listdir(exports_dir) if name.endswith(".record.json")]
        if os.path.isdir(exports_dir)
        else []
    )
    assert leftovers == []


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def test_same_session_primary_deterministic(client: TestClient) -> None:
    session_id = ready_session(client)
    first = post_export(client, session_id, "cleaned_items", {"market": "M1"}).json()[
        "data"
    ]
    second = post_export(client, session_id, "cleaned_items", {"market": "M1"}).json()[
        "data"
    ]
    assert first["exportId"] != second["exportId"]
    one = client.get(f"/api/v1/sessions/{session_id}/exports/{first['exportId']}")
    two = client.get(f"/api/v1/sessions/{session_id}/exports/{second['exportId']}")
    assert one.content == two.content
    meta_one = json.loads(
        client.get(
            f"/api/v1/sessions/{session_id}/exports/{first['exportId']}/metadata"
        ).content
    )
    meta_two = json.loads(
        client.get(
            f"/api/v1/sessions/{session_id}/exports/{second['exportId']}/metadata"
        ).content
    )
    assert meta_one["filtersApplied"] == meta_two["filtersApplied"] == {"market": "M1"}


def test_same_session_report_semantic_reproducibility(client: TestClient) -> None:
    session_id = ready_session(client)
    first_id = post_export(client, session_id, "cleaning_report").json()["data"][
        "exportId"
    ]
    second_id = post_export(client, session_id, "cleaning_report").json()["data"][
        "exportId"
    ]
    one = json.loads(
        client.get(f"/api/v1/sessions/{session_id}/exports/{first_id}").content
    )
    two = json.loads(
        client.get(f"/api/v1/sessions/{session_id}/exports/{second_id}").content
    )
    one["provenance"].pop("generatedAt")
    two["provenance"].pop("generatedAt")
    assert one == two


def test_cross_session_primary_equivalent(client: TestClient) -> None:
    first_session = ready_session(client)
    second_session = ready_session(client)
    assert first_session != second_session
    first = post_export(client, first_session, "orders", {"market": "M2"}).json()[
        "data"
    ]
    second = post_export(client, second_session, "orders", {"market": "M2"}).json()[
        "data"
    ]
    one = client.get(f"/api/v1/sessions/{first_session}/exports/{first['exportId']}")
    two = client.get(f"/api/v1/sessions/{second_session}/exports/{second['exportId']}")
    assert one.content == two.content
    assert first["sha256"] == second["sha256"]
