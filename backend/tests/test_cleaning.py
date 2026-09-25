"""Phase-7 auditable-cleaning tests (synthetic data only, deterministic).

Covers: the CAT-005 trim matrix (positive + edge cases), the
no-unauthorized-cleaning battery (duplicates, missing values, numerics,
dates, delivery/leakage, unknown enums, unknown columns), audit-count
reconciliation, idempotence/determinism, privacy exclusion, lifecycle
(CLEANING -> CANONICALIZING -> ANALYZING -> READY, observational GETs,
409/404/410,
ADR-028 failure, restart recovery, torn adoption, reset, duplicate guard),
stage-blocking travel, and a generated scale check. No real DataCo file is
used anywhere.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import app.sessions as session_store
from app import cleaning as cleaning_service
from app.cleaning import (
    apply_trims,
    build_steps,
    padding_mask,
    trim_scope,
)
from app.config import settings
from app.main import app
from app.profile_checks import ORDER_STATUS_VALUES, ProfileInputs
from app.profiling import ensure_profiled, run_profiling

TRIM_BYTES = (Path(__file__).parent / "fixtures" / "cleaning_trim.csv").read_bytes()
ISSUES_BYTES = (
    Path(__file__).parent / "fixtures" / "profiling_issues.csv"
).read_bytes()

REQUIRED_HEADER = ",".join(
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
    ]
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", root)
    return root


def upload_ok(client: TestClient, content: bytes) -> tuple[str, dict]:
    response = client.post(
        "/api/v1/sessions/uploads",
        files={"file": ("data.csv", content, "text/csv")},
    )
    assert response.status_code == 202
    return response.json()["data"]["sessionId"], response.json()["data"]


def park_at_cleaning(session_root: str, content: bytes) -> str:
    """A CLEANING session with profiling done but cleaning never executed."""
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
    assert profiled.cleaningArtifact is None
    return session_id


def read_cleaned(session_root: str, session_id: str) -> pd.DataFrame:
    paths = session_store.session_paths(session_root, session_id)
    with open(os.path.join(paths.derived, "cleaned.csv"), "rb") as handle:
        raw = handle.read()
    assert b"invented.trimmer@example.invalid" not in raw
    return pd.read_csv(
        os.path.join(paths.derived, "cleaned.csv"),
        dtype="string[pyarrow]",
        keep_default_na=False,
    )


def steps_by_rule(session_root: str, session_id: str) -> dict[str, list[dict]]:
    paths = session_store.session_paths(session_root, session_id)
    artifact = session_store.read_cleaning_report(paths)
    assert artifact is not None
    grouped: dict[str, list[dict]] = {}
    for step in artifact.steps:
        grouped.setdefault(step.ruleId, []).append(step.model_dump())
    return grouped


# ---------------------------------------------------------------------------
# CAT-005 unit matrix (prompt section 30, direct strings, no fixtures)
# ---------------------------------------------------------------------------


def _unit_frame(values: dict[str, list[str]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            column: pd.array(rows, dtype="string[pyarrow]")
            for column, rows in values.items()
        }
    )


def _unit_inputs() -> ProfileInputs:
    col_of = {
        "order_status": "Order Status",
        "destination_country": "Order Country",
        "category_name": "Category Name",
    }
    return ProfileInputs(
        col_of=col_of,
        audit_header=None,
        source_headers=["Order Status", "Order Country", "Category Name"],
    )


def test_trim_matrix_edge_cases() -> None:
    inputs = _unit_inputs()
    frame = _unit_frame(
        {
            "Order Status": [" Retail ", "Retail", "retail", "COMPLETE "],
            "Order Country": ["Retail  Sales", "\tRetail\n", "Retail", "SYN-Land"],
            "Category Name": ["a", "b", "c", "d"],
        }
    )
    # Trim scope is the governed field set; domain membership is irrelevant.
    assert set(trim_scope(inputs.col_of)) == {
        "destination_country",
        "category_name",
        "order_status",
    }
    country_mask = padding_mask(frame, "Order Country")
    assert country_mask.tolist() == [False, True, False, False]
    # Whitespace and domain findings are independent: " Retail " is CAT-005
    # eligible even though its trimmed value stays unknown under CAT-001.
    status_mask = padding_mask(frame, "Order Status")
    assert status_mask.tolist() == [True, False, False, True]
    assert "Retail" not in ORDER_STATUS_VALUES  # still unknown after trim
    cleaned, fixed_by_field, rows_fixed = apply_trims(frame, inputs)
    # "\tRetail\n" trims; "Retail  Sales" keeps internal whitespace; case kept.
    assert cleaned["Order Country"].tolist() == [
        "Retail  Sales",
        "Retail",
        "Retail",
        "SYN-Land",
    ]
    assert cleaned["Order Status"].tolist() == [
        "Retail",
        "Retail",
        "retail",
        "COMPLETE",
    ]
    assert fixed_by_field == {
        "destination_country": 1,
        "category_name": 0,
        "order_status": 2,
    }
    assert rows_fixed == 3


def test_whitespace_definition_covers_tabs_newlines_nbsp() -> None:
    """Governance says "leading/trailing whitespace" without pinning ASCII.

    Documented reading: Python str.strip() semantics (spaces, tabs,
    newlines, and other Unicode whitespace such as NBSP).
    """
    inputs = _unit_inputs()
    frame = _unit_frame(
        {
            "Order Status": ["COMPLETE", "COMPLETE", "COMPLETE", "COMPLETE"],
            "Order Country": [
                " Retail ",
                "\tRetail\t",
                "\nRetail\n",
                "\u00a0Retail\u00a0",  # U+00A0 NO-BREAK SPACE around Retail
            ],
            "Category Name": ["a", "b", "c", "d"],
        }
    )
    cleaned, fixed_by_field, _ = apply_trims(frame, inputs)
    assert cleaned["Order Country"].tolist() == ["Retail"] * 4
    assert fixed_by_field["destination_country"] == 4


def test_only_governed_label_fields_are_trimmed() -> None:
    inputs = ProfileInputs(
        col_of={
            "order_id": "Order Id",
            "gross_sales": "Sales",
            "destination_country": "Order Country",
        },
        audit_header=None,
        source_headers=["Order Id", "Sales", "Order Country"],
    )
    frame = _unit_frame(
        {
            "Order Id": ["  SYN-ORDER-1  ", "SYN-ORDER-2"],
            "Sales": ["  30.00  ", "30.00"],
            "Order Country": ["  SYN-Land  ", "SYN-Land"],
        }
    )
    cleaned, fixed_by_field, rows_fixed = apply_trims(frame, inputs)
    # IDs and amounts are outside CAT-005 scope: byte-identical.
    assert cleaned["Order Id"].tolist() == ["  SYN-ORDER-1  ", "SYN-ORDER-2"]
    assert cleaned["Sales"].tolist() == ["  30.00  ", "30.00"]
    assert cleaned["Order Country"].tolist() == ["SYN-Land", "SYN-Land"]
    assert fixed_by_field == {"destination_country": 1}
    assert rows_fixed == 1


# ---------------------------------------------------------------------------
# Trim fixture integration
# ---------------------------------------------------------------------------


def test_trim_fixture_settles_at_ready(client: TestClient, session_root: str) -> None:
    session_id, accepted = upload_ok(client, TRIM_BYTES)
    data = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert data["state"] == "READY"
    assert data["stage"] == "READY"
    assert data["error"] is None
    paths = session_store.session_paths(session_root, session_id)
    assert sorted(os.listdir(paths.derived)) == [
        "canonical_calendar.csv",
        "canonical_customers.csv",
        "canonical_data_quality_issues.csv",
        "canonical_order_items.csv",
        "canonical_orders.csv",
        "canonical_products.csv",
        "canonical_report.json",
        "cleaned.csv",
        "cleaning_report.json",
        "kpi_report.json",
        "profiling_report.json",
        "schema_report.json",
    ]
    with open(paths.raw, "rb") as handle:
        assert handle.read() == TRIM_BYTES
    assert accepted["sha256"] == hashlib.sha256(TRIM_BYTES).hexdigest()


def test_trim_fixture_values_and_counts(client: TestClient, session_root: str) -> None:
    session_id, _ = upload_ok(client, TRIM_BYTES)
    cleaned = read_cleaned(session_root, session_id)
    assert len(cleaned) == 8
    # Unknown/privacy columns never materialize in the cleaned projection.
    assert "Customer Email" not in cleaned.columns
    assert len(cleaned.columns) == 25
    by_item = {row["Order Item Id"]: row for _, row in cleaned.iterrows()}
    assert by_item["TRIM-ITEM-01"]["Order Country"] == "SYN-Land"
    assert by_item["TRIM-ITEM-02"]["Category Name"] == "SYN  Widget"
    assert by_item["TRIM-ITEM-03"]["Product Name"] == "SYN-Gadget"
    assert by_item["TRIM-ITEM-04"]["Order Status"] == "COMPLETE"
    # Whitespace and domain findings are independent: " Rocket " trims to
    # "Rocket" (CAT-005 fixed) while staying unknown (CAT-002 flagged).
    assert by_item["TRIM-ITEM-05"]["Shipping Mode"] == "Rocket"
    assert by_item["TRIM-ITEM-06"]["Shipping Mode"] == "Second Class"
    assert by_item["TRIM-ITEM-06"]["Customer Segment"] == "Corporate"
    assert by_item["TRIM-ITEM-07"]["Customer Segment"] == "consumer"
    assert by_item["TRIM-ITEM-08"]["Order Status"] == "COMPLETE"

    grouped = steps_by_rule(session_root, session_id)
    cat_steps = {s["field"]: s for s in grouped["DQ-CAT-005"]}
    assert cat_steps["destination_country"]["fixed"] == 1
    assert cat_steps["product_name"]["fixed"] == 1
    assert cat_steps["order_status"]["fixed"] == 1
    assert cat_steps["shipping_mode"]["fixed"] == 1
    assert sum(s["fixed"] for s in grouped["DQ-CAT-005"]) == 4
    # Unknown enums remain flagged, never coerced into known categories.
    assert grouped["DQ-CAT-002"][0]["flagged"] == 2
    assert grouped["DQ-CAT-002"][0]["fixed"] == 0
    assert grouped["DQ-CAT-003"][0]["flagged"] == 2
    assert grouped["DQ-CAT-003"][0]["fixed"] == 0
    # Privacy exclusion recorded without values.
    assert grouped["DQ-PRIVACY-001"][0]["excluded"] == 1

    paths = session_store.session_paths(session_root, session_id)
    artifact = session_store.read_cleaning_report(paths)
    assert artifact is not None
    assert artifact.totals.rows == 8
    # Profiling attributes the padded-unknown enum row to CAT-002, so its
    # row-level CAT-005 count (3) is below the cleaning trim population (4).
    assert artifact.totals.rowsWithPaddingDetected == 3
    assert artifact.totals.rowsFixed == 4
    assert artifact.totals.cellsFixed == 4
    assert artifact.totals.fieldsTrimmed == 4
    assert artifact.reconciliation.grossPre == artifact.reconciliation.grossPost
    assert artifact.reconciliation.netPre == artifact.reconciliation.netPost == "224.00"
    # Only CAT-005 ever reports fixed > 0.
    for step in artifact.steps:
        if step.ruleId != "DQ-CAT-005":
            assert step.fixed == 0


# ---------------------------------------------------------------------------
# No-unauthorized-cleaning battery (adversarial fixture)
# ---------------------------------------------------------------------------


def test_adversarial_fixture_retains_everything_but_governed_trims(
    client: TestClient, session_root: str
) -> None:
    session_id, _ = upload_ok(client, ISSUES_BYTES)
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "CANONICALIZING"
    )
    cleaned = pd.read_csv(
        os.path.join(
            session_store.session_paths(session_root, session_id).derived, "cleaned.csv"
        ),
        dtype="string[pyarrow]",
        keep_default_na=False,
    )
    # No dedupe: duplicates retained exactly (3 lines share one item ID).
    assert len(cleaned) == 18
    assert int((cleaned["Order Item Id"] == "SYN-ITEM-DUP-01").sum()) == 3
    # Repeated Order Id + Product Id pairs retained.
    assert int((cleaned["Order Id"] == "SYN-ORDER-9201").sum()) == 3
    by_item = {}
    for _, row in cleaned.iterrows():
        by_item.setdefault(row["Order Item Id"], []).append(row)
    # Missing values never imputed.
    assert by_item["SYN-ITEM-9202"][0]["Customer Id"] == ""
    assert by_item["SYN-ITEM-9202"][0]["order date (DateOrders)"] == ""
    # Malformed values never repaired.
    assert by_item["SYN-ITEM-9203"][0]["order date (DateOrders)"] == "31-02-2021 10:00"
    assert by_item["SYN-ITEM-9203"][0]["shipping date (DateOrders)"] == "not-a-date"
    assert by_item["SYN-ITEM-9202"][0]["Order Item Quantity"] == "two"
    # Arithmetic never replaces reported net; negatives never clamped.
    assert by_item["SYN-ITEM-9207"][0]["Order Item Total"] == "50.00"
    assert by_item["SYN-ITEM-9208"][0]["Benefit per order"] == "-150.00"
    # Shipping days never reconciled to timestamps.
    assert by_item["SYN-ITEM-9214"][0]["Days for shipping (real)"] == "-3"
    assert by_item["SYN-ITEM-9215"][0]["Days for shipping (real)"] == "5"
    # Unknown enums never coerced (including case).
    assert by_item["SYN-ITEM-9210"][0]["Order Status"] == "WEIRD_STATUS"
    assert by_item["SYN-ITEM-9211"][0]["Shipping Mode"] == "Rocket"
    assert by_item["SYN-ITEM-9212"][0]["Customer Segment"] == "Platinum"
    # Cancelled rows retained.
    assert by_item["SYN-ITEM-9216"][0]["Delivery Status"] == "Shipping canceled"
    # The one governed trim still applies.
    assert by_item["SYN-ITEM-9213"][0]["Order Country"] == "SYN-Land"
    # Leakage/audit-only and unknown columns stay raw-only.
    assert "Late_delivery_risk" not in cleaned.columns
    assert "Warehouse Zone" not in cleaned.columns
    assert "Customer Email" not in cleaned.columns
    assert "Buyer Latitude" not in cleaned.columns
    assert "Order Customer Id" not in cleaned.columns
    # Raw byte-identical.
    paths = session_store.session_paths(session_root, session_id)
    with open(paths.raw, "rb") as handle:
        assert handle.read() == ISSUES_BYTES


# ---------------------------------------------------------------------------
# Audit-count reconciliation
# ---------------------------------------------------------------------------


def test_audit_counts_reconcile_per_step(client: TestClient, session_root: str) -> None:
    for content in (TRIM_BYTES, ISSUES_BYTES):
        session_id, _ = upload_ok(client, content)
        paths = session_store.session_paths(session_root, session_id)
        artifact = session_store.read_cleaning_report(paths)
        assert artifact is not None
        for step in artifact.steps:
            assert step.detected == (
                step.fixed + step.flagged + step.excluded + step.unchanged
            ), step.ruleId
            assert set(step.model_dump()) == {
                "ruleId",
                "field",
                "detected",
                "fixed",
                "flagged",
                "excluded",
                "unchanged",
                "reason",
            }
        # Money never moves under trim-only cleaning.
        assert artifact.reconciliation.grossPre == artifact.reconciliation.grossPost
        assert (
            artifact.reconciliation.discountPre == artifact.reconciliation.discountPost
        )
        assert artifact.reconciliation.netPre == artifact.reconciliation.netPost
        assert artifact.reconciliation.profitPre == artifact.reconciliation.profitPost
        assert artifact.outputRows == artifact.inputSourceRows == artifact.totals.rows


def test_build_steps_zero_state_holds_invariant() -> None:
    inputs = _unit_inputs()
    steps = build_steps(
        {}, ["DQ-KEY-001", "DQ-CAT-005", "DQ-FILE-005"], {}, inputs.col_of
    )
    assert [s.ruleId for s in steps] != ["DQ-FILE-005"]
    for step in steps:
        assert (
            step.detected == step.fixed + step.flagged + step.excluded + step.unchanged
        )
        assert step.detected == 0


# ---------------------------------------------------------------------------
# Idempotence / determinism
# ---------------------------------------------------------------------------


def test_rerun_is_byte_identical(client: TestClient, session_root: str) -> None:
    session_id, _ = upload_ok(client, TRIM_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    with open(os.path.join(paths.derived, "cleaned.csv"), "rb") as handle:
        before = handle.read()
    first = session_store.read_cleaning_report(paths)
    rerun = cleaning_service.run_cleaning(session_id)
    assert rerun is not None and rerun.state == "READY"
    with open(os.path.join(paths.derived, "cleaned.csv"), "rb") as handle:
        assert handle.read() == before
    second = session_store.read_cleaning_report(paths)
    assert first is not None and second is not None
    assert first.steps == second.steps
    assert first.totals == second.totals


def test_same_input_same_semantic_output(client: TestClient, session_root: str) -> None:
    first_id, _ = upload_ok(client, TRIM_BYTES)
    second_id, _ = upload_ok(client, TRIM_BYTES)
    first_paths = session_store.session_paths(session_root, first_id)
    second_paths = session_store.session_paths(session_root, second_id)
    first = session_store.read_cleaning_report(first_paths)
    second = session_store.read_cleaning_report(second_paths)
    assert first is not None and second is not None
    assert first.steps == second.steps
    assert first.totals == second.totals
    assert first.reconciliation == second.reconciliation
    assert first.outputSha256 == second.outputSha256


def test_torn_transition_adopts_identical_result(
    client: TestClient, session_root: str
) -> None:
    session_id, _ = upload_ok(client, TRIM_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    with open(os.path.join(paths.derived, "cleaned.csv"), "rb") as handle:
        before = handle.read()
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    manifest.state = "CLEANING"
    manifest.stage = "CLEANING"
    manifest.cleaningArtifact = None
    session_store.write_manifest(paths, manifest)
    adopted = cleaning_service.run_cleaning(session_id)
    assert adopted is not None and adopted.state == "READY"
    assert adopted.cleaningArtifact is not None
    with open(os.path.join(paths.derived, "cleaned.csv"), "rb") as handle:
        assert handle.read() == before


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


def _privacy_bytes() -> bytes:
    header = (
        REQUIRED_HEADER
        + ",Customer Segment,Order Country,Customer FirstName,"
        + "Customer Email,Buyer Latitude"
    )
    row = (
        "SYN-ORDER-9301,SYN-ITEM-9301,SYN-CUST-931,SYN-PROD-01,SYN-CAT-01,"
        "03-15-2021 10:00,03-18-2021 09:00,30.00,2.00,28.00,6.40,15.00,2,3,4,"
        "Shipped,COMPLETE,Standard Class,Consumer,SYN-Land,"
        "InventedFirst rough,  invented.probe9301@example.invalid  ,11.11"
    )
    return (header + "\n" + row + "\n").encode()


def test_privacy_probes_never_enter_derived_outputs(
    client: TestClient, session_root: str, caplog: pytest.LogCaptureFixture
) -> None:
    content = _privacy_bytes()
    with caplog.at_level(logging.INFO):
        session_id, _ = upload_ok(client, content)
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "READY"
    )
    paths = session_store.session_paths(session_root, session_id)
    with open(os.path.join(paths.derived, "cleaning_report.json"), "rb") as handle:
        report_raw = handle.read()
    with open(os.path.join(paths.derived, "cleaned.csv"), "rb") as handle:
        cleaned_raw = handle.read()
    for probe in (
        b"InventedFirst",
        b"invented.probe9301@example.invalid",
        b"11.11",
        b"Customer FirstName",
    ):
        assert probe not in report_raw
        assert probe not in cleaned_raw
    for record in caplog.records:
        assert "InventedFirst" not in record.getMessage()
        assert "invented.probe9301" not in record.getMessage()
    # Exclusion is still counted, without values.
    grouped = steps_by_rule(session_root, session_id)
    assert grouped["DQ-PRIVACY-001"][0]["excluded"] >= 1
    assert grouped["DQ-PRIVACY-002"][0]["excluded"] >= 1


# ---------------------------------------------------------------------------
# Lifecycle / API
# ---------------------------------------------------------------------------


def test_cleaning_report_endpoint_shape_and_travel(
    client: TestClient, session_root: str
) -> None:
    session_id, _ = upload_ok(client, ISSUES_BYTES)
    response = client.get(f"/api/v1/sessions/{session_id}/cleaning-report")
    assert response.status_code == 200
    steps = response.json()["data"]["steps"]
    assert isinstance(steps, list) and steps
    assert {s["ruleId"] for s in steps} >= {
        "DQ-KEY-001",
        "DQ-CAT-005",
        "DQ-GRAIN-001",
        "DQ-PRIVACY-001",
    }
    by_rule = {s["ruleId"]: s for s in steps if s["ruleId"] == "DQ-KEY-001"}
    assert by_rule["DQ-KEY-001"]["flagged"] == 2
    assert "Blocks CANONICALIZATION" in by_rule["DQ-KEY-001"]["reason"]


def test_error_findings_travel_and_block_later_stages_only(
    client: TestClient, session_root: str
) -> None:
    session_id, _ = upload_ok(client, ISSUES_BYTES)
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "CANONICALIZING"
    )
    grouped = steps_by_rule(session_root, session_id)
    assert grouped["DQ-KEY-001"][0]["flagged"] == 2
    assert "Blocks CANONICALIZATION" in grouped["DQ-KEY-001"][0]["reason"]
    assert grouped["DQ-GRAIN-001"][0]["flagged"] >= 1
    assert "Blocks CANONICALIZATION" in grouped["DQ-GRAIN-001"][0]["reason"]
    assert "Blocks KPI_ANALYSIS" in grouped["DQ-DATE-001"][0]["reason"]
    # Dimension rules travel as flagged findings with no value mutation.
    assert grouped["DQ-GRAIN-004"][0]["flagged"] >= 1
    assert "Blocks CANONICALIZATION" in grouped["DQ-GRAIN-004"][0]["reason"]
    assert grouped["DQ-GRAIN-004"][0]["fixed"] == 0
    # GRAIN-003 is clean on this fixture: a zero step, never a fix.
    assert grouped["DQ-GRAIN-003"][0]["detected"] == 0
    assert grouped["DQ-GRAIN-003"][0]["flagged"] == 0
    assert grouped["DQ-GRAIN-003"][0]["fixed"] == 0


def test_gets_are_observational_and_pending_is_409(session_root: str) -> None:
    session_id = park_at_cleaning(session_root, TRIM_BYTES)
    # A bare TestClient needs the app; build one locally without fixtures.
    local_client = TestClient(app)
    response = local_client.get(f"/api/v1/sessions/{session_id}/cleaning-report")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NOT_READY"
    assert response.json()["error"]["details"] == {"state": "CLEANING"}
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None and manifest.state == "CLEANING"
    assert manifest.cleaningArtifact is None
    assert not os.path.exists(os.path.join(paths.derived, "cleaning_report.json"))


def test_unknown_and_expired_cleaning_report(
    client: TestClient, session_root: str
) -> None:
    assert (
        client.get(f"/api/v1/sessions/{uuid.uuid4()}/cleaning-report").status_code
        == 404
    )
    assert client.get("/api/v1/sessions/not-a-uuid/cleaning-report").status_code == 404
    session_id, _ = upload_ok(client, TRIM_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    manifest.lastAccessedAt = (
        (datetime.now() - timedelta(days=2)).replace(microsecond=0).isoformat()
    )
    session_store.write_manifest(paths, manifest)
    expired = client.get(f"/api/v1/sessions/{session_id}/cleaning-report")
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "SESSION_EXPIRED"


def test_terminal_cleaning_failure_cleans_up(session_root: str) -> None:
    session_id = park_at_cleaning(session_root, TRIM_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    os.remove(paths.raw)
    failed = cleaning_service.run_cleaning(session_id)
    assert failed is not None and failed.state == "FAILED"
    assert failed.error is not None
    assert failed.error.code == "INTERNAL_STAGE_ERROR"
    assert failed.error.stage == "CLEANING"
    assert not os.path.exists(paths.raw)
    assert os.listdir(paths.derived) == []
    assert session_store.read_manifest(paths) is not None
    local_client = TestClient(app)
    response = local_client.get(f"/api/v1/sessions/{session_id}/cleaning-report")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_STAGE_ERROR"


def test_recover_cleaning_sessions_covers_crash_window(session_root: str) -> None:
    os.makedirs(session_root, exist_ok=True)
    good = park_at_cleaning(session_root, TRIM_BYTES)
    assert (
        cleaning_service.run_cleaning(park_at_cleaning(session_root, TRIM_BYTES))
        is not None
    )
    stale = park_at_cleaning(session_root, TRIM_BYTES)
    stale_paths = session_store.session_paths(session_root, stale)
    stale_manifest = session_store.read_manifest(stale_paths)
    assert stale_manifest is not None
    stale_manifest.lastAccessedAt = (
        (datetime.now() - timedelta(days=3)).replace(microsecond=0).isoformat()
    )
    session_store.write_manifest(stale_paths, stale_manifest)
    assert cleaning_service.recover_cleaning_sessions(session_root) == 1
    good_manifest = session_store.read_manifest(
        session_store.session_paths(session_root, good)
    )
    assert good_manifest is not None and good_manifest.state == "READY"
    assert os.path.isdir(stale_paths.root)


def test_duplicate_worker_invocation_is_safe(
    client: TestClient, session_root: str
) -> None:
    session_id, _ = upload_ok(client, TRIM_BYTES)
    first = cleaning_service.run_cleaning(session_id)
    second = cleaning_service.run_cleaning(session_id)
    assert first is not None and second is not None
    assert first.state == second.state == "READY"
    cleaning_service._CLEANING_IN_PROGRESS.add(session_id)
    try:
        assert cleaning_service.run_cleaning(session_id) is None
    finally:
        cleaning_service._CLEANING_IN_PROGRESS.discard(session_id)


def test_reset_cannot_be_resurrected_by_workers(
    client: TestClient, session_root: str
) -> None:
    session_id, _ = upload_ok(client, TRIM_BYTES)
    assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 200
    assert cleaning_service.run_cleaning(session_id) is None
    assert run_profiling(session_id) is None
    assert cleaning_service.recover_cleaning_sessions(session_root) == 0
    assert os.listdir(session_root) == []


def test_artifact_write_failure_leaves_safe_rerunnable_state(
    session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = park_at_cleaning(session_root, TRIM_BYTES)

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("injected artifact failure")

    real_write_report = session_store.write_cleaning_report
    monkeypatch.setattr(session_store, "write_cleaning_report", boom)
    stalled = cleaning_service.run_cleaning(session_id)
    assert stalled is not None and stalled.state == "CLEANING"
    assert stalled.cleaningArtifact is None
    monkeypatch.setattr(session_store, "write_cleaning_report", real_write_report)
    recovered = cleaning_service.run_cleaning(session_id)
    assert recovered is not None and recovered.state == "READY"


def test_foreign_artifact_is_recomputed_not_adopted(session_root: str) -> None:
    session_id = park_at_cleaning(session_root, TRIM_BYTES)
    assert cleaning_service.run_cleaning(session_id) is not None
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    artifact = session_store.read_cleaning_report(paths)
    assert manifest is not None and artifact is not None
    artifact.sourceSha256 = "0" * 64
    session_store.write_cleaning_report(paths, artifact)
    manifest.state = "CLEANING"
    manifest.stage = "CLEANING"
    manifest.cleaningArtifact = None
    session_store.write_manifest(paths, manifest)
    with open(paths.raw, "ab") as handle:
        handle.write(b"tamper,bytes\n")
    failed = cleaning_service.run_cleaning(session_id)
    assert failed is not None and failed.state == "FAILED"


# ---------------------------------------------------------------------------
# Scale (generated rows, no giant fixture)
# ---------------------------------------------------------------------------


def test_csv_serialization_never_invents_transforms(tmp_path: Path) -> None:
    """Pandas round-trip preserves every semantic cell (§17 audit).

    Empty stays empty; leading zeros, commas, quotes, embedded newlines,
    non-ASCII text, and formula-looking strings survive byte-normalized
    quoting without value changes. Quoting normalization is fine because
    artifact semantics are value-based and raw stays immutable.
    """
    from app.cleaning import _write_cleaned_csv

    frame = pd.DataFrame(
        {
            "Order Item Id": pd.array(
                ["001", "00X-7", "a,b", 'q"q', "line\nbreak", "", "NA", "null"],
                dtype="string[pyarrow]",
            ),
            "Order Country": pd.array(
                ["  SYN-Land  ", "Café", "+1", "01", "-12.50", "=SUM(A1:A2)", "x", "y"],
                dtype="string[pyarrow]",
            ),
        }
    )
    target = str(tmp_path / "cleaned.csv")
    _write_cleaned_csv(frame, target)
    back = pd.read_csv(target, dtype="string[pyarrow]", keep_default_na=False)
    assert back["Order Item Id"].tolist() == [
        "001",
        "00X-7",
        "a,b",
        'q"q',
        "line\nbreak",
        "",
        "NA",
        "null",
    ]
    # Untouched by cleaning here; serialization alone changes nothing.
    assert back["Order Country"].tolist() == [
        "  SYN-Land  ",
        "Café",
        "+1",
        "01",
        "-12.50",
        "=SUM(A1:A2)",
        "x",
        "y",
    ]


def test_latin1_source_cleans_deterministically(
    client: TestClient, session_root: str
) -> None:
    """Latin-1 bytes (incl. non-ASCII padded labels) clean and rerun identically."""
    header = REQUIRED_HEADER + ",Customer Segment,Order Country"
    row = (
        "SYN-ORDER-9401,SYN-ITEM-9401,SYN-CUST-941,SYN-PROD-01,SYN-CAT-01,"
        "03-15-2021 10:00,03-18-2021 09:00,30.00,2.00,28.00,6.40,15.00,2,3,4,"
        "Shipped,COMPLETE,Standard Class,Consumer,  SYN-Café  "
    )
    content = (header + "\n" + row + "\n").encode("latin-1")
    try:
        content.decode("utf-8-sig")
        raise AssertionError("fixture must not decode as UTF-8")
    except UnicodeDecodeError:
        pass
    session_id, _ = upload_ok(client, content)
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "READY"
    )
    paths = session_store.session_paths(session_root, session_id)
    with open(os.path.join(paths.derived, "cleaned.csv"), "rb") as handle:
        before = handle.read()
    assert "SYN-Café".encode() in before
    rerun = cleaning_service.run_cleaning(session_id)
    assert rerun is not None and rerun.state == "READY"
    with open(os.path.join(paths.derived, "cleaned.csv"), "rb") as handle:
        assert handle.read() == before


def test_corrupt_cleaned_csv_is_recomputed_not_adopted(session_root: str) -> None:
    """A corrupt cleaned.csv fails the recomputed-SHA gate → full recompute."""
    session_id = park_at_cleaning(session_root, TRIM_BYTES)
    assert cleaning_service.run_cleaning(session_id) is not None
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    with open(session_store.cleaned_path(paths), "ab") as handle:
        handle.write(b"corrupt,trailing,bytes\n")
    manifest.state = "CLEANING"
    manifest.stage = "CLEANING"
    manifest.cleaningArtifact = None
    session_store.write_manifest(paths, manifest)
    recomputed = cleaning_service.run_cleaning(session_id)
    assert recomputed is not None and recomputed.state == "READY"
    cleaned = pd.read_csv(
        session_store.cleaned_path(paths),
        dtype="string[pyarrow]",
        keep_default_na=False,
    )
    assert len(cleaned) == 8
    assert cleaned["Order Country"].iloc[0] == "SYN-Land"


def test_unreadable_report_with_pointer_returns_stored_state(
    session_root: str,
) -> None:
    """Corrupt report + intact pointer: no false claim, no crash, no rewind.

    Forward-only transitions forbid regressing to CLEANING to regenerate;
    the stored state is returned untouched (GET surfaces the read error).
    """
    session_id = park_at_cleaning(session_root, TRIM_BYTES)
    assert cleaning_service.run_cleaning(session_id) is not None
    paths = session_store.session_paths(session_root, session_id)
    with open(
        os.path.join(paths.derived, "cleaning_report.json"), "w", encoding="utf-8"
    ) as handle:
        handle.write("{not valid json")
    result = cleaning_service.run_cleaning(session_id)
    assert result is not None and result.state == "READY"
    assert result.cleaningArtifact is not None


def test_worker_exception_fails_terminally_and_releases_guard(
    session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unexpected compute errors follow ADR-028; the in-process guard clears."""
    session_id = park_at_cleaning(session_root, TRIM_BYTES)
    paths = session_store.session_paths(session_root, session_id)

    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("injected compute failure")

    monkeypatch.setattr(cleaning_service, "apply_trims", boom)
    failed = cleaning_service.run_cleaning(session_id)
    assert failed is not None and failed.state == "FAILED"
    assert failed.error is not None
    assert failed.error.code == "INTERNAL_STAGE_ERROR"
    assert failed.error.stage == "CLEANING"
    assert not os.path.exists(paths.raw)
    assert os.listdir(paths.derived) == []
    assert not cleaning_service._CLEANING_IN_PROGRESS
    again = cleaning_service.run_cleaning(session_id)
    assert again is not None and again.state == "FAILED"


def test_generated_scale_reconciles(client: TestClient, session_root: str) -> None:
    lines = [REQUIRED_HEADER + ",Customer Segment,Order Country"]
    for seq in range(5000):
        country = "  SYN-Land  " if seq % 7 == 0 else "SYN-Land"
        lines.append(
            f"SYN-ORDER-{seq:05d},SYN-ITEM-{seq:05d},SYN-CUST-{seq % 251},"
            f"SYN-PROD-{seq % 37},SYN-CAT-01,03-15-2021 10:00,03-18-2021 09:00,"
            f"30.00,2.00,28.00,6.40,15.00,2,3,4,Shipped,COMPLETE,"
            f"Standard Class,Consumer,{country}"
        )
    content = ("\n".join(lines) + "\n").encode()
    session_id, _ = upload_ok(client, content)
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "READY"
    )
    paths = session_store.session_paths(session_root, session_id)
    artifact = session_store.read_cleaning_report(paths)
    assert artifact is not None
    assert artifact.totals.rows == 5000
    expected_cells = sum(1 for seq in range(5000) if seq % 7 == 0)
    assert artifact.totals.cellsFixed == expected_cells
    assert artifact.totals.rowsFixed == expected_cells
    assert artifact.outputRows == 5000
    for step in artifact.steps:
        assert (
            step.detected == step.fixed + step.flagged + step.excluded + step.unchanged
        )
    with open(os.path.join(paths.derived, "cleaning_report.json"), "rb") as handle:
        assert b"SYN-ORDER-" not in handle.read()
