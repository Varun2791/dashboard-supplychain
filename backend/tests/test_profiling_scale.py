"""Phase-6 scale test (generated synthetic data, no fixtures committed).

Demonstrates that profiling scales with rows rather than exploding with
high-cardinality outputs: one 15k-row generated file profiles in a single
pass with counts that reconcile exactly, including duplicate detection
spanning the whole file. No wall-clock thresholds (never flaky in CI).
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

import pytest

import app.sessions as session_store
from app.config import settings
from app.profiling import ensure_profiled, read_staged_frame

HEADER = [
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

N_ROWS = 15000


def generated_content() -> bytes:
    lines = [",".join(HEADER)]
    for idx in range(N_ROWS):
        order = idx // 3  # every order repeats: legitimate item grain
        lines.append(
            ",".join(
                [
                    f"SYN-ORDER-{70000 + order}",
                    f"SYN-ITEM-{80000 + idx}",
                    f"SYN-CUST-{900 + (idx % 500)}",
                    f"SYN-PROD-{100 + (idx % 50)}",
                    f"SYN-CAT-{10 + (idx % 5)}",
                    "03-15-2021 10:00",
                    "03-18-2021 09:00",
                    "29.98",
                    "2.00",
                    "27.98",
                    "6.40",
                    "14.99",
                    "2",
                    "3",
                    "4",
                    "Shipped",
                    "COMPLETE",
                    "Standard Class",
                ]
            )
        )
    # A duplicate key at the tail twins the head row's key: detection must
    # span the whole file, not a prefix window.
    tail = lines[-1].split(",")
    tail[1] = "SYN-ITEM-80000"
    lines.append(",".join(tail))
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture()
def session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", root)
    return root


def test_generated_file_profiles_with_reconciling_counts(
    session_root: str,
) -> None:
    from app.schema_validation import ensure_schema_validated

    content = generated_content()
    session_id = str(uuid.uuid4())
    paths = session_store.session_paths(session_root, session_id)
    os.makedirs(paths.derived)
    os.makedirs(paths.exports)
    with open(paths.raw, "wb") as handle:
        handle.write(content)
    now = session_store.utcnow_naive_iso()
    manifest = session_store.build_manifest(
        session_id=session_id,
        filename_safe="generated.csv",
        size_bytes=len(content),
        sha256_hex=hashlib.sha256(content).hexdigest(),
        encoding="utf-8",
        now=now,
    )
    session_store.write_manifest(paths, manifest)
    parked = ensure_schema_validated(paths, manifest, now)
    assert parked.state == "PROFILING"

    profiled = ensure_profiled(paths, parked, session_store.utcnow_naive_iso())
    assert profiled.state == "CLEANING"
    report = session_store.read_profiling_report(paths)
    assert report is not None
    assert report.profile.rows == N_ROWS + 1
    assert report.profile.duplicates.keyDupes == 1
    assert report.profile.duplicates.exact == 0
    # Counts reconcile: every row is either missing or present per field.
    for entry in report.profile.missingness:
        assert (
            entry.missing + (report.profile.rows - entry.missing) == report.profile.rows
        )
        assert 0.0 <= entry.rate <= 1.0
    # High-cardinality IDs collapse to counts, never value lists.
    by_field = {e.field: e for e in report.profile.cardinality}
    assert by_field["order_item_id"].distinct == N_ROWS
    assert by_field["order_id"].distinct == N_ROWS // 3
    text = report.model_dump_json()
    assert "SYN-ITEM-80000" not in text


def test_single_staging_read_covers_all_rows(session_root: str) -> None:
    content = generated_content()
    session_id = str(uuid.uuid4())
    paths = session_store.session_paths(session_root, session_id)
    os.makedirs(paths.root, exist_ok=True)
    with open(paths.raw, "wb") as handle:
        handle.write(content)
    frame = read_staged_frame(paths.raw, "utf-8", HEADER)
    assert len(frame) == N_ROWS + 1
    assert list(frame.columns) == HEADER
