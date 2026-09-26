"""Phase-15A backend query-surface tests (synthetic data only).

Covers the two ADR-038 reads: `GET .../filter-options` (session-wide
facet domains) and `GET .../orders` (bounded paginated sanitized
one-row-per-order drilldown). The fixture holds a synthetic
multi-merchandise order so the governed facet/drilldown asymmetry is
frozen as EXPECTED behavior — never as sum reconciliation.

No DataCo rows are used; every expectation recomputes from the fixture.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.sessions as session_store
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
    "Customer Id": "SYN-CUST-DX",
    "order date (DateOrders)": "03-15-2021 10:00",
    "shipping date (DateOrders)": "03-18-2021 09:00",
    "Sales": "100.00",
    "Order Item Discount": "0.00",
    "Benefit per order": "5.00",
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
        # O-ORD-A: two single-category Alpha lines (one negative line profit).
        row(
            **{
                "Order Id": "O-ORD-A",
                "Order Item Id": "O-ITM-A1",
                "Customer Id": "SYN-CUST-A",
                "Product Card Id": "PROD-PA1",
                "Product Category Id": "CAT-A",
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
                "Order Id": "O-ORD-A",
                "Order Item Id": "O-ITM-A2",
                "Customer Id": "SYN-CUST-A",
                "Product Card Id": "PROD-PA2",
                "Product Category Id": "CAT-A",
                "Order Item Total": "45.00",
                "Benefit per order": "-4.00",
                "Order Item Quantity": "1",
                "Days for shipping (real)": "3",
                "Days for shipment (scheduled)": "5",
                "Category Name": "Alpha",
                "Product Name": "Widget A2",
            }
        ),
        # O-ORD-X: multi-merchandise (Alpha + Beta) → null order category.
        row(
            **{
                "Order Id": "O-ORD-X",
                "Order Item Id": "O-ITM-X1",
                "Customer Id": "SYN-CUST-X",
                "Product Card Id": "PROD-PX1",
                "Product Category Id": "CAT-A",
                "order date (DateOrders)": "03-16-2021 11:00",
                "Order Item Total": "10.00",
                "Benefit per order": "1.00",
                "Category Name": "Alpha",
                "Product Name": "Widget X1",
            }
        ),
        row(
            **{
                "Order Id": "O-ORD-X",
                "Order Item Id": "O-ITM-X2",
                "Customer Id": "SYN-CUST-X",
                "Product Card Id": "PROD-PX2",
                "Product Category Id": "CAT-B",
                "order date (DateOrders)": "03-16-2021 11:00",
                "Order Item Total": "20.00",
                "Benefit per order": "2.00",
                "Order Item Quantity": "3",
                "Category Name": "Beta",
                "Product Name": "Widget X2",
            }
        ),
        # O-ORD-B: single Beta, ties O-ORD-X's timestamp (tie-break check).
        row(
            **{
                "Order Id": "O-ORD-B",
                "Order Item Id": "O-ITM-B1",
                "Customer Id": "SYN-CUST-B",
                "Product Card Id": "PROD-PB1",
                "Product Category Id": "CAT-B",
                "order date (DateOrders)": "03-16-2021 11:00",
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
        # O-ORD-C: shipping-cancelled strict CANCELED order.
        row(
            **{
                "Order Id": "O-ORD-C",
                "Order Item Id": "O-ITM-C1",
                "Customer Id": "SYN-CUST-C",
                "Product Card Id": "PROD-PC1",
                "Product Category Id": "CAT-A",
                "order date (DateOrders)": "03-10-2021 09:00",
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
        # O-ORD-F: suspected-fraud late order (latest timestamp).
        row(
            **{
                "Order Id": "O-ORD-F",
                "Order Item Id": "O-ITM-F1",
                "Customer Id": "SYN-CUST-F",
                "Product Card Id": "PROD-PF1",
                "Product Category Id": "CAT-G",
                "order date (DateOrders)": "03-20-2021 08:00",
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
        # O-ORD-U: unknown shipping mode + UNKNOWN-flagged category label.
        row(
            **{
                "Order Id": "O-ORD-U",
                "Order Item Id": "O-ITM-U1",
                "Customer Id": "SYN-CUST-U",
                "Product Card Id": "PROD-PU1",
                "Product Category Id": "CAT-U",
                "order date (DateOrders)": "03-11-2021 08:00",
                "Order Item Total": "5.00",
                "Order Region": "R2",
                "Market": "M2",
                "Shipping Mode": "Rocket",
                "Category Name": "UNKNOWN_FLAGGED",
                "Product Name": "Widget U1",
            }
        ),
        # O-ORD-E: empty category label → null order merch dim.
        row(
            **{
                "Order Id": "O-ORD-E",
                "Order Item Id": "O-ITM-E1",
                "Customer Id": "SYN-CUST-E",
                "Product Card Id": "PROD-PE1",
                "Product Category Id": "CAT-E",
                "order date (DateOrders)": "03-12-2021 08:00",
                "Order Item Total": "15.00",
                "Days for shipping (real)": "1",
                "Days for shipment (scheduled)": "3",
                "Category Name": "",
                "Product Name": "Widget E1",
            }
        ),
    ]
    return (HEADER + "\n" + "\n".join(rows) + "\n").encode()


DIAG_BYTES = fixture_csv()

EXPECTED_ORDER = [
    "O-ORD-F",  # 03-20 latest
    "O-ORD-B",  # 03-16 tie, id before X
    "O-ORD-X",  # 03-16 tie
    "O-ORD-A",  # 03-15
    "O-ORD-E",  # 03-12
    "O-ORD-U",  # 03-11
    "O-ORD-C",  # 03-10 earliest
]

ALLOWLIST = {
    "order_id",
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
}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", root)
    return root


def upload_ok(client: TestClient, content: bytes) -> str:
    response = client.post(
        "/api/v1/sessions/uploads",
        files={"file": ("data.csv", content, "text/csv")},
    )
    assert response.status_code == 202
    data: Any = response.json()["data"]
    return str(data["sessionId"])


def park_at_analyzing(session_root: str, content: bytes) -> str:
    """An ANALYZING session with canonical done, KPI analysis never run."""
    from app.canonicalization import ensure_canonicalized
    from app.cleaning import ensure_cleaned
    from app.profiling import ensure_profiled
    from app.schema_validation import ensure_schema_validated

    session_id = str(uuid.uuid4())
    paths = session_store.session_paths(session_root, session_id)
    os.makedirs(paths.derived)
    os.makedirs(paths.exports)
    with open(paths.raw, "wb") as handle:
        handle.write(content)
    now = session_store.utcnow_naive_iso()
    manifest = session_store.build_manifest(
        session_id=session_id,
        filename_safe="data.csv",
        size_bytes=len(content),
        sha256_hex=hashlib.sha256(content).hexdigest(),
        encoding="utf-8",
        now=now,
    )
    session_store.write_manifest(paths, manifest)
    validated = ensure_schema_validated(paths, manifest, now)
    assert validated.state == "PROFILING"
    profiled = ensure_profiled(paths, validated, now)
    assert profiled.state == "CLEANING"
    cleaned = ensure_cleaned(paths, profiled, now)
    assert cleaned.state == "CANONICALIZING"
    canonicalized = ensure_canonicalized(paths, cleaned, now)
    assert canonicalized.state == "ANALYZING"
    return session_id


def ready_session(client: TestClient) -> str:
    session_id = upload_ok(client, DIAG_BYTES)
    state = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert state["state"] == "READY"
    return session_id


def orders_page(client: TestClient, session_id: str, **params: str | int) -> Any:
    response = client.get(f"/api/v1/sessions/{session_id}/orders", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Filter-options matrix
# ---------------------------------------------------------------------------


def test_filter_options_success_shape(client: TestClient) -> None:
    session_id = ready_session(client)
    response = client.get(f"/api/v1/sessions/{session_id}/filter-options")
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    data = body["data"]
    assert set(data) == {"dateRange", "markets", "regions", "categories"}
    assert set(data["dateRange"]) == {"minOrderDate", "maxOrderDate"}
    assert body["meta"]["sessionId"] == session_id
    assert body["meta"]["sessionState"] == "READY"


def test_filter_options_date_extent(client: TestClient) -> None:
    session_id = ready_session(client)
    data = client.get(f"/api/v1/sessions/{session_id}/filter-options").json()["data"]
    assert data["dateRange"] == {
        "minOrderDate": "2021-03-10",
        "maxOrderDate": "2021-03-20",
    }


def test_filter_options_sorted_domains(client: TestClient) -> None:
    session_id = ready_session(client)
    data = client.get(f"/api/v1/sessions/{session_id}/filter-options").json()["data"]
    assert data["markets"] == ["M1", "M2"]
    assert data["regions"] == ["R1", "R2"]
    assert data["categories"] == ["Alpha", "Beta", "Gamma"]


def test_filter_options_excludes_null_empty_unknown(client: TestClient) -> None:
    """Empty labels collapse, literal UNKNOWN labels stay unselectable."""
    session_id = ready_session(client)
    data = client.get(f"/api/v1/sessions/{session_id}/filter-options").json()["data"]
    assert "" not in data["categories"]
    assert "UNKNOWN_FLAGGED" not in data["categories"]
    assert "" not in data["markets"] and "" not in data["regions"]


def test_filter_options_category_from_items_incl_multi_merch(
    client: TestClient,
) -> None:
    """Beta is discoverable although it also lives on multi-merch order X."""
    session_id = ready_session(client)
    data = client.get(f"/api/v1/sessions/{session_id}/filter-options").json()["data"]
    assert "Beta" in data["categories"]


def test_filter_options_non_cascading_and_stable(client: TestClient) -> None:
    first = client.get(
        f"/api/v1/sessions/{ready_session(client)}/filter-options"
    ).json()["data"]
    session_id = ready_session(client)
    # No filter params exist; a second read of the same session is identical.
    second = client.get(f"/api/v1/sessions/{session_id}/filter-options").json()["data"]
    third = client.get(f"/api/v1/sessions/{session_id}/filter-options").json()["data"]
    assert second == third
    assert first == second


def test_filter_options_privacy(client: TestClient) -> None:
    session_id = ready_session(client)
    text = client.get(f"/api/v1/sessions/{session_id}/filter-options").text
    for forbidden in (
        "customer_id",
        "SYN-CUST",
        "postal",
        "first_name",
        "last_name",
        "email",
        "password",
        "street",
        "First",
    ):
        assert forbidden not in text


def test_filter_options_lifecycle(client: TestClient, session_root: str) -> None:
    missing = str(uuid.uuid4())
    assert client.get(f"/api/v1/sessions/{missing}/filter-options").status_code == 404
    parked = park_at_analyzing(session_root, DIAG_BYTES)
    gated = client.get(f"/api/v1/sessions/{parked}/filter-options")
    assert gated.status_code == 409
    assert gated.json()["error"]["code"] == "NOT_READY"
    session_id = upload_ok(client, DIAG_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    manifest.lastAccessedAt = (
        (datetime.now() - timedelta(days=2)).replace(microsecond=0).isoformat()
    )
    session_store.write_manifest(paths, manifest)
    expired = client.get(f"/api/v1/sessions/{session_id}/filter-options")
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "SESSION_EXPIRED"


def test_filter_options_resurface_terminal_error(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sessions/uploads",
        files={"file": ("orders.csv", b"a,b\n1,2\n", "text/csv")},
    )
    session_id = response.json()["data"]["sessionId"]
    failed = client.get(f"/api/v1/sessions/{session_id}/filter-options")
    assert failed.status_code == 422
    assert failed.json()["error"]["code"] == "SCHEMA_MISSING_COLUMN"


# ---------------------------------------------------------------------------
# Orders: paging, ordering, traversal
# ---------------------------------------------------------------------------


def test_orders_first_page_default_limit(client: TestClient) -> None:
    session_id = ready_session(client)
    body = orders_page(client, session_id)
    assert body["error"] is None
    assert body["data"]["page"] == {"nextCursor": None, "total": 7}
    assert [row["order_id"] for row in body["data"]["rows"]] == EXPECTED_ORDER


def test_orders_custom_and_max_limit(client: TestClient) -> None:
    session_id = ready_session(client)
    body = orders_page(client, session_id, limit=3)
    assert [row["order_id"] for row in body["data"]["rows"]] == EXPECTED_ORDER[:3]
    assert body["data"]["page"]["total"] == 7
    assert body["data"]["page"]["nextCursor"] is not None
    capped = orders_page(client, session_id, limit=200)
    assert capped["data"]["page"] == {"nextCursor": None, "total": 7}
    assert len(capped["data"]["rows"]) == 7


def test_orders_invalid_limits(client: TestClient) -> None:
    session_id = ready_session(client)
    for bad in (0, -1, 201, 1000):
        response = client.get(
            f"/api/v1/sessions/{session_id}/orders", params={"limit": bad}
        )
        assert response.status_code == 422, bad
        assert response.json()["error"]["code"] == "INVALID_PAGINATION"
    non_integer = client.get(
        f"/api/v1/sessions/{session_id}/orders", params={"limit": "many"}
    )
    assert non_integer.status_code == 422


def test_orders_traversal_no_duplicate_no_skip(client: TestClient) -> None:
    session_id = ready_session(client)
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        body = orders_page(client, session_id, **params)
        rows = body["data"]["rows"]
        assert len(rows) <= 2
        seen.extend(row["order_id"] for row in rows)
        cursor = body["data"]["page"]["nextCursor"]
        pages += 1
        assert pages <= 10
        if cursor is None:
            assert body["data"]["page"]["total"] == 7
            break
    assert seen == EXPECTED_ORDER
    assert len(set(seen)) == len(seen) == 7


def test_orders_malformed_cursor(client: TestClient) -> None:
    session_id = ready_session(client)
    for bad in ("not-a-cursor", "eyJ2IjogOTk5fQ==", "", "!!!"):
        response = client.get(
            f"/api/v1/sessions/{session_id}/orders", params={"cursor": bad}
        )
        assert response.status_code == 422, bad
        assert response.json()["error"]["code"] == "INVALID_PAGINATION"


def test_orders_cursor_filter_mismatch(client: TestClient) -> None:
    session_id = ready_session(client)
    first = orders_page(client, session_id, limit=1, category="Alpha")
    cursor = first["data"]["page"]["nextCursor"]
    assert cursor is not None
    response = client.get(
        f"/api/v1/sessions/{session_id}/orders",
        params={"limit": 1, "cursor": cursor, "category": "Beta"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PAGINATION"


def test_orders_total_is_pre_pagination(client: TestClient) -> None:
    session_id = ready_session(client)
    body = orders_page(client, session_id, limit=2, market="M1")
    assert body["data"]["page"]["total"] == 4
    assert len(body["data"]["rows"]) == 2


def test_orders_empty_result(client: TestClient) -> None:
    session_id = ready_session(client)
    body = orders_page(client, session_id, category="NoSuchCategory")
    assert body["data"] == {"rows": [], "page": {"nextCursor": None, "total": 0}}
    assert body["meta"]["filters"] == {"category": "NoSuchCategory"}


# ---------------------------------------------------------------------------
# Orders: filters
# ---------------------------------------------------------------------------


def test_orders_date_filter(client: TestClient) -> None:
    session_id = ready_session(client)
    body = orders_page(client, session_id, **{"from": "2021-03-16"})
    assert [row["order_id"] for row in body["data"]["rows"]] == [
        "O-ORD-F",
        "O-ORD-B",
        "O-ORD-X",
    ]
    bounded = orders_page(
        client, session_id, **{"from": "2021-03-11", "to": "2021-03-15"}
    )
    assert [row["order_id"] for row in bounded["data"]["rows"]] == [
        "O-ORD-A",
        "O-ORD-E",
        "O-ORD-U",
    ]


def test_orders_market_region_filters(client: TestClient) -> None:
    session_id = ready_session(client)
    markets = orders_page(client, session_id, market="M2")
    assert [row["order_id"] for row in markets["data"]["rows"]] == [
        "O-ORD-F",
        "O-ORD-B",
        "O-ORD-U",
    ]
    regions = orders_page(client, session_id, region="R1")
    assert [row["order_id"] for row in regions["data"]["rows"]] == [
        "O-ORD-X",
        "O-ORD-A",
        "O-ORD-E",
        "O-ORD-C",
    ]


def test_orders_category_filter_order_frame(client: TestClient) -> None:
    session_id = ready_session(client)
    body = orders_page(client, session_id, category="Alpha")
    assert [row["order_id"] for row in body["data"]["rows"]] == ["O-ORD-A", "O-ORD-C"]


def test_orders_multi_merch_category_exclusion(client: TestClient) -> None:
    """Order X (Alpha+Beta, null order category) never matches category=A."""
    session_id = ready_session(client)
    for category in ("Alpha", "Beta"):
        body = orders_page(client, session_id, category=category)
        assert "O-ORD-X" not in [row["order_id"] for row in body["data"]["rows"]]


def test_orders_shipping_mode_subset(client: TestClient) -> None:
    """Only the mapped V1 subset is selectable; the rest is rejected."""
    session_id = ready_session(client)
    standard = orders_page(client, session_id, shipping_mode="STANDARD_CLASS")
    assert [row["order_id"] for row in standard["data"]["rows"]] == [
        "O-ORD-X",
        "O-ORD-A",
        "O-ORD-E",
        "O-ORD-C",
    ]
    same_day = orders_page(client, session_id, shipping_mode="SAME_DAY")
    assert [row["order_id"] for row in same_day["data"]["rows"]] == [
        "O-ORD-F",
        "O-ORD-B",
    ]
    rejected = client.get(
        f"/api/v1/sessions/{session_id}/orders",
        params={"shipping_mode": "SECOND_CLASS"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "INVALID_FILTER_VALUE"
    unknown = orders_page(client, session_id, shipping_mode="UNKNOWN_FLAGGED")
    assert [row["order_id"] for row in unknown["data"]["rows"]] == ["O-ORD-U"]


def test_orders_status_and_outcome_filters(client: TestClient) -> None:
    session_id = ready_session(client)
    canceled = orders_page(client, session_id, order_status="CANCELED")
    assert [row["order_id"] for row in canceled["data"]["rows"]] == ["O-ORD-C"]
    fraud = orders_page(client, session_id, order_status="SUSPECTED_FRAUD")
    assert [row["order_id"] for row in fraud["data"]["rows"]] == ["O-ORD-F"]
    late = orders_page(client, session_id, shipment_outcome="LATE")
    assert [row["order_id"] for row in late["data"]["rows"]] == ["O-ORD-F"]
    early = orders_page(client, session_id, shipment_outcome="EARLY")
    assert [row["order_id"] for row in early["data"]["rows"]] == [
        "O-ORD-B",
        "O-ORD-A",
        "O-ORD-E",
    ]
    exact = orders_page(client, session_id, shipment_outcome="ON_SCHEDULE")
    assert [row["order_id"] for row in exact["data"]["rows"]] == ["O-ORD-X", "O-ORD-U"]
    blocked = orders_page(client, session_id, shipment_outcome="SHIPPING_CANCELED")
    assert [row["order_id"] for row in blocked["data"]["rows"]] == ["O-ORD-C"]


def test_orders_invalid_filter_values(client: TestClient) -> None:
    session_id = ready_session(client)
    bad_enum = client.get(
        f"/api/v1/sessions/{session_id}/orders", params={"shipping_mode": "ROCKET"}
    )
    assert bad_enum.status_code == 422
    assert bad_enum.json()["error"]["code"] == "INVALID_FILTER_VALUE"
    bad_date = client.get(
        f"/api/v1/sessions/{session_id}/orders", params={"from": "not-a-date"}
    )
    assert bad_date.status_code == 422
    assert bad_date.json()["error"]["code"] == "INVALID_FILTER_VALUE"


# ---------------------------------------------------------------------------
# Orders: rows, serialization, commercial source
# ---------------------------------------------------------------------------


def test_orders_row_allowlist_exact(client: TestClient) -> None:
    session_id = ready_session(client)
    body = orders_page(client, session_id, limit=1)
    assert set(body["data"]["rows"][0]) == ALLOWLIST


def test_orders_one_row_per_order(client: TestClient) -> None:
    session_id = ready_session(client)
    body = orders_page(client, session_id)
    ids = [row["order_id"] for row in body["data"]["rows"]]
    assert len(ids) == len(set(ids)) == 7


def test_orders_stored_commercial_aggregates(client: TestClient) -> None:
    session_id = ready_session(client)
    body = orders_page(client, session_id)
    by_id = {row["order_id"]: row for row in body["data"]["rows"]}
    merged = by_id["O-ORD-A"]
    assert merged["line_count"] == 2
    assert merged["total_units"] == 3
    assert merged["net_value"] == "135.00"
    assert merged["profit_total"] == "5.00"
    assert merged["gross_value"] == "200.00"
    assert merged["discount_total"] == "0.00"
    multi = by_id["O-ORD-X"]
    assert multi["line_count"] == 2
    assert multi["total_units"] == 4
    assert multi["net_value"] == "30.00"


def test_orders_negative_profit_retained(client: TestClient) -> None:
    session_id = ready_session(client)
    body = orders_page(client, session_id)
    by_id = {row["order_id"]: row for row in body["data"]["rows"]}
    assert by_id["O-ORD-B"]["profit_total"] == "-50.00"
    assert by_id["O-ORD-B"]["net_value"] == "40.00"


def test_orders_cancelled_is_late_null(client: TestClient) -> None:
    session_id = ready_session(client)
    body = orders_page(client, session_id)
    by_id = {row["order_id"]: row for row in body["data"]["rows"]}
    cancelled = by_id["O-ORD-C"]
    assert cancelled["shipment_outcome"] == "SHIPPING_CANCELED"
    assert cancelled["is_late"] is None
    assert cancelled["actual_shipping_days"] is None
    assert cancelled["order_status"] == "CANCELED"
    assert by_id["O-ORD-F"]["order_status"] == "SUSPECTED_FRAUD"
    assert by_id["O-ORD-F"]["is_late"] is True
    assert by_id["O-ORD-A"]["is_late"] is False


def test_orders_serialization_types(client: TestClient) -> None:
    session_id = ready_session(client)
    body = orders_page(client, session_id)
    row = next(r for r in body["data"]["rows"] if r["order_id"] == "O-ORD-A")
    assert isinstance(row["order_id"], str)
    assert row["order_timestamp"] == "2021-03-15T10:00:00"
    assert isinstance(row["line_count"], int)
    assert isinstance(row["total_units"], int)
    assert isinstance(row["scheduled_shipping_days"], int)
    assert isinstance(row["actual_shipping_days"], int)
    for money in ("gross_value", "discount_total", "net_value", "profit_total"):
        assert isinstance(row[money], str)
        assert "." in row[money] and len(row[money].rsplit(".", 1)[1]) == 2


def test_orders_filter_meta_echo(client: TestClient) -> None:
    session_id = ready_session(client)
    plain = orders_page(client, session_id)
    assert plain["meta"]["filters"] == {}
    filtered = orders_page(
        client, session_id, market="M1", shipping_mode="STANDARD_CLASS"
    )
    assert filtered["meta"]["filters"] == {
        "market": "M1",
        "shipping_mode": "STANDARD_CLASS",
    }


def test_orders_privacy(client: TestClient) -> None:
    session_id = ready_session(client)
    text = client.get(f"/api/v1/sessions/{session_id}/orders").text
    for forbidden in (
        "customer_id",
        "SYN-CUST",
        "postal",
        "first_name",
        "last_name",
        "email",
        "password",
        "street",
        "Late_delivery_risk",
        "Delivery Status",
        "Category Name",
        "Department Name",
        "Product Name",
    ):
        assert forbidden not in text


# ---------------------------------------------------------------------------
# Reconciliation + asymmetry (governed expectations, not sum equality)
# ---------------------------------------------------------------------------


def test_orders_reconcile_with_order_grain_kpis_for_invariant_filter(
    client: TestClient,
) -> None:
    session_id = ready_session(client)
    drilldown = orders_page(client, session_id, market="M1")
    assert drilldown["data"]["page"]["total"] == 4
    overview = client.get(
        f"/api/v1/sessions/{session_id}/kpis/overview", params={"market": "M1"}
    ).json()["data"]
    by_id = {kpi["id"]: kpi for kpi in overview["kpis"]}
    assert by_id["kpi.orders.count"]["value"] == 4
    assert overview["totals"]["orders"] == 4
    assert by_id["kpi.orders.shipment_eligible_count"]["value"] == 3


def test_category_asymmetry_is_expected_not_reconciled(client: TestClient) -> None:
    """Item-grain headlines hold X's Alpha line; drilldown excludes X."""
    session_id = ready_session(client)
    overview = client.get(
        f"/api/v1/sessions/{session_id}/kpis/overview", params={"category": "Alpha"}
    ).json()["data"]
    by_id = {kpi["id"]: kpi for kpi in overview["kpis"]}
    assert by_id["kpi.value.net"]["value"] == "205.00"
    drilldown = orders_page(client, session_id, category="Alpha")
    assert [row["order_id"] for row in drilldown["data"]["rows"]] == [
        "O-ORD-A",
        "O-ORD-C",
    ]
    drilldown_net = sum(float(row["net_value"]) for row in drilldown["data"]["rows"])
    assert drilldown_net == 195.00
    assert by_id["kpi.value.net"]["value"] != f"{drilldown_net:.2f}"


def test_facet_drilldown_asymmetry_frozen(client: TestClient) -> None:
    """Beta is faceted from item facts; multi-merch X never drills down."""
    session_id = ready_session(client)
    facets = client.get(f"/api/v1/sessions/{session_id}/filter-options").json()["data"]
    assert "Beta" in facets["categories"]
    drilldown = orders_page(client, session_id, category="Beta")
    assert [row["order_id"] for row in drilldown["data"]["rows"]] == ["O-ORD-B"]


# ---------------------------------------------------------------------------
# Lifecycle parity with KPI serving
# ---------------------------------------------------------------------------


def test_orders_lifecycle(client: TestClient, session_root: str) -> None:
    missing = str(uuid.uuid4())
    assert client.get(f"/api/v1/sessions/{missing}/orders").status_code == 404
    parked = park_at_analyzing(session_root, DIAG_BYTES)
    gated = client.get(f"/api/v1/sessions/{parked}/orders")
    assert gated.status_code == 409
    assert gated.json()["error"]["code"] == "NOT_READY"
    session_id = upload_ok(client, DIAG_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    manifest.lastAccessedAt = (
        (datetime.now() - timedelta(days=2)).replace(microsecond=0).isoformat()
    )
    session_store.write_manifest(paths, manifest)
    expired = client.get(f"/api/v1/sessions/{session_id}/orders")
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "SESSION_EXPIRED"


def test_orders_resurface_terminal_error(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sessions/uploads",
        files={"file": ("orders.csv", b"a,b\n1,2\n", "text/csv")},
    )
    session_id = response.json()["data"]["sessionId"]
    failed = client.get(f"/api/v1/sessions/{session_id}/orders")
    assert failed.status_code == 422
    assert failed.json()["error"]["code"] == "SCHEMA_MISSING_COLUMN"


# ---------------------------------------------------------------------------
# Cursor filter-context binding: structured fingerprint regression
# ---------------------------------------------------------------------------


def collision_csv() -> bytes:
    """Punctuation-bearing open-domain values through the real pipeline.

    Context 1 (market="A, region=B", region="C") and context 2
    (market="A", region="B, region=C") render identically under the old
    human-readable `describe()` join ("market=A, region=B, region=C")
    but are distinct normalized populations.
    """
    cells = dict(BASE)
    cells.update(
        {
            "Customer Segment": "Consumer",
            "Order Country": "C-Land",
            "Department Name": "D1",
            "Category Name": "Kappa",
        }
    )

    def quoted(**overrides: str) -> str:
        values = dict(cells)
        values.update(overrides)
        parts = []
        for name in COLUMNS:
            cell = values[name]
            parts.append(f'"{cell}"' if "," in cell else cell)
        return ",".join(parts)

    rows = [
        quoted(
            **{
                "Order Id": "K-ORD-1",
                "Order Item Id": "K-ITM-1",
                "Customer Id": "SYN-CUST-K1",
                "Product Card Id": "PROD-PK1",
                "Product Category Id": "CAT-K",
                "order date (DateOrders)": "03-15-2021 10:00",
                "Order Item Total": "10.00",
                "Market": "A, region=B",
                "Order Region": "C",
                "Product Name": "Widget K1",
            }
        ),
        quoted(
            **{
                "Order Id": "K-ORD-2",
                "Order Item Id": "K-ITM-2",
                "Customer Id": "SYN-CUST-K2",
                "Product Card Id": "PROD-PK2",
                "Product Category Id": "CAT-K",
                "order date (DateOrders)": "03-16-2021 10:00",
                "Order Item Total": "20.00",
                "Market": "A, region=B",
                "Order Region": "C",
                "Product Name": "Widget K2",
            }
        ),
        quoted(
            **{
                "Order Id": "K-ORD-3",
                "Order Item Id": "K-ITM-3",
                "Customer Id": "SYN-CUST-K3",
                "Product Card Id": "PROD-PK3",
                "Product Category Id": "CAT-K",
                "order date (DateOrders)": "03-17-2021 10:00",
                "Order Item Total": "30.00",
                "Market": "A",
                "Order Region": "B, region=C",
                "Product Name": "Widget K3",
            }
        ),
    ]
    return (HEADER + "\n" + "\n".join(rows) + "\n").encode()


def collision_session(client: TestClient) -> str:
    session_id = upload_ok(client, collision_csv())
    state = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert state["state"] == "READY"
    return session_id


def test_cursor_collision_contexts_reject(client: TestClient) -> None:
    """Delimiter-colliding contexts must not share cursors (structured f)."""
    session_id = collision_session(client)
    context_one = {"market": "A, region=B", "region": "C"}
    context_two = {"market": "A", "region": "B, region=C"}
    # A. Context 1 matches two rows: a cursor is issued.
    first = client.get(
        f"/api/v1/sessions/{session_id}/orders",
        params={"limit": 1, **context_one},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert [row["order_id"] for row in body["data"]["rows"]] == ["K-ORD-2"]
    assert body["data"]["page"]["total"] == 2
    cursor = body["data"]["page"]["nextCursor"]
    assert cursor is not None
    # B. Same cursor + same context continues normally.
    same = client.get(
        f"/api/v1/sessions/{session_id}/orders",
        params={"limit": 1, "cursor": cursor, **context_one},
    )
    assert same.status_code == 200, same.text
    assert [row["order_id"] for row in same.json()["data"]["rows"]] == ["K-ORD-1"]
    # Context 2 is itself valid (rejection below is binding, not bad filter).
    other = client.get(f"/api/v1/sessions/{session_id}/orders", params=context_two)
    assert other.status_code == 200, other.text
    assert [row["order_id"] for row in other.json()["data"]["rows"]] == ["K-ORD-3"]
    # C/D/E. Cursor from context 1 + context 2 rejects cleanly.
    cross = client.get(
        f"/api/v1/sessions/{session_id}/orders",
        params={"limit": 1, "cursor": cursor, **context_two},
    )
    assert cross.status_code == 422
    cross_body = cross.json()
    assert cross_body["data"] is None
    assert cross_body["error"]["code"] == "INVALID_PAGINATION"


def test_cursor_accepts_normalized_spelling(client: TestClient) -> None:
    """Binding is to normalized values, not raw query spelling."""
    session_id = ready_session(client)
    first = orders_page(client, session_id, market=" M1 ", limit=1)
    assert [row["order_id"] for row in first["data"]["rows"]] == ["O-ORD-X"]
    cursor = first["data"]["page"]["nextCursor"]
    assert cursor is not None
    second = orders_page(client, session_id, market="M1", limit=1, cursor=cursor)
    assert [row["order_id"] for row in second["data"]["rows"]] == ["O-ORD-A"]


def test_orders_strict_version_cursor_rejected(client: TestClient) -> None:
    """Foreign `v=true` cursor fails the strict integer version check."""
    session_id = ready_session(client)
    foreign = base64.urlsafe_b64encode(
        json.dumps({"v": True, "ts": None, "oid": "O-ORD-A", "f": "anything"}).encode()
    ).decode()
    response = client.get(
        f"/api/v1/sessions/{session_id}/orders", params={"cursor": foreign}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PAGINATION"
