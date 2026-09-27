"""Reference-confirmed enum mapping tests (synthetic values only).

ADR-038 clarification (2026-09-27): `Second Class`/`First Class`/`Corporate`
are governed source spellings mapping to the existing canonical
`SECOND_CLASS`/`FIRST_CLASS`/`CORPORATE`. `PENDING_PAYMENT` stays unknown.
No reference bytes, no PII.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.canonicalization import (
    CUSTOMER_SEGMENT_MAP,
    ORDER_STATUS_MAP,
    SHIPPING_MODE_MAP,
    map_enum,
)
from app.config import settings
from app.main import app
from app.profile_checks import (
    CUSTOMER_SEGMENT_VALUES,
    SHIPPING_MODE_VALUES,
    parse_timestamps,
)

HEADER = (
    "Order Id,Order Item Id,Customer Id,Product Card Id,"
    "Product Category Id,order date (DateOrders),shipping date (DateOrders),"
    "Sales,Order Item Discount,Order Item Total,Benefit per order,"
    "Order Item Product Price,Order Item Quantity,"
    "Days for shipping (real),Days for shipment (scheduled),"
    "Delivery Status,Order Status,Shipping Mode,Customer Segment"
)

BASE = {
    "order date (DateOrders)": "03-15-2021 10:00",
    "shipping date (DateOrders)": "03-18-2021 09:00",
    "Sales": "100.00",
    "Order Item Discount": "10.00",
    "Order Item Total": "90.00",
    "Benefit per order": "9.00",
    "Order Item Product Price": "50.00",
    "Order Item Quantity": "2",
    "Days for shipping (real)": "3",
    "Days for shipment (scheduled)": "2",
    "Delivery Status": "Shipped",
    "Order Status": "COMPLETE",
}

COLUMNS = HEADER.split(",")


def line(order: str, item: str, customer: str, mode: str, segment: str) -> str:
    values = dict(BASE)
    values.update(
        {
            "Order Id": order,
            "Order Item Id": item,
            "Customer Id": customer,
            "Product Card Id": "SYN-PROD-01",
            "Product Category Id": "SYN-CAT-01",
            "Shipping Mode": mode,
            "Customer Segment": segment,
        }
    )
    return ",".join(values[name] for name in COLUMNS)


def four_mode_csv() -> bytes:
    rows = [
        line("SYN-O-01", "SYN-I-01", "SYN-C-01", "Standard Class", "Consumer"),
        line("SYN-O-02", "SYN-I-02", "SYN-C-02", "Second Class", "Corporate"),
        line("SYN-O-03", "SYN-I-03", "SYN-C-03", "First Class", "Home Office"),
        line("SYN-O-04", "SYN-I-04", "SYN-C-04", "Same Day", "Consumer"),
    ]
    return (HEADER + "\n" + "\n".join(rows) + "\n").encode()


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
    return response.json()["data"]["sessionId"]


def quality(client: TestClient, session_id: str) -> dict:
    response = client.get(f"/api/v1/sessions/{session_id}/data-quality")
    assert response.status_code == 200
    return {issue["ruleId"]: issue for issue in response.json()["data"]["issues"]}


def test_reference_confirmed_spellings_are_recognized() -> None:
    assert SHIPPING_MODE_VALUES == {
        "Standard Class",
        "Second Class",
        "First Class",
        "Same Day",
    }
    assert CUSTOMER_SEGMENT_VALUES == {"Consumer", "Corporate", "Home Office"}
    assert SHIPPING_MODE_MAP["Second Class"] == "SECOND_CLASS"
    assert SHIPPING_MODE_MAP["First Class"] == "FIRST_CLASS"
    assert CUSTOMER_SEGMENT_MAP["Corporate"] == "CORPORATE"
    # Existing mappings retained.
    assert SHIPPING_MODE_MAP["Standard Class"] == "STANDARD_CLASS"
    assert SHIPPING_MODE_MAP["Same Day"] == "SAME_DAY"
    assert CUSTOMER_SEGMENT_MAP["Consumer"] == "CONSUMER"
    assert CUSTOMER_SEGMENT_MAP["Home Office"] == "HOME_OFFICE"


def test_map_enum_exact_with_unknown_sentinel() -> None:
    import pandas as pd

    modes = pd.Series(
        pd.array(
            ["Second Class", "First Class", "Standard Class", "Rocket"],
            dtype="string[pyarrow]",
        )
    )
    assert map_enum(modes.str.strip(), SHIPPING_MODE_MAP) == [
        "SECOND_CLASS",
        "FIRST_CLASS",
        "STANDARD_CLASS",
        "UNKNOWN_FLAGGED",
    ]
    assert "PENDING_PAYMENT" not in ORDER_STATUS_MAP


def test_governed_modes_and_segments_trigger_no_cat_warning(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, four_mode_csv())
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "READY"
    )
    rules = quality(client, session_id)
    assert "DQ-CAT-002" not in rules
    assert "DQ-CAT-003" not in rules
    assert "DQ-CAT-001" not in rules


def test_genuinely_unknown_values_still_flagged(
    client: TestClient, session_root: str
) -> None:
    rows = [
        line("SYN-O-11", "SYN-I-11", "SYN-C-11", "Rocket", "Platinum"),
    ]
    text = HEADER + "\n" + "\n".join(rows) + "\n"
    session_id = upload_ok(client, text.encode())
    rules = quality(client, session_id)
    assert rules["DQ-CAT-002"]["count"] == 1
    assert rules["DQ-CAT-003"]["count"] == 1


def test_pending_payment_still_unknown(client: TestClient, session_root: str) -> None:
    values = dict(BASE)
    values.update(
        {
            "Order Id": "SYN-O-21",
            "Order Item Id": "SYN-I-21",
            "Customer Id": "SYN-C-21",
            "Product Card Id": "SYN-PROD-01",
            "Product Category Id": "SYN-CAT-01",
            "Shipping Mode": "Standard Class",
            "Customer Segment": "Consumer",
            "Order Status": "PENDING_PAYMENT",
        }
    )
    text = HEADER + "\n" + ",".join(values[name] for name in COLUMNS) + "\n"
    session_id = upload_ok(client, text.encode())
    rules = quality(client, session_id)
    assert rules["DQ-CAT-001"]["count"] == 1


def test_delivery_grouping_includes_all_four_modes(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, four_mode_csv())
    response = client.get(
        f"/api/v1/sessions/{session_id}/kpis/delivery?by=shipping_mode"
    )
    assert response.status_code == 200
    groups = {g["key"]: g for g in response.json()["data"]["groups"]}
    assert set(groups) == {
        "STANDARD_CLASS",
        "SECOND_CLASS",
        "FIRST_CLASS",
        "SAME_DAY",
    }
    assert response.json()["data"]["eligibleOrders"] == 4
    for group in groups.values():
        by_id = {entry["id"]: entry for entry in group["kpis"]}
        assert by_id["kpi.ship.late_count"]["denominator"] == 1


def test_commercial_grouping_includes_corporate(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, four_mode_csv())
    response = client.get(
        f"/api/v1/sessions/{session_id}/kpis/commercial?by=customer_segment"
    )
    assert response.status_code == 200
    groups = {g["key"]: g for g in response.json()["data"]["groups"]}
    assert set(groups) == {"CONSUMER", "CORPORATE", "HOME_OFFICE"}


def test_backend_filter_accepts_new_modes(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, four_mode_csv())
    for token, order in (("SECOND_CLASS", "SYN-O-02"), ("FIRST_CLASS", "SYN-O-03")):
        response = client.get(
            f"/api/v1/sessions/{session_id}/orders?shipping_mode={token}"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["page"]["total"] == 1
        assert data["rows"][0]["order_id"] == order
        assert data["rows"][0]["shipping_mode"] == token
    # Unknown token still rejected.
    bad = client.get(f"/api/v1/sessions/{session_id}/orders?shipping_mode=BOGUS")
    assert bad.status_code == 422


def test_export_vocabularies_derive_new_modes() -> None:
    from app.exports import _enum_sets

    assert _enum_sets()["shipping_mode"] >= {
        "STANDARD_CLASS",
        "SECOND_CLASS",
        "FIRST_CLASS",
        "SAME_DAY",
    }
    assert "CORPORATE" in _enum_sets()["customer_segment"]


def test_shared_parser_still_single_contract() -> None:
    import app.canonicalization as canonicalization
    import app.profiling as profiling

    assert profiling.parse_timestamps is parse_timestamps
    assert canonicalization.parse_timestamps is parse_timestamps
