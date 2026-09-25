"""Phase-8 canonical-model tests (synthetic data only, deterministic).

Covers, on the small `canonical_small.csv` fixture (6 lines, 4 orders) plus
crafted adversarial frames: source-row provenance, order-item mapping,
is_late derivation (late/early/exact/cancelled/null-days), authoritative
commercial values with retained negative profit, unknown-enum sentinels,
month-first timestamps, privacy exclusion, geography separation, order/
product/customer/calendar/issues builds, reconciliation, the DQ-KEY-001 and
DQ-GRAIN-001 gates (scope, parking, no dedupe, no first-row pick), artifact
integrity (corrupt/stale/foreign/partial/write-failure/recovery), and
concurrency (CAS touches, duplicate workers, reset, no backward moves).

No real DataCo file is used anywhere; no reference controls are hardcoded
into production (assertions here recompute expectations from the fixture).
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import app.sessions as session_store
from app import canonicalization as canonical_service
from app.canonicalization import (
    ORDER_STATUS_MAP,
    dim_conflicts,
    duplicate_item_rows,
    map_enum,
    order_gate_conflicts,
    to_string_frame,
)
from app.config import settings
from app.main import app

CANON_BYTES = (Path(__file__).parent / "fixtures" / "canonical_small.csv").read_bytes()
CANON_HEADER = CANON_BYTES.decode().splitlines()[0]


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


def park_at_canonicalizing(session_root: str, content: bytes) -> str:
    """A CANONICALIZING session with cleaning done, canonical never executed."""
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
    assert cleaned.canonicalArtifact is None
    return session_id


def read_table(session_root: str, session_id: str, name: str) -> pd.DataFrame:
    paths = session_store.session_paths(session_root, session_id)
    return pd.read_csv(
        os.path.join(paths.derived, name),
        dtype="string[pyarrow]",
        keep_default_na=False,
    )


def canonical_report(session_root: str, session_id: str):  # type: ignore[no-untyped-def]
    from app.schemas import CanonicalArtifact

    paths = session_store.session_paths(session_root, session_id)
    artifact = session_store.read_canonical_report(paths)
    assert artifact is not None
    assert isinstance(artifact, CanonicalArtifact)
    return artifact


def by_key(frame: pd.DataFrame, column: str) -> dict[str, dict[str, str]]:
    return {str(row[column]): dict(row) for _, row in frame.iterrows()}


# ---------------------------------------------------------------------------
# Pure-unit derivations (no session needed)
# ---------------------------------------------------------------------------


def test_map_enum_exact_unknown_and_blank() -> None:
    series = pd.Series(
        pd.array(["COMPLETE", " Rocket ", "", "Corporate"], dtype="string[pyarrow]")
    )
    assert map_enum(series.str.strip(), ORDER_STATUS_MAP) == [
        "COMPLETE",
        "UNKNOWN_FLAGGED",
        None,
        "UNKNOWN_FLAGGED",
    ]


def test_duplicate_item_rows_ignores_missing() -> None:
    series = pd.Series(pd.array(["A", "A", " ", "B"], dtype="string[pyarrow]"))
    assert duplicate_item_rows(series) == 1


def test_order_gate_conflicts_ignores_nulls() -> None:
    frame = pd.DataFrame(
        {
            "order_id": ["O1", "O1", "O2"],
            "customer_id": ["C", "C", None],
            "shipping_mode": ["X", "Y", "Z"],
            "order_timestamp": [None, None, None],
            "ship_timestamp": [None, None, None],
            "order_status": ["S", "S", "S"],
            "customer_segment": ["G", "G", "G"],
            "actual_shipping_days": [1, 1, 1],
            "scheduled_shipping_days": [2, 2, 2],
            "destination_country": ["L", "L", "L"],
            "destination_region": ["R", "R", "R"],
            "destination_market": ["M", "M", "M"],
            "shipment_outcome": ["EARLY", "EARLY", "EARLY"],
        }
    )
    assert order_gate_conflicts(frame) == {"O1": ["shipping_mode"]}


def test_dim_conflicts_groups_by_key() -> None:
    frame = pd.DataFrame(
        {
            "product_id": ["P", "P", "Q"],
            "product_name": ["Widget", "Gadget", "Widget"],
        }
    )
    assert dim_conflicts(frame, "product_id", ("product_name",)) == {
        "P": ["product_name"]
    }


def test_to_string_frame_renders_nulls_dates_money() -> None:
    from datetime import date
    from decimal import Decimal

    frame = pd.DataFrame(
        {
            "when": [datetime(2021, 3, 15, 10, 0), None],
            "day": [date(2021, 3, 15), None],
            "amount": [Decimal("27.98"), None],
            "flag": [True, None],
            "n": [2, None],
        }
    )
    rendered = to_string_frame(frame)
    assert rendered["when"].tolist() == ["2021-03-15T10:00:00", ""]
    assert rendered["day"].tolist() == ["2021-03-15", ""]
    assert rendered["amount"].tolist() == ["27.98", ""]
    assert rendered["flag"].tolist() == ["true", ""]
    assert rendered["n"].tolist() == ["2", ""]


# ---------------------------------------------------------------------------
# Complete-build integration on the small synthetic fixture
# ---------------------------------------------------------------------------


def test_small_fixture_settles_at_analyzing(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    data = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert data["state"] == "ANALYZING"
    assert data["stage"] == "ANALYZING"
    assert data["error"] is None
    assert data["progress"]["currentStage"] == "ANALYZING"
    assert "READY" not in data["progress"]["completedStages"]
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
        "profiling_report.json",
        "schema_report.json",
    ]
    manifest = session_store.read_manifest(paths)
    assert manifest is not None and manifest.canonicalArtifact is not None
    with open(paths.raw, "rb") as handle:
        assert handle.read() == CANON_BYTES


def test_source_row_numbers_are_1_based_ordinals(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    items = read_table(session_root, session_id, "canonical_order_items.csv")
    assert items["source_row_number"].tolist() == ["1", "2", "3", "4", "5", "6"]
    assert items["order_item_id"].tolist() == [
        "SYN-ITEM-101",
        "SYN-ITEM-102",
        "SYN-ITEM-201",
        "SYN-ITEM-301",
        "SYN-ITEM-401",
        "SYN-ITEM-402",
    ]


def test_order_items_carry_governed_mapping(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    items = by_key(
        read_table(session_root, session_id, "canonical_order_items.csv"),
        "order_item_id",
    )
    first = items["SYN-ITEM-101"]
    assert first["order_id"] == "SYN-ORDER-100"
    assert first["customer_id"] == "SYN-CUST-01"
    assert first["product_id"] == "SYN-PROD-A"
    assert first["category_id"] == "SYN-CAT-1"
    assert first["quantity_units"] == "2"
    assert first["unit_price"] == "14.99"
    assert first["order_status"] == "COMPLETE"
    assert first["shipping_mode"] == "STANDARD_CLASS"
    assert first["customer_segment"] == "CONSUMER"
    assert first["destination_country"] == "SYN-Land"
    assert first["order_timestamp"] == "2021-03-15T10:00:00"
    assert first["order_date"] == "2021-03-15"
    # CAT-005 trim applied upstream: padded label arrives trimmed.
    assert first["product_name"] == "SYN-Widget"


def test_is_late_late_early_exact_and_cancelled(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    items = by_key(
        read_table(session_root, session_id, "canonical_order_items.csv"),
        "order_item_id",
    )
    late = items["SYN-ITEM-101"]
    assert late["shipment_outcome"] == "LATE"
    assert late["is_late"] == "true"
    assert late["schedule_variance_days"] == "2"
    exact = items["SYN-ITEM-201"]
    assert exact["shipment_outcome"] == "ON_SCHEDULE"
    assert exact["is_late"] == "false"
    assert exact["schedule_variance_days"] == "0"
    early = items["SYN-ITEM-301"]
    assert early["shipment_outcome"] == "EARLY"
    assert early["is_late"] == "false"
    assert early["schedule_variance_days"] == "-3"
    cancelled = items["SYN-ITEM-401"]
    assert cancelled["shipment_outcome"] == "SHIPPING_CANCELED"
    assert cancelled["is_late"] == ""
    assert cancelled["schedule_variance_days"] == ""
    assert cancelled["actual_shipping_days"] == ""
    assert cancelled["scheduled_shipping_days"] == "3"


def test_reported_net_authoritative_and_negative_profit_retained(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    items = by_key(
        read_table(session_root, session_id, "canonical_order_items.csv"),
        "order_item_id",
    )
    assert items["SYN-ITEM-101"]["net_sales"] == "27.98"
    assert items["SYN-ITEM-101"]["gross_sales"] == "29.98"
    assert items["SYN-ITEM-101"]["discount_amount"] == "2.00"
    # Negative profit is retained, never clipped (ADR-017).
    assert items["SYN-ITEM-102"]["profit_amount"] == "-1.25"
    assert items["SYN-ITEM-401"]["profit_amount"] == "-3.00"


def test_unknown_enums_become_flagged_sentinel(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    items = by_key(
        read_table(session_root, session_id, "canonical_order_items.csv"),
        "order_item_id",
    )
    # " Rocket " trims upstream but stays outside the governed set: flagged.
    assert items["SYN-ITEM-301"]["shipping_mode"] == "UNKNOWN_FLAGGED"
    assert items["SYN-ITEM-301"]["customer_segment"] == "UNKNOWN_FLAGGED"
    assert items["SYN-ITEM-101"]["shipping_mode"] == "STANDARD_CLASS"


def test_month_first_timestamps_and_calendar_join(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    items = by_key(
        read_table(session_root, session_id, "canonical_order_items.csv"),
        "order_item_id",
    )
    # 03-15 parses as March 15 (month-first), not 3rd of the 15th month.
    assert items["SYN-ITEM-101"]["order_timestamp"] == "2021-03-15T10:00:00"
    assert items["SYN-ITEM-301"]["order_timestamp"] == "2021-01-05T00:00:00"
    calendar = by_key(
        read_table(session_root, session_id, "canonical_calendar.csv"), "date"
    )
    assert sorted(calendar) == ["2021-01-05", "2021-03-15", "2021-03-16"]
    monday = calendar["2021-03-15"]
    assert monday["year"] == "2021"
    assert monday["quarter"] == "1"
    assert monday["month"] == "3"
    assert monday["iso_week"] == "11"
    assert monday["day_of_week"] == "1"
    assert monday["is_weekend"] == "false"


def test_orders_aggregate_items_exactly_once(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    orders = by_key(
        read_table(session_root, session_id, "canonical_orders.csv"), "order_id"
    )
    assert sorted(orders) == [
        "SYN-ORDER-100",
        "SYN-ORDER-200",
        "SYN-ORDER-300",
        "SYN-ORDER-400",
    ]
    multi = orders["SYN-ORDER-100"]
    assert multi["line_count"] == "2"
    assert multi["total_units"] == "4"
    assert multi["gross_value"] == "49.98"
    assert multi["discount_total"] == "2.50"
    assert multi["net_value"] == "47.48"
    assert multi["profit_total"] == "5.15"
    assert multi["shipment_outcome"] == "LATE"
    assert multi["is_late"] == "true"
    # Merch dims spanning products collapse to null, never a first-row pick.
    assert multi["product_name"] == ""
    assert multi["department_name"] == "SYN-Dept"
    cancelled = orders["SYN-ORDER-400"]
    assert cancelled["shipment_outcome"] == "SHIPPING_CANCELED"
    assert cancelled["is_late"] == ""
    assert cancelled["actual_shipping_days"] == ""
    assert cancelled["line_count"] == "2"
    assert cancelled["net_value"] == "17.00"
    assert cancelled["product_name"] == "SYN-Widget"


def test_products_carry_dims_and_defensible_aggregates(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    products = by_key(
        read_table(session_root, session_id, "canonical_products.csv"), "product_id"
    )
    assert sorted(products) == ["SYN-PROD-A", "SYN-PROD-B", "SYN-PROD-C", "SYN-PROD-D"]
    widget = products["SYN-PROD-A"]
    assert widget["category_id"] == "SYN-CAT-1"
    assert widget["product_name"] == "SYN-Widget"
    assert widget["line_count"] == "2"
    assert widget["total_units"] == "4"
    assert widget["total_net_value"] == "77.98"
    assert widget["total_profit_amount"] == "16.40"
    # No reference-price field exists anywhere in the canonical output.
    paths = session_store.session_paths(session_root, session_id)
    with open(os.path.join(paths.derived, "canonical_products.csv"), "rb") as handle:
        assert b"price" not in handle.read().lower()


def test_customers_sanitized_without_pii_or_destination_geo(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    customers = by_key(
        read_table(session_root, session_id, "canonical_customers.csv"), "customer_id"
    )
    assert sorted(customers) == [
        "SYN-CUST-01",
        "SYN-CUST-02",
        "SYN-CUST-03",
        "SYN-CUST-04",
    ]
    first = customers["SYN-CUST-01"]
    assert first["customer_segment"] == "CONSUMER"
    assert first["order_count"] == "1"
    assert first["total_net_value"] == "47.48"
    # No governed customer-side geo columns exist: always null, never
    # derived from destinations (ADR-016).
    assert first["customer_country"] == ""
    assert first["customer_state"] == ""
    assert first["customer_city"] == ""
    paths = session_store.session_paths(session_root, session_id)
    for name in (
        "canonical_customers.csv",
        "canonical_order_items.csv",
        "canonical_orders.csv",
    ):
        with open(os.path.join(paths.derived, name), "rb") as handle:
            raw = handle.read()
        for probe in (
            b"example.invalid",
            b"Buyer Latitude",
            b"Customer Email",
            b"Late_delivery_risk",
        ):
            assert probe not in raw
    # The report's derivation prose may name the audit-only field (never its
    # values); personal probes stay out of every artifact including it.
    with open(os.path.join(paths.derived, "canonical_report.json"), "rb") as handle:
        report_raw = handle.read()
    for probe in (b"example.invalid", b"Buyer Latitude", b"Customer Email"):
        assert probe not in report_raw


def test_issues_table_carries_detection_evidence(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    issues = read_table(session_root, session_id, "canonical_data_quality_issues.csv")
    assert set(issues.columns.tolist()) == {
        "rule_id",
        "severity",
        "count",
        "treatment",
        "blocked_stage",
        "message",
    }
    assert set(issues["rule_id"].tolist()) == {
        "DQ-KEY-002",
        "DQ-KEY-003",
        "DQ-CAT-002",
        "DQ-CAT-003",
        "DQ-CAT-005",
        "DQ-BUSINESS-003",
        "DQ-PRIVACY-001",
        "DQ-PRIVACY-002",
    }
    for probe in ("SYN-ITEM-101", "27.98", "Rocket", "example.invalid"):
        assert probe not in issues.to_csv()


def test_report_reconciliation_and_identity(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    artifact = canonical_report(session_root, session_id)
    assert artifact.status == "complete"
    assert artifact.blocker is None
    assert artifact.sourceRows == 6
    assert {table.table for table in artifact.tables} == {
        "order_items",
        "orders",
        "products",
        "customers_sanitized",
        "calendar",
        "data_quality_issues",
    }
    assert artifact.reconciliation.itemRows == 6
    assert artifact.reconciliation.itemsWithOrder == 6
    assert artifact.reconciliation.orderCount == 4
    assert artifact.reconciliation.linesInOrders == 6
    assert artifact.reconciliation.foreignKeysReconcile is True
    assert artifact.reconciliation.totalsReconcile is True
    assert artifact.derivations and artifact.notes
    # Every listed table verifies against its stored SHA.
    from app.profiling import sha256_file

    paths = session_store.session_paths(session_root, session_id)
    for table in artifact.tables:
        assert sha256_file(os.path.join(paths.root, table.name)) == table.sha256


def test_missing_days_derive_null_outcome_without_blocking(
    client: TestClient, session_root: str
) -> None:
    header = CANON_HEADER.split(",")
    cells = CANON_BYTES.decode().splitlines()[1].split(",")
    cells[header.index("Order Id")] = "SYN-ORDER-501"
    cells[header.index("Order Item Id")] = "SYN-ITEM-501"
    cells[header.index("Days for shipment (scheduled)")] = ""
    content = (CANON_HEADER + "\n" + ",".join(cells) + "\n").encode()
    session_id = upload_ok(client, content)
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "ANALYZING"
    )
    items = read_table(session_root, session_id, "canonical_order_items.csv")
    assert items["shipment_outcome"].tolist() == [""]
    assert items["is_late"].tolist() == [""]
    assert items["schedule_variance_days"].tolist() == [""]


def test_single_invalid_order_date_travels_as_null(
    client: TestClient, session_root: str
) -> None:
    header = CANON_HEADER.split(",")
    good = CANON_BYTES.decode().splitlines()[1].split(",")
    bad = list(good)
    bad[header.index("Order Id")] = "SYN-ORDER-502"
    bad[header.index("Order Item Id")] = "SYN-ITEM-502"
    bad[header.index("order date (DateOrders)")] = "not-a-date"
    content = (
        CANON_HEADER + "\n" + ",".join(good) + "\n" + ",".join(bad) + "\n"
    ).encode()
    session_id = upload_ok(client, content)
    # One parseable date exists: per-row failure travels, build completes.
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "ANALYZING"
    )
    items = by_key(
        read_table(session_root, session_id, "canonical_order_items.csv"),
        "order_item_id",
    )
    assert items["SYN-ITEM-502"]["order_timestamp"] == ""
    assert items["SYN-ITEM-502"]["order_date"] == ""
    calendar = read_table(session_root, session_id, "canonical_calendar.csv")
    assert "" not in calendar["date"].tolist()


# ---------------------------------------------------------------------------
# Blocker scope: KEY-001 blocks the whole build, GRAIN-001 blocks orders only
# ---------------------------------------------------------------------------


def _conflict_bytes() -> bytes:
    header = CANON_HEADER.split(",")
    first = CANON_BYTES.decode().splitlines()[1].split(",")
    second = list(first)
    second[header.index("Order Item Id")] = "SYN-ITEM-901"
    second[header.index("Product Card Id")] = "SYN-PROD-901"
    # Same order, conflicting shipment class: DQ-GRAIN-001, no first-row pick.
    second[header.index("Shipping Mode")] = "Same Day"
    return (CANON_HEADER + "\n" + ",".join(first) + "\n" + ",".join(second)).encode()


def test_duplicate_item_key_blocks_whole_build(
    client: TestClient, session_root: str
) -> None:
    header = CANON_HEADER.split(",")
    first = CANON_BYTES.decode().splitlines()[1].split(",")
    second = list(first)
    second[header.index("Order Id")] = "SYN-ORDER-902"
    content = (CANON_HEADER + "\n" + ",".join(first) + "\n" + ",".join(second)).encode()
    session_id = upload_ok(client, content)
    data = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert data["state"] == "CANONICALIZING"
    assert data["error"] is None
    artifact = canonical_report(session_root, session_id)
    assert artifact.status == "blocked"
    assert artifact.blocker is not None
    assert artifact.blocker.code == "DUPLICATE_ITEM_KEY"
    assert artifact.blocker.stage == "CANONICALIZING"
    assert artifact.blocker.scope == "order_items"
    assert artifact.tables == []
    # Nothing deduplicated downstream because nothing was built; raw retained
    # (governed gate, not a terminal failure).
    paths = session_store.session_paths(session_root, session_id)
    assert os.path.exists(paths.raw)
    assert sorted(os.listdir(paths.derived)) == [
        "canonical_report.json",
        "cleaned.csv",
        "cleaning_report.json",
        "profiling_report.json",
        "schema_report.json",
    ]
    # Rerun is a stable park, never progress and never a failure.
    rerun = canonical_service.run_canonicalization(session_id)
    assert rerun is not None and rerun.state == "CANONICALIZING"


def test_grain_conflict_blocks_orders_only(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, _conflict_bytes())
    data = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert data["state"] == "CANONICALIZING"
    assert data["error"] is None
    artifact = canonical_report(session_root, session_id)
    assert artifact.status == "blocked"
    assert artifact.blocker is not None
    assert artifact.blocker.code == "ORDER_INVARIANCE_CONFLICT"
    assert artifact.blocker.scope == "orders"
    built = {table.table for table in artifact.tables}
    assert built == {
        "order_items",
        "products",
        "customers_sanitized",
        "calendar",
        "data_quality_issues",
    }
    paths = session_store.session_paths(session_root, session_id)
    assert not os.path.exists(os.path.join(paths.derived, "canonical_orders.csv"))
    # Both conflicting lines retained: no dedupe, no first-row pick.
    items = read_table(session_root, session_id, "canonical_order_items.csv")
    assert len(items) == 2
    assert sorted(items["shipping_mode"].tolist()) == ["SAME_DAY", "STANDARD_CLASS"]
    assert os.path.exists(paths.raw)


def test_customer_segment_conflict_blocks_customers_only(
    client: TestClient, session_root: str
) -> None:
    header = CANON_HEADER.split(",")
    first = CANON_BYTES.decode().splitlines()[1].split(",")
    second = list(first)
    second[header.index("Order Id")] = "SYN-ORDER-903"
    second[header.index("Order Item Id")] = "SYN-ITEM-903"
    second[header.index("Customer Segment")] = "Home Office"
    content = (CANON_HEADER + "\n" + ",".join(first) + "\n" + ",".join(second)).encode()
    session_id = upload_ok(client, content)
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "CANONICALIZING"
    )
    artifact = canonical_report(session_root, session_id)
    assert artifact.blocker is not None
    assert artifact.blocker.code == "CUSTOMER_INVARIANCE_CONFLICT"
    assert artifact.blocker.stage == "CANONICALIZING"
    assert artifact.blocker.scope == "customers_sanitized"
    built = {table.table for table in artifact.tables}
    assert "orders" in built
    assert "products" in built
    assert "customers_sanitized" not in built
    # No fabrication on the way out: both conflicting lines retained with
    # their own segment values (no nulling, no dedupe, no first-row pick).
    items = read_table(session_root, session_id, "canonical_order_items.csv")
    assert len(items) == 2
    assert sorted(items["customer_segment"].tolist()) == ["CONSUMER", "HOME_OFFICE"]
    # Governed parked gate: raw retained, nothing terminal.
    paths = session_store.session_paths(session_root, session_id)
    assert os.path.exists(paths.raw)


def test_product_dim_conflict_blocks_products_only(
    client: TestClient, session_root: str
) -> None:
    header = CANON_HEADER.split(",")
    first = CANON_BYTES.decode().splitlines()[1].split(",")
    second = list(first)
    second[header.index("Order Id")] = "SYN-ORDER-904"
    second[header.index("Order Item Id")] = "SYN-ITEM-904"
    second[header.index("Product Name")] = "SYN-Other"
    content = (CANON_HEADER + "\n" + ",".join(first) + "\n" + ",".join(second)).encode()
    session_id = upload_ok(client, content)
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "CANONICALIZING"
    )
    artifact = canonical_report(session_root, session_id)
    assert artifact.blocker is not None
    assert artifact.blocker.code == "PRODUCT_INVARIANCE_CONFLICT"
    assert artifact.blocker.stage == "CANONICALIZING"
    assert artifact.blocker.scope == "products"
    built = {table.table for table in artifact.tables}
    assert "orders" in built
    assert "customers_sanitized" in built
    assert "products" not in built
    # No fabrication: both conflicting lines retained with their own product
    # names (no representative value, no nulling, no dedupe).
    items = read_table(session_root, session_id, "canonical_order_items.csv")
    assert len(items) == 2
    assert sorted(items["product_name"].tolist()) == ["SYN-Other", "SYN-Widget"]
    paths = session_store.session_paths(session_root, session_id)
    assert os.path.exists(paths.raw)


def test_invariance_blocker_codes_cannot_be_confused(
    client: TestClient, session_root: str
) -> None:
    """Order, product, and customer conflicts report distinct governed codes
    with distinct scopes (ADR-036): no reuse, no confusion."""
    header = CANON_HEADER.split(",")
    first = CANON_BYTES.decode().splitlines()[1].split(",")

    def variant(**changes: str) -> bytes:
        second = list(first)
        for column, value in changes.items():
            second[header.index(column)] = value
        body = "\n".join([CANON_HEADER, ",".join(first), ",".join(second)])
        return (body + "\n").encode()

    order_session = upload_ok(
        client,
        variant(
            **{
                "Order Item Id": "SYN-ITEM-901",
                "Product Card Id": "SYN-PROD-901",
                "Shipping Mode": "Same Day",
            }
        ),
    )
    product_session = upload_ok(
        client,
        variant(
            **{
                "Order Id": "SYN-ORDER-904",
                "Order Item Id": "SYN-ITEM-904",
                "Product Name": "SYN-Other",
            }
        ),
    )
    customer_session = upload_ok(
        client,
        variant(
            **{
                "Order Id": "SYN-ORDER-903",
                "Order Item Id": "SYN-ITEM-903",
                "Customer Segment": "Home Office",
            }
        ),
    )
    pairs = set()
    for session_id in (order_session, product_session, customer_session):
        blocker = canonical_report(session_root, session_id).blocker
        assert blocker is not None
        assert blocker.stage == "CANONICALIZING"
        pairs.add((blocker.code, blocker.scope))
    assert pairs == {
        ("ORDER_INVARIANCE_CONFLICT", "orders"),
        ("PRODUCT_INVARIANCE_CONFLICT", "products"),
        ("CUSTOMER_INVARIANCE_CONFLICT", "customers_sanitized"),
    }


def test_file_wide_unparseable_dates_block_items(
    client: TestClient, session_root: str
) -> None:
    header = CANON_HEADER.split(",")
    cells = CANON_BYTES.decode().splitlines()[1].split(",")
    cells[header.index("Order Id")] = "SYN-ORDER-905"
    cells[header.index("Order Item Id")] = "SYN-ITEM-905"
    cells[header.index("order date (DateOrders)")] = "not-a-date"
    content = (CANON_HEADER + "\n" + ",".join(cells) + "\n").encode()
    session_id = upload_ok(client, content)
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "CANONICALIZING"
    )
    artifact = canonical_report(session_root, session_id)
    assert artifact.status == "blocked"
    assert artifact.blocker is not None
    assert artifact.blocker.code == "DQ-DATE-001"
    assert artifact.blocker.scope == "order_items"
    assert artifact.tables == []


# ---------------------------------------------------------------------------
# Artifact integrity: corrupt/stale/foreign/partial/write-failure/recovery
# ---------------------------------------------------------------------------


def test_corrupt_canonical_report_is_recomputed_not_adopted(
    session_root: str,
) -> None:
    session_id = park_at_canonicalizing(session_root, CANON_BYTES)
    assert canonical_service.run_canonicalization(session_id) is not None
    paths = session_store.session_paths(session_root, session_id)
    with open(
        os.path.join(paths.derived, "canonical_report.json"), "w", encoding="utf-8"
    ) as handle:
        handle.write("{not valid json")
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    manifest.state = "CANONICALIZING"
    manifest.stage = "CANONICALIZING"
    manifest.canonicalArtifact = None
    session_store.write_manifest(paths, manifest)
    recomputed = canonical_service.run_canonicalization(session_id)
    assert recomputed is not None and recomputed.state == "ANALYZING"
    assert session_store.read_canonical_report(paths) is not None


def test_corrupt_canonical_table_is_rebuilt(
    session_root: str,
) -> None:
    session_id = park_at_canonicalizing(session_root, CANON_BYTES)
    assert canonical_service.run_canonicalization(session_id) is not None
    paths = session_store.session_paths(session_root, session_id)
    with open(os.path.join(paths.derived, "canonical_order_items.csv"), "ab") as handle:
        handle.write(b"corrupt,trailing,bytes\n")
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    manifest.state = "CANONICALIZING"
    manifest.stage = "CANONICALIZING"
    manifest.canonicalArtifact = None
    session_store.write_manifest(paths, manifest)
    rebuilt = canonical_service.run_canonicalization(session_id)
    assert rebuilt is not None and rebuilt.state == "ANALYZING"
    items = read_table(session_root, session_id, "canonical_order_items.csv")
    assert len(items) == 6


def test_tampered_raw_fails_terminally(session_root: str) -> None:
    session_id = park_at_canonicalizing(session_root, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    with open(paths.raw, "ab") as handle:
        handle.write(b"tamper,bytes\n")
    failed = canonical_service.run_canonicalization(session_id)
    assert failed is not None and failed.state == "FAILED"
    assert failed.error is not None
    assert failed.error.code == "INTERNAL_STAGE_ERROR"
    assert failed.error.stage == "CANONICALIZING"
    assert not os.path.exists(paths.raw)
    assert os.listdir(paths.derived) == []


def test_corrupt_cleaned_csv_fails_terminally(session_root: str) -> None:
    session_id = park_at_canonicalizing(session_root, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    with open(session_store.cleaned_path(paths), "ab") as handle:
        handle.write(b"corrupt,trailing,bytes\n")
    failed = canonical_service.run_canonicalization(session_id)
    assert failed is not None and failed.state == "FAILED"
    assert failed.error is not None
    assert failed.error.code == "INTERNAL_STAGE_ERROR"


def test_foreign_artifact_is_recomputed_not_adopted(session_root: str) -> None:
    first = park_at_canonicalizing(session_root, CANON_BYTES)
    assert canonical_service.run_canonicalization(first) is not None
    first_paths = session_store.session_paths(session_root, first)
    with open(
        os.path.join(first_paths.derived, "canonical_report.json"),
        encoding="utf-8",
    ) as handle:
        forged = handle.read()
    second = park_at_canonicalizing(session_root, CANON_BYTES)
    second_paths = session_store.session_paths(session_root, second)
    with open(
        os.path.join(second_paths.derived, "canonical_report.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(forged)
    recomputed = canonical_service.run_canonicalization(second)
    assert recomputed is not None and recomputed.state == "ANALYZING"
    artifact = canonical_report(session_root, second)
    assert artifact.sessionId == second


def test_stale_version_is_recomputed_not_adopted(session_root: str) -> None:
    import json

    session_id = park_at_canonicalizing(session_root, CANON_BYTES)
    assert canonical_service.run_canonicalization(session_id) is not None
    paths = session_store.session_paths(session_root, session_id)
    report_path = os.path.join(paths.derived, "canonical_report.json")
    with open(report_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["appVersion"] = "0.0.0-stale"
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    manifest.state = "CANONICALIZING"
    manifest.stage = "CANONICALIZING"
    manifest.canonicalArtifact = None
    session_store.write_manifest(paths, manifest)
    recomputed = canonical_service.run_canonicalization(session_id)
    assert recomputed is not None and recomputed.state == "ANALYZING"
    assert canonical_report(session_root, session_id).appVersion == settings.app_version


def test_partial_write_is_rebuilt(session_root: str) -> None:
    session_id = park_at_canonicalizing(session_root, CANON_BYTES)
    assert canonical_service.run_canonicalization(session_id) is not None
    paths = session_store.session_paths(session_root, session_id)
    os.remove(os.path.join(paths.derived, "canonical_orders.csv"))
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    manifest.state = "CANONICALIZING"
    manifest.stage = "CANONICALIZING"
    manifest.canonicalArtifact = None
    session_store.write_manifest(paths, manifest)
    rebuilt = canonical_service.run_canonicalization(session_id)
    assert rebuilt is not None and rebuilt.state == "ANALYZING"
    assert len(read_table(session_root, session_id, "canonical_orders.csv")) == 4


def test_report_write_failure_leaves_safe_rerunnable_state(
    session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = park_at_canonicalizing(session_root, CANON_BYTES)

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("injected report failure")

    real_write = session_store.write_canonical_report
    monkeypatch.setattr(session_store, "write_canonical_report", boom)
    stalled = canonical_service.run_canonicalization(session_id)
    assert stalled is not None and stalled.state == "CANONICALIZING"
    assert stalled.canonicalArtifact is None
    monkeypatch.setattr(session_store, "write_canonical_report", real_write)
    recovered = canonical_service.run_canonicalization(session_id)
    assert recovered is not None and recovered.state == "ANALYZING"


def test_manifest_write_failure_after_tables_adopted_on_rerun(
    session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = park_at_canonicalizing(session_root, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    calls = {"count": 0}
    real_write = session_store.write_manifest

    def flaky(
        target: session_store.SessionPaths, manifest: session_store.SessionManifest
    ) -> None:
        calls["count"] += 1
        if calls["count"] >= 1 and manifest.state == "ANALYZING":
            raise OSError("injected manifest failure")
        real_write(target, manifest)

    monkeypatch.setattr(session_store, "write_manifest", flaky)
    stalled = canonical_service.run_canonicalization(session_id)
    assert stalled is not None and stalled.state == "CANONICALIZING"
    assert session_store.read_canonical_report(paths) is not None
    monkeypatch.setattr(session_store, "write_manifest", real_write)
    adopted = canonical_service.run_canonicalization(session_id)
    assert adopted is not None and adopted.state == "ANALYZING"
    assert adopted.canonicalArtifact is not None


def test_completed_rerun_is_a_noop(session_root: str) -> None:
    session_id = park_at_canonicalizing(session_root, CANON_BYTES)
    first = canonical_service.run_canonicalization(session_id)
    assert first is not None and first.state == "ANALYZING"
    paths = session_store.session_paths(session_root, session_id)
    with open(
        os.path.join(paths.derived, "canonical_report.json"), encoding="utf-8"
    ) as handle:
        before = handle.read()
    second = canonical_service.run_canonicalization(session_id)
    assert second is not None and second.state == "ANALYZING"
    with open(
        os.path.join(paths.derived, "canonical_report.json"), encoding="utf-8"
    ) as handle:
        assert handle.read() == before


def test_recover_canonicalizing_sessions_covers_crash_window(
    session_root: str,
) -> None:
    os.makedirs(session_root, exist_ok=True)
    good = park_at_canonicalizing(session_root, CANON_BYTES)
    stale = park_at_canonicalizing(session_root, CANON_BYTES)
    stale_paths = session_store.session_paths(session_root, stale)
    stale_manifest = session_store.read_manifest(stale_paths)
    assert stale_manifest is not None
    stale_manifest.lastAccessedAt = (
        (datetime.now() - timedelta(days=3)).replace(microsecond=0).isoformat()
    )
    session_store.write_manifest(stale_paths, stale_manifest)
    assert canonical_service.recover_canonicalizing_sessions(session_root) == 1
    good_manifest = session_store.read_manifest(
        session_store.session_paths(session_root, good)
    )
    assert good_manifest is not None and good_manifest.state == "ANALYZING"
    assert os.path.isdir(stale_paths.root)


# ---------------------------------------------------------------------------
# Concurrency: CAS touches, duplicate workers, reset, forward-only
# ---------------------------------------------------------------------------


def test_status_touches_cannot_regress_canonicalizing(session_root: str) -> None:
    """Concurrent observational touches must not fail or regress the build."""
    import threading

    session_id = park_at_canonicalizing(session_root, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    errors: list[BaseException] = []

    def touch() -> None:
        try:
            for _ in range(25):
                current = session_store.read_manifest(paths)
                assert current is not None
                session_store.touch_manifest_if_current(
                    paths, current, session_store.utcnow_naive_iso()
                )
        except BaseException as exc:  # noqa: BLE001 - collected, then raised
            errors.append(exc)

    threads = [threading.Thread(target=touch) for _ in range(8)]
    for thread in threads:
        thread.start()
    done = canonical_service.run_canonicalization(session_id)
    for thread in threads:
        thread.join()
    assert not errors
    assert done is not None and done.state == "ANALYZING"
    final = session_store.read_manifest(paths)
    assert final is not None and final.state == "ANALYZING"
    assert session_store.read_canonical_report(paths) is not None


def test_duplicate_worker_invocation_is_safe(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    first = canonical_service.run_canonicalization(session_id)
    second = canonical_service.run_canonicalization(session_id)
    assert first is not None and second is not None
    assert first.state == second.state == "ANALYZING"
    canonical_service._CANONICALIZATION_IN_PROGRESS.add(session_id)
    try:
        assert canonical_service.run_canonicalization(session_id) is None
    finally:
        canonical_service._CANONICALIZATION_IN_PROGRESS.discard(session_id)


def test_reset_cannot_be_resurrected_by_workers(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 200
    assert canonical_service.run_canonicalization(session_id) is None
    assert canonical_service.recover_canonicalizing_sessions(session_root) == 0
    assert os.listdir(session_root) == []


def test_worker_exception_fails_terminally_and_releases_guard(
    session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = park_at_canonicalizing(session_root, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)

    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("injected compute failure")

    monkeypatch.setattr(canonical_service, "build_order_items", boom)
    failed = canonical_service.run_canonicalization(session_id)
    assert failed is not None and failed.state == "FAILED"
    assert failed.error is not None
    assert failed.error.code == "INTERNAL_STAGE_ERROR"
    assert failed.error.stage == "CANONICALIZING"
    assert not os.path.exists(paths.raw)
    assert os.listdir(paths.derived) == []
    assert not canonical_service._CANONICALIZATION_IN_PROGRESS
    again = canonical_service.run_canonicalization(session_id)
    assert again is not None and again.state == "FAILED"
