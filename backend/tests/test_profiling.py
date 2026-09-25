"""Phase-6 profiling engine tests (synthetic fixtures only, no DataCo rows).

Covers deterministic value-level detection: row counts, governed encoding,
mapped-column selection, string IDs, missing vs parse-failure semantics,
month-first dates, duplicate-key vs legitimate order repetition, negative
profit retention, the $0.05 reconciliation tolerance, shipping-day
authority, leakage-field isolation, unknown-extra quarantine, artifact
privacy, raw immutability, and determinism.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

import app.sessions as session_store
from app.config import settings
from app.main import app

CLEAN_BYTES = (Path(__file__).parent / "fixtures" / "profiling_clean.csv").read_bytes()
ISSUES_BYTES = (
    Path(__file__).parent / "fixtures" / "profiling_issues.csv"
).read_bytes()

REQUIRED_HEADER = (
    "Order Id,Order Item Id,Customer Id,Product Card Id,"
    "Product Category Id,order date (DateOrders),shipping date (DateOrders),"
    "Sales,Order Item Discount,Order Item Total,Benefit per order,"
    "Order Item Product Price,Order Item Quantity,"
    "Days for shipping (real),Days for shipment (scheduled),"
    "Delivery Status,Order Status,Shipping Mode"
)


def valid_row(**overrides: str) -> str:
    base = {
        "Order Id": "SYN-ORDER-9301",
        "Order Item Id": "SYN-ITEM-9301",
        "Customer Id": "SYN-CUST-931",
        "Product Card Id": "SYN-PROD-931",
        "Product Category Id": "SYN-CAT-931",
        "order date (DateOrders)": "03-15-2021 10:00",
        "shipping date (DateOrders)": "03-18-2021 09:00",
        "Sales": "29.98",
        "Order Item Discount": "2.00",
        "Order Item Total": "27.98",
        "Benefit per order": "6.40",
        "Order Item Product Price": "14.99",
        "Order Item Quantity": "2",
        "Days for shipping (real)": "3",
        "Days for shipment (scheduled)": "4",
        "Delivery Status": "Shipped",
        "Order Status": "COMPLETE",
        "Shipping Mode": "Standard Class",
    }
    base.update(overrides)
    ordered = [base[name] for name in REQUIRED_HEADER.split(",")]
    return ",".join(ordered)


def craft_csv(rows: list[str]) -> bytes:
    return ("\n".join([REQUIRED_HEADER, *rows]) + "\n").encode()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", root)
    return root


def post_csv(
    client: TestClient,
    filename: str,
    content: bytes,
    content_type: str = "text/csv",
) -> Response:
    return client.post(
        "/api/v1/sessions/uploads",
        files={"file": (filename, content, content_type)},
    )


def upload_ok(client: TestClient, content: bytes) -> str:
    response = post_csv(client, "data.csv", content)
    assert response.status_code == 202
    return response.json()["data"]["sessionId"]


def read_artifact(session_root: str, session_id: str) -> dict:
    paths = session_store.session_paths(session_root, session_id)
    with open(
        os.path.join(paths.derived, "profiling_report.json"), encoding="utf-8"
    ) as handle:
        return json.load(handle)


def test_clean_fixture_settles_at_ready_with_only_privacy_info(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CLEAN_BYTES)
    status = client.get(f"/api/v1/sessions/{session_id}/status")
    assert status.json()["data"]["state"] == "READY"
    quality = client.get(f"/api/v1/sessions/{session_id}/data-quality")
    assert quality.status_code == 200
    issues = quality.json()["data"]["issues"]
    assert {issue["ruleId"] for issue in issues} == {
        "DQ-PRIVACY-001",
        "DQ-PRIVACY-002",
    }


def test_profile_endpoint_returns_contract_shape(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CLEAN_BYTES)
    response = client.get(f"/api/v1/sessions/{session_id}/profile")
    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {
        "rows",
        "columns",
        "grain",
        "missingness",
        "cardinality",
        "duplicates",
        "invarianceConflicts",
        "productInvarianceConflicts",
        "customerInvarianceConflicts",
    }
    assert data["rows"] == 4
    assert data["columns"] == 25  # 18 required + 7 optional mapped fields
    assert data["grain"] == "order_item"
    assert set(data["duplicates"]) == {"exact", "keyDupes"}
    assert data["duplicates"] == {"exact": 0, "keyDupes": 0}
    for entry in data["missingness"]:
        assert set(entry) == {
            "field",
            "source",
            "missing",
            "total",
            "rate",
            "parseFailures",
        }
        assert entry["total"] == 4
    for entry in data["cardinality"]:
        assert set(entry) == {"field", "source", "distinct"}


def test_data_quality_endpoint_returns_contract_shape(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, ISSUES_BYTES)
    response = client.get(f"/api/v1/sessions/{session_id}/data-quality")
    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {"summary", "issues"}
    assert set(data["summary"]) == {
        "rulesEvaluated",
        "rulesTriggered",
        "errors",
        "warnings",
        "infos",
        "blockingIssues",
    }
    for issue in data["issues"]:
        assert set(issue) == {
            "ruleId",
            "severity",
            "count",
            "treatment",
            "blockedStage",
        }
    assert "fixed" not in {issue["treatment"] for issue in data["issues"]}


def test_raw_sha_unchanged_by_profiling(client: TestClient, session_root: str) -> None:
    session_id = upload_ok(client, ISSUES_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    with open(paths.raw, "rb") as handle:
        assert handle.read() == ISSUES_BYTES
    client.get(f"/api/v1/sessions/{session_id}/profile")
    client.get(f"/api/v1/sessions/{session_id}/data-quality")
    with open(paths.raw, "rb") as handle:
        after = handle.read()
    assert after == ISSUES_BYTES
    assert hashlib.sha256(after).hexdigest() == hashlib.sha256(ISSUES_BYTES).hexdigest()


def test_identifiers_stay_strings_and_count_distinctly(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CLEAN_BYTES)
    profile = client.get(f"/api/v1/sessions/{session_id}/profile").json()["data"]
    by_field = {entry["field"]: entry for entry in profile["cardinality"]}
    assert by_field["order_item_id"]["distinct"] == 4
    assert by_field["order_id"]["distinct"] == 4
    assert by_field["customer_id"]["distinct"] == 4


def test_missing_and_parse_failures_tracked_separately(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, ISSUES_BYTES)
    profile = client.get(f"/api/v1/sessions/{session_id}/profile").json()["data"]
    by_field = {entry["field"]: entry for entry in profile["missingness"]}
    # Row B leaves Customer Id empty: missing, never a parse failure.
    assert by_field["customer_id"]["missing"] == 1
    assert by_field["customer_id"]["parseFailures"] == 0
    # Row B writes "two" as quantity: present but unparseable.
    assert by_field["quantity_units"]["parseFailures"] == 1
    assert by_field["quantity_units"]["missing"] == 0
    # Row C carries a month-impossible order date: parse failure, not missing.
    assert by_field["order_timestamp"]["parseFailures"] == 1
    assert by_field["order_timestamp"]["missing"] == 1  # row B is empty


def test_month_first_date_semantics(client: TestClient, session_root: str) -> None:
    january = valid_row(**{"order date (DateOrders)": "01-13-2021 10:00"})
    session_id = upload_ok(client, craft_csv([january]))
    profile = client.get(f"/api/v1/sessions/{session_id}/profile").json()["data"]
    by_field = {entry["field"]: entry for entry in profile["missingness"]}
    assert by_field["order_timestamp"]["parseFailures"] == 0

    day_first = valid_row(**{"order date (DateOrders)": "13-01-2021 10:00"})
    other_id = upload_ok(client, craft_csv([day_first]))
    other = client.get(f"/api/v1/sessions/{other_id}/profile").json()["data"]
    by_other = {entry["field"]: entry for entry in other["missingness"]}
    assert by_other["order_timestamp"]["parseFailures"] == 1


def test_repeated_order_id_is_legitimate_but_dup_item_id_is_not(
    client: TestClient, session_root: str
) -> None:
    first = valid_row()
    second = valid_row(
        **{"Order Item Id": "SYN-ITEM-9302", "Product Card Id": "SYN-PROD-932"}
    )
    session_id = upload_ok(client, craft_csv([first, second]))
    status = client.get(f"/api/v1/sessions/{session_id}/status")
    assert status.json()["data"]["state"] == "READY"
    quality = client.get(f"/api/v1/sessions/{session_id}/data-quality").json()["data"]
    by_rule = {issue["ruleId"]: issue for issue in quality["issues"]}
    assert "DQ-KEY-001" not in by_rule
    assert by_rule["DQ-KEY-002"]["severity"] == "INFO"
    assert by_rule["DQ-KEY-002"]["blockedStage"] is None


def test_negative_profit_retained_and_only_extreme_ratio_flagged(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, ISSUES_BYTES)
    quality = client.get(f"/api/v1/sessions/{session_id}/data-quality").json()["data"]
    by_rule = {issue["ruleId"]: issue for issue in quality["issues"]}
    # Exactly one extreme row (profit -150 on net 100); the -5-on-100 row
    # stays valid and unflagged.
    assert by_rule["DQ-NUM-003"]["count"] == 1


def test_reconciliation_tolerance_boundary(
    client: TestClient, session_root: str
) -> None:
    exact = valid_row(
        **{"Sales": "10.00", "Order Item Discount": "0.00", "Order Item Total": "9.95"}
    )
    session_id = upload_ok(client, craft_csv([exact]))
    quality = client.get(f"/api/v1/sessions/{session_id}/data-quality").json()["data"]
    assert "DQ-NUM-002" not in {issue["ruleId"] for issue in quality["issues"]}

    over = valid_row(
        **{"Sales": "10.00", "Order Item Discount": "0.00", "Order Item Total": "9.94"}
    )
    other_id = upload_ok(client, craft_csv([over]))
    other = client.get(f"/api/v1/sessions/{other_id}/data-quality").json()["data"]
    by_rule = {issue["ruleId"]: issue for issue in other["issues"]}
    assert by_rule["DQ-NUM-002"]["count"] == 1


def test_shipping_days_authoritative_over_timestamps(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, ISSUES_BYTES)
    quality = client.get(f"/api/v1/sessions/{session_id}/data-quality").json()["data"]
    by_rule = {issue["ruleId"]: issue for issue in quality["issues"]}
    # The Same-Day row disagrees on timestamps (DQ-DATE-004 evidence) while
    # its day fields agree with the leakage field: no BUSINESS-003 finding.
    assert by_rule["DQ-DATE-004"]["count"] == 1
    assert by_rule["DQ-BUSINESS-003"]["count"] == 1  # only the planted row


def test_leakage_field_never_becomes_lateness_input(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, ISSUES_BYTES)
    artifact = read_artifact(session_root, session_id)
    text = json.dumps(artifact)
    assert "is_late" not in text
    assert "shipment_outcome" not in text


def test_unknown_extras_ignored_semantically(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CLEAN_BYTES)
    artifact = read_artifact(session_root, session_id)
    text = json.dumps(artifact)
    assert "Zone 7" not in text
    assert artifact["mappedFields"] == 25
    # Privacy-like unknown values never appear either.
    assert "invented.buyer9101@example.invalid" not in text
    assert "11.11" not in json.dumps(artifact["profile"])


def test_unknown_extra_differences_do_not_affect_exact_identity(
    client: TestClient, session_root: str
) -> None:
    """Exact identity spans governed columns only; extras never materialize."""
    header = REQUIRED_HEADER + ",Warehouse Zone"
    first = valid_row() + ",Zone 1"
    second = valid_row() + ",Zone 2"
    content = (header + "\n" + first + "\n" + second + "\n").encode()
    session_id = upload_ok(client, content)
    profile = client.get(f"/api/v1/sessions/{session_id}/profile").json()["data"]
    # Governed values fully identical (shared item key too) → exact duplicate
    # even though the unknown extra differs; the extra values leak nowhere.
    assert profile["duplicates"] == {"exact": 1, "keyDupes": 1}
    artifact = read_artifact(session_root, session_id)
    text = json.dumps(artifact)
    assert "Zone 1" not in text
    assert "Zone 2" not in text


def test_textual_null_zero_and_na_are_not_missing(
    client: TestClient, session_root: str
) -> None:
    header = REQUIRED_HEADER + ",Customer Segment"
    tricky = valid_row(**{"Order Item Quantity": "0", "Order Item Discount": "0.00"})
    content = (header + "\n" + tricky + ",null\n").encode()
    session_id = upload_ok(client, content)
    profile = client.get(f"/api/v1/sessions/{session_id}/profile").json()["data"]
    by_field = {entry["field"]: entry for entry in profile["missingness"]}
    assert by_field["quantity_units"]["missing"] == 0
    assert by_field["quantity_units"]["parseFailures"] == 0
    quality = client.get(f"/api/v1/sessions/{session_id}/data-quality").json()["data"]
    by_rule = {issue["ruleId"]: issue for issue in quality["issues"]}
    # "null" is a value, not missingness: it fails enum membership instead.
    assert by_rule["DQ-CAT-003"]["count"] == 1


def test_latin1_encoding_profiles(client: TestClient, session_root: str) -> None:
    header = ",".join(
        [
            "Order Id",
            "Order Item Id",
            "Customer Id",
            "Product Card Id",
            "Product Category Id",
            "order date (DateOrders)",
            "shipping date (DateOrders)",
            "Sales",
            "Order Item Discount",
            "Order Item Total",
            "Benefit per order",
            "Order Item Product Price",
            "Order Item Quantity",
            "Days for shipping (real)",
            "Days for shipment (scheduled)",
            "Delivery Status",
            "Order Status",
            "Shipping Mode",
            "Customer Segment",
            "Order Country",
            "Order Region",
            "Market",
            "Department Name",
            "Category Name",
            "Product Name",
        ]
    )
    body = (
        "SYN-ORDER-9401,SYN-ITEM-9401,SYN-CUST-941,SYN-PROD-941,SYN-CAT-941,"
        "03-15-2021 10:00,03-18-2021 09:00,29.98,2.00,27.98,6.40,14.99,2,"
        "3,4,Shipped,COMPLETE,Standard Class,Consumer,SYN-Land,North,"
        "SYN-Market,SYN-Dept,SYN-Category,caf\xe9"
    )
    content = (header + "\n" + body + "\n").encode("latin-1")
    try:
        content.decode("utf-8-sig")
        raise AssertionError("fixture must not decode as UTF-8")
    except UnicodeDecodeError:
        pass
    session_id = upload_ok(client, content)
    status = client.get(f"/api/v1/sessions/{session_id}/status")
    assert status.json()["data"]["state"] == "READY"
    profile = client.get(f"/api/v1/sessions/{session_id}/profile").json()["data"]
    assert profile["rows"] == 1


def test_inversion_derived_spellings_take_unknown_path(
    client: TestClient, session_root: str
) -> None:
    """Governance gap: these spellings have no verbatim contract instance.

    Until reference-file confirmation records the exact strings, they take
    the governed UNKNOWN path (ADR-030): counted, reported, excluded from
    split views — never coerced, never blocking. The session still advances.
    """
    header = REQUIRED_HEADER + ",Customer Segment"
    rows = [
        valid_row(**{"Shipping Mode": "Second Class"}) + ",Consumer",
        valid_row(
            **{
                "Order Id": "SYN-ORDER-9302",
                "Order Item Id": "SYN-ITEM-9302",
                "Shipping Mode": "First Class",
            }
        )
        + ",Consumer",
        # Distinct customer: Corporate here is a per-line unknown enum only.
        # Invariance conflicts are per-customer (DQ-GRAIN-004), so a lone
        # Corporate row on its own customer cannot conflict with Consumer
        # rows on other customers.
        valid_row(
            **{
                "Order Id": "SYN-ORDER-9303",
                "Order Item Id": "SYN-ITEM-9303",
                "Customer Id": "SYN-CUST-933",
            }
        )
        + ",Corporate",
    ]
    session_id = upload_ok(client, (header + "\n" + "\n".join(rows) + "\n").encode())
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "READY"
    )
    quality = client.get(f"/api/v1/sessions/{session_id}/data-quality").json()["data"]
    by_rule = {issue["ruleId"]: issue for issue in quality["issues"]}
    assert by_rule["DQ-CAT-002"]["count"] == 2
    assert by_rule["DQ-CAT-002"]["severity"] == "WARNING"
    assert by_rule["DQ-CAT-002"]["blockedStage"] is None
    assert by_rule["DQ-CAT-003"]["count"] == 1


def test_profiling_is_deterministic_across_sessions(
    client: TestClient, session_root: str
) -> None:
    first = upload_ok(client, ISSUES_BYTES)
    second = upload_ok(client, ISSUES_BYTES)
    volatile = {"profiledAt", "sessionId"}
    first_artifact = read_artifact(session_root, first)
    second_artifact = read_artifact(session_root, second)
    for key in volatile:
        del first_artifact[key]
        del second_artifact[key]
    assert first_artifact == second_artifact


# ---------------------------------------------------------------------------
# DQ-GRAIN-003 / DQ-GRAIN-004 dimension invariance (ADR-036, synthetic only)
# ---------------------------------------------------------------------------

DIM_HEADER = (
    REQUIRED_HEADER + ",Customer Segment,Department Name,Category Name,Product Name"
)

DIM_FIELDS = (
    "Customer Segment",
    "Department Name",
    "Category Name",
    "Product Name",
)


def dim_row(valid_kwargs: dict[str, str] | None = None, **dims: str) -> str:
    """One crafted line: required base plus the four optional dim columns."""
    base = {
        "Customer Segment": "Consumer",
        "Department Name": "SYN-Dept",
        "Category Name": "SYN-Category",
        "Product Name": "SYN-Widget",
    }
    base.update(dims)
    return (
        valid_row(**(valid_kwargs or {}))
        + ","
        + ",".join(base[name] for name in DIM_FIELDS)
    )


def dim_csv(rows: list[str]) -> bytes:
    return (DIM_HEADER + "\n" + "\n".join(rows) + "\n").encode()


def dim_quality(client: TestClient, session_id: str) -> dict:
    response = client.get(f"/api/v1/sessions/{session_id}/data-quality")
    assert response.status_code == 200
    return {issue["ruleId"]: issue for issue in response.json()["data"]["issues"]}


def test_grain003_identical_dims_do_not_conflict(
    client: TestClient, session_root: str
) -> None:
    rows = [
        dim_row({"Order Id": "SYN-ORDER-9501", "Order Item Id": "SYN-ITEM-9501"}),
        dim_row({"Order Id": "SYN-ORDER-9502", "Order Item Id": "SYN-ITEM-9502"}),
    ]
    session_id = upload_ok(client, dim_csv(rows))
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "READY"
    )
    assert "DQ-GRAIN-003" not in dim_quality(client, session_id)


def test_grain003_conflicting_category_id(
    client: TestClient, session_root: str
) -> None:
    rows = [
        dim_row({"Order Id": "SYN-ORDER-9511", "Order Item Id": "SYN-ITEM-9511"}),
        dim_row(
            {
                "Order Id": "SYN-ORDER-9512",
                "Order Item Id": "SYN-ITEM-9512",
                "Product Category Id": "SYN-CAT-OTHER",
            }
        ),
    ]
    session_id = upload_ok(client, dim_csv(rows))
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "CANONICALIZING"
    )
    by_rule = dim_quality(client, session_id)
    issue = by_rule["DQ-GRAIN-003"]
    assert issue["severity"] == "ERROR"
    assert issue["treatment"] == "flagged"
    assert issue["blockedStage"] == "CANONICALIZATION"
    assert issue["count"] == 1
    artifact = read_artifact(session_root, session_id)
    assert "1" in artifact["issueMessages"]["DQ-GRAIN-003"]
    # Counts only: the conflicting category values leak nowhere.
    assert "SYN-CAT-OTHER" not in json.dumps(artifact)


def test_grain003_conflicting_merch_names(
    client: TestClient, session_root: str
) -> None:
    cases = [
        ("Department Name", "SYN-Other-Dept"),
        ("Category Name", "SYN-Other-Category"),
        ("Product Name", "SYN-Other-Widget"),
    ]
    for field, other in cases:
        rows = [
            dim_row({"Order Id": "SYN-ORDER-9521", "Order Item Id": "SYN-ITEM-9521"}),
            dim_row(
                {"Order Id": "SYN-ORDER-9522", "Order Item Id": "SYN-ITEM-9522"},
                **{field: other},
            ),
        ]
        session_id = upload_ok(client, dim_csv(rows))
        by_rule = dim_quality(client, session_id)
        assert by_rule["DQ-GRAIN-003"]["count"] == 1, field
        profile = client.get(f"/api/v1/sessions/{session_id}/profile").json()["data"]
        detail = profile["productInvarianceConflicts"]
        assert detail["keysChecked"] == 1
        assert detail["conflictingKeys"] == 1


def test_grain003_missing_vs_value_is_not_a_conflict(
    client: TestClient, session_root: str
) -> None:
    rows = [
        dim_row({"Order Id": "SYN-ORDER-9531", "Order Item Id": "SYN-ITEM-9531"}),
        dim_row(
            {"Order Id": "SYN-ORDER-9532", "Order Item Id": "SYN-ITEM-9532"},
            **{"Product Name": ""},
        ),
    ]
    session_id = upload_ok(client, dim_csv(rows))
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "READY"
    )
    assert "DQ-GRAIN-003" not in dim_quality(client, session_id)


def test_grain003_unit_price_variation_is_not_a_conflict(
    client: TestClient, session_root: str
) -> None:
    """No reference-price concept exists: unit_price can never conflict."""
    rows = [
        dim_row({"Order Id": "SYN-ORDER-9541", "Order Item Id": "SYN-ITEM-9541"}),
        dim_row(
            {
                "Order Id": "SYN-ORDER-9542",
                "Order Item Id": "SYN-ITEM-9542",
                "Order Item Product Price": "99.99",
            }
        ),
    ]
    session_id = upload_ok(client, dim_csv(rows))
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "READY"
    )
    assert "DQ-GRAIN-003" not in dim_quality(client, session_id)


def test_grain003_padding_only_difference_is_cat005_not_conflict(
    client: TestClient, session_root: str
) -> None:
    """Stripped-text comparison: padding is CAT-005 trim fuel, not conflict."""
    rows = [
        dim_row({"Order Id": "SYN-ORDER-9551", "Order Item Id": "SYN-ITEM-9551"}),
        dim_row(
            {"Order Id": "SYN-ORDER-9552", "Order Item Id": "SYN-ITEM-9552"},
            **{"Product Name": " SYN-Widget "},
        ),
    ]
    session_id = upload_ok(client, dim_csv(rows))
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "READY"
    )
    by_rule = dim_quality(client, session_id)
    assert "DQ-GRAIN-003" not in by_rule
    assert by_rule["DQ-CAT-005"]["treatment"] == "detected"


def test_grain004_same_segment_does_not_conflict(
    client: TestClient, session_root: str
) -> None:
    rows = [
        dim_row({"Order Id": "SYN-ORDER-9561", "Order Item Id": "SYN-ITEM-9561"}),
        dim_row({"Order Id": "SYN-ORDER-9562", "Order Item Id": "SYN-ITEM-9562"}),
    ]
    session_id = upload_ok(client, dim_csv(rows))
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "READY"
    )
    assert "DQ-GRAIN-004" not in dim_quality(client, session_id)


def test_grain004_conflicting_segments(client: TestClient, session_root: str) -> None:
    rows = [
        dim_row({"Order Id": "SYN-ORDER-9571", "Order Item Id": "SYN-ITEM-9571"}),
        dim_row(
            {"Order Id": "SYN-ORDER-9572", "Order Item Id": "SYN-ITEM-9572"},
            **{"Customer Segment": "Home Office"},
        ),
    ]
    session_id = upload_ok(client, dim_csv(rows))
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "CANONICALIZING"
    )
    by_rule = dim_quality(client, session_id)
    issue = by_rule["DQ-GRAIN-004"]
    assert issue["severity"] == "ERROR"
    assert issue["treatment"] == "flagged"
    assert issue["blockedStage"] == "CANONICALIZATION"
    assert issue["count"] == 1
    profile = client.get(f"/api/v1/sessions/{session_id}/profile").json()["data"]
    detail = profile["customerInvarianceConflicts"]
    assert detail["keysChecked"] == 1
    assert detail["conflictingKeys"] == 1
    assert {
        entry["field"]: entry["conflictingKeys"] for entry in detail["byField"]
    } == {"customer_segment": 1}


def test_grain004_missing_vs_value_is_not_a_conflict(
    client: TestClient, session_root: str
) -> None:
    rows = [
        dim_row({"Order Id": "SYN-ORDER-9581", "Order Item Id": "SYN-ITEM-9581"}),
        dim_row(
            {"Order Id": "SYN-ORDER-9582", "Order Item Id": "SYN-ITEM-9582"},
            **{"Customer Segment": ""},
        ),
    ]
    session_id = upload_ok(client, dim_csv(rows))
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "READY"
    )
    assert "DQ-GRAIN-004" not in dim_quality(client, session_id)


def test_grain004_unknown_segment_still_flags_without_repair(
    client: TestClient, session_root: str
) -> None:
    """Corporate is unknown-domain (CAT-003, never coerced) AND a second
    distinct segment value (GRAIN-004): independent findings, no repair."""
    rows = [
        dim_row({"Order Id": "SYN-ORDER-9591", "Order Item Id": "SYN-ITEM-9591"}),
        dim_row(
            {"Order Id": "SYN-ORDER-9592", "Order Item Id": "SYN-ITEM-9592"},
            **{"Customer Segment": "Corporate"},
        ),
    ]
    session_id = upload_ok(client, dim_csv(rows))
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "CANONICALIZING"
    )
    by_rule = dim_quality(client, session_id)
    assert by_rule["DQ-GRAIN-004"]["count"] == 1
    assert by_rule["DQ-CAT-003"]["count"] == 1
    assert by_rule["DQ-CAT-003"]["blockedStage"] is None


def test_dimension_detail_shape_on_shared_issues_fixture(
    client: TestClient, session_root: str
) -> None:
    profile = client.get(
        f"/api/v1/sessions/{upload_ok(client, ISSUES_BYTES)}/profile"
    ).json()["data"]
    assert set(profile["productInvarianceConflicts"]) == {
        "keysChecked",
        "conflictingKeys",
        "byField",
    }
    assert profile["productInvarianceConflicts"]["keysChecked"] == 2
    assert profile["productInvarianceConflicts"]["conflictingKeys"] == 0
    assert profile["customerInvarianceConflicts"]["keysChecked"] == 2
    assert profile["customerInvarianceConflicts"]["conflictingKeys"] == 1
    assert {
        entry["field"]: entry["conflictingKeys"]
        for entry in profile["customerInvarianceConflicts"]["byField"]
    } == {"customer_segment": 1}
