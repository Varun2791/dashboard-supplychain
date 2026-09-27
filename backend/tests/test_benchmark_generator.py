"""Generator tests: schema validity, invariants, scenarios, determinism."""

from __future__ import annotations

import csv
import io

import pytest

from benchmarks.generator import (
    GENERATOR_VERSION,
    TIERS,
    generate_dataset,
    resolve_config,
)
from benchmarks.report import default_scratch_dir, ensure_within_scratch


def parse_rows(content: bytes) -> list[dict[str, str]]:
    text = io.StringIO(content.decode("utf-8"))
    reader = csv.DictReader(text)
    assert reader.fieldnames is not None
    return list(reader)


def test_header_matches_governed_benchmark_shape() -> None:
    """V1 benchmark header shape anchored to production registry authority.

    The 25 mapped headers come from `app.schema_registry` (18 required + 7
    optional); the 5 additions are test-owned benchmark columns. Total is
    exactly 30. This is the V1 benchmark header shape, not an external
    DataCo header claim.
    """
    from app import schema_registry

    dataset = generate_dataset(tier="small", seed=1, rows=50)
    header = dataset.content.decode("utf-8").splitlines()[0].split(",")
    governed = [e.source_header for e in schema_registry.REQUIRED_MAPPINGS]
    governed += [e.source_header for e in schema_registry.OPTIONAL_MAPPINGS]
    assert len(schema_registry.REQUIRED_MAPPINGS) == 18
    assert len(schema_registry.OPTIONAL_MAPPINGS) == 7
    additions = [
        "Order Customer Id",
        "Late_delivery_risk",
        "Warehouse Zone",
        "Customer Email",
        "Buyer Latitude",
    ]
    assert header == governed + additions
    assert len(header) == 30
    assert len(set(header)) == 30


def test_requested_row_count_exact() -> None:
    dataset = generate_dataset(tier="small", seed=7, rows=200)
    assert dataset.actual_rows == 200
    assert len(parse_rows(dataset.content)) == 200


def test_small_tier_default_row_count() -> None:
    dataset = generate_dataset(tier="small", seed=7)
    assert dataset.actual_rows == TIERS["small"]["rows"] == 5000


def test_order_item_key_unique_and_multiline_orders_exist() -> None:
    dataset = generate_dataset(tier="small", seed=11, rows=500)
    rows = parse_rows(dataset.content)
    item_ids = [row["Order Item Id"] for row in rows]
    assert len(set(item_ids)) == len(item_ids)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["Order Id"]] = counts.get(row["Order Id"], 0) + 1
    assert max(counts.values()) > 1
    assert any(count == 1 for count in counts.values())


def test_order_invariants_stable() -> None:
    dataset = generate_dataset(tier="small", seed=13, rows=500)
    rows = parse_rows(dataset.content)
    invariant_fields = (
        "Customer Id",
        "Order Status",
        "Shipping Mode",
        "Customer Segment",
        "order date (DateOrders)",
        "shipping date (DateOrders)",
        "Days for shipping (real)",
        "Days for shipment (scheduled)",
        "Order Country",
        "Order Region",
        "Market",
        "Delivery Status",
    )
    seen: dict[str, dict[str, str]] = {}
    for row in rows:
        order = row["Order Id"]
        if order not in seen:
            seen[order] = {field: row[field] for field in invariant_fields}
        else:
            for field in invariant_fields:
                assert seen[order][field] == row[field], field


def test_product_and_customer_invariants_stable() -> None:
    dataset = generate_dataset(tier="small", seed=17, rows=500)
    rows = parse_rows(dataset.content)
    product_seen: dict[str, tuple[str, str, str, str]] = {}
    customer_seen: dict[str, str] = {}
    for row in rows:
        product_key = (
            row["Product Category Id"],
            row["Department Name"],
            row["Category Name"],
            row["Product Name"],
        )
        if row["Product Card Id"] not in product_seen:
            product_seen[row["Product Card Id"]] = product_key
        else:
            assert product_seen[row["Product Card Id"]] == product_key
        if row["Customer Id"] not in customer_seen:
            customer_seen[row["Customer Id"]] = row["Customer Segment"]
        else:
            assert customer_seen[row["Customer Id"]] == row["Customer Segment"]


def test_scenario_populations_exist() -> None:
    dataset = generate_dataset(tier="small", seed=21, rows=2000)
    rows = parse_rows(dataset.content)
    late = early = exact = cancelled = strict = fraud = negative = 0
    for row in rows:
        if row["Delivery Status"] == "Shipping canceled":
            cancelled += 1
            continue
        actual = int(row["Days for shipping (real)"])
        scheduled = int(row["Days for shipment (scheduled)"])
        if actual > scheduled:
            late += 1
        elif actual < scheduled:
            early += 1
        else:
            exact += 1
        if row["Order Status"] == "CANCELED":
            strict += 1
        if row["Order Status"] == "SUSPECTED_FRAUD":
            fraud += 1
        if float(row["Benefit per order"]) < 0:
            negative += 1
    assert late > 0 and early > 0 and exact > 0
    assert cancelled > 0 and strict > 0 and fraud > 0 and negative > 0


def test_valid_arithmetic_consistent_to_the_cent() -> None:
    dataset = generate_dataset(tier="small", seed=23, rows=300)
    for row in parse_rows(dataset.content):
        gross = round(float(row["Sales"]) * 100)
        discount = round(float(row["Order Item Discount"]) * 100)
        net = round(float(row["Order Item Total"]) * 100)
        assert net == gross - discount


def test_no_real_personal_data_patterns() -> None:
    dataset = generate_dataset(tier="small", seed=29, rows=200)
    text = dataset.content.decode("utf-8")
    assert "@example.invalid" in text
    for token in ("@gmail.", "@yahoo.", "@hotmail.", "password", "DataCo"):
        assert token not in text
    assert GENERATOR_VERSION == "1"


def test_determinism_same_seed_same_sha() -> None:
    first = generate_dataset(tier="small", seed=31, rows=300)
    second = generate_dataset(tier="small", seed=31, rows=300)
    assert first.sha256 == second.sha256
    assert first.content == second.content


def test_determinism_different_seed_different_sha() -> None:
    first = generate_dataset(tier="small", seed=31, rows=300)
    second = generate_dataset(tier="small", seed=32, rows=300)
    assert first.sha256 != second.sha256


def test_tier_definitions_cover_governed_scales() -> None:
    assert TIERS["medium"]["rows"] == 75000
    assert TIERS["reference_count"]["rows"] == 180519
    assert TIERS["target"]["rows"] == 500000


def test_resolve_config_rejects_unknown_inputs() -> None:
    with pytest.raises(ValueError):
        resolve_config("huge", seed=1)
    with pytest.raises(ValueError):
        resolve_config("small", seed=1, profile="nope")
    with pytest.raises(ValueError):
        resolve_config("small", seed=1, rows=0)


def test_scratch_path_safety(tmp_path) -> None:  # type: ignore[no-untyped-def]
    outside = tmp_path / "escape.csv"
    with pytest.raises(ValueError):
        ensure_within_scratch(outside)
    allowed = ensure_within_scratch(outside, test_only=True)
    assert allowed.is_absolute()
    inside = default_scratch_dir() / "small-seed1.csv"
    assert ensure_within_scratch(inside) == inside.resolve()


def test_quality_stress_profile_is_deterministic_and_shaped() -> None:
    first = generate_dataset(tier="small", seed=5, rows=400, profile="quality-stress")
    second = generate_dataset(tier="small", seed=5, rows=400, profile="quality-stress")
    assert first.sha256 == second.sha256
    assert first.actual_rows == 400
    assert first.content.decode("utf-8").splitlines()[0].split(",") == (
        generate_dataset(tier="small", seed=5, rows=10)
        .content.decode("utf-8")
        .splitlines()[0]
        .split(",")
    )
    rows = parse_rows(first.content)
    mutated = sum(
        1
        for row in rows
        if row["Order Status"] == "BOGUS_STATUS"
        or row["shipping date (DateOrders)"] == ""
        or row["Product Name"] != row["Product Name"].strip()
        or row["Shipping Mode"] == "Second Class"
        or row["Customer Segment"] == "Corporate"
    )
    assert mutated > 0
    valid = generate_dataset(tier="small", seed=5, rows=400)
    assert valid.config.profile == "valid"
    assert first.content != valid.content


def test_quality_stress_triggers_real_detection_path(
    tmp_path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    """One representative stress run through production profiling/DQ."""
    import hashlib
    import os
    import uuid
    from pathlib import Path as _Path

    import app.sessions as session_store
    from app.config import settings
    from app.profiling import ensure_profiled
    from app.schema_validation import ensure_schema_validated

    session_root = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", session_root)
    dataset = generate_dataset(tier="small", seed=9, rows=600, profile="quality-stress")
    session_id = str(uuid.uuid4())
    paths = session_store.session_paths(session_root, session_id)
    os.makedirs(paths.derived)
    os.makedirs(paths.exports)
    with open(paths.raw, "wb") as handle:
        handle.write(dataset.content)
    now = session_store.utcnow_naive_iso()
    manifest = session_store.build_manifest(
        session_id=session_id,
        filename_safe="stress.csv",
        size_bytes=len(dataset.content),
        sha256_hex=hashlib.sha256(dataset.content).hexdigest(),
        encoding="utf-8",
        now=now,
    )
    session_store.write_manifest(paths, manifest)
    validated = ensure_schema_validated(paths, manifest, now)
    assert validated.state == "PROFILING"
    profiled = ensure_profiled(paths, validated, now)
    assert profiled.state == "CLEANING"
    report = session_store.read_profiling_report(paths)
    assert report is not None
    counts = {issue.ruleId: issue.count for issue in report.issues}
    assert (
        counts.get("DQ-CAT-001", 0) > 0
        or counts.get("DQ-CAT-002", 0) > 0
        or counts.get("DQ-CAT-003", 0) > 0
        or counts.get("DQ-NUM-002", 0) > 0
    )
    assert _Path(paths.raw).exists()


def test_scenario_populations_ignore_late_delivery_risk() -> None:
    """Outcome oracles derive from governed inputs, never Late_delivery_risk."""
    dataset = generate_dataset(tier="small", seed=21, rows=2000)
    text = dataset.content.decode("utf-8")
    header, *lines = text.splitlines()
    risk_index = header.split(",").index("Late_delivery_risk")
    scrubbed = [header]
    for line in lines:
        cells = line.split(",")
        cells[risk_index] = "0"
        scrubbed.append(",".join(cells))
    reparsed = parse_rows(("\n".join(scrubbed) + "\n").encode("utf-8"))

    def populations(rows: list[dict[str, str]]) -> tuple[int, ...]:
        late = early = exact = cancelled = strict = fraud = negative = 0
        for row in rows:
            if row["Delivery Status"] == "Shipping canceled":
                cancelled += 1
                continue
            actual = int(row["Days for shipping (real)"])
            scheduled = int(row["Days for shipment (scheduled)"])
            if actual > scheduled:
                late += 1
            elif actual < scheduled:
                early += 1
            else:
                exact += 1
            if row["Order Status"] == "CANCELED":
                strict += 1
            if row["Order Status"] == "SUSPECTED_FRAUD":
                fraud += 1
            if float(row["Benefit per order"]) < 0:
                negative += 1
        return (late, early, exact, cancelled, strict, fraud, negative)

    assert "Late_delivery_risk" in header.split(",")
    assert populations(parse_rows(dataset.content)) == populations(reparsed)
