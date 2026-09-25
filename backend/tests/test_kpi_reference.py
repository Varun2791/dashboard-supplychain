"""Phase-9 golden and reference regression structure (synthetic by default).

Two tiers, kept explicitly separate:

A. Always-runnable synthetic golden tests: the full pipeline on the small
   `canonical_small.csv` fixture must keep cross-artifact reconciliation
   (canonical report <-> KPI artifact <-> endpoint payloads) and the
   governed algebraic invariants (late + on-schedule = eligible;
   early + exact = on-schedule; margin = profit / net from the same
   payload). No DataCo rows, no hardcoded reference controls.

B. Optional local reference regression: when the authorized public DataCo
   file is available locally, `SUPPLYCHAIN_REFERENCE_CSV` points at it and
   the complete `AGENTS.md` controls are verified end to end. The file is
   never committed, never downloaded by tests, and CI never depends on it
   (the test skips without the variable). Reference verification remains
   pending until that run executes.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.sessions as session_store
from app.config import settings
from app.main import app

CANON_BYTES = (Path(__file__).parent / "fixtures" / "canonical_small.csv").read_bytes()

REFERENCE_ENV_VAR = "SUPPLYCHAIN_REFERENCE_CSV"


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


def overview(client: TestClient, session_id: str) -> dict[str, dict]:
    response = client.get(f"/api/v1/sessions/{session_id}/kpis/overview")
    assert response.status_code == 200
    return {entry["id"]: entry for entry in response.json()["data"]["kpis"]}


def test_cross_artifact_totals_reconcile(client: TestClient, session_root: str) -> None:
    """Canonical reconciliation, KPI artifact, and endpoints agree."""
    session_id = upload_ok(client, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    canonical = session_store.read_canonical_report(paths)
    assert canonical is not None and canonical.status == "complete"
    assert canonical.reconciliation.totalsReconcile is True
    kpis = overview(client, session_id)
    assert kpis["kpi.items.count"]["value"] == canonical.reconciliation.itemRows
    assert kpis["kpi.orders.count"]["value"] == canonical.reconciliation.orderCount
    totals = client.get(f"/api/v1/sessions/{session_id}/kpis/overview").json()["data"][
        "totals"
    ]
    assert totals["netValue"] == kpis["kpi.value.net"]["value"]
    assert totals["profitTotal"] == kpis["kpi.profit.recorded"]["value"]
    assert (
        totals["eligibleOrders"] == kpis["kpi.orders.shipment_eligible_count"]["value"]
    )


def test_governed_algebraic_invariants_hold(
    client: TestClient, session_root: str
) -> None:
    """Late + on-schedule = eligible; early + exact = on-schedule."""
    session_id = upload_ok(client, CANON_BYTES)
    kpis = overview(client, session_id)
    eligible = kpis["kpi.orders.shipment_eligible_count"]["value"]
    assert (
        kpis["kpi.ship.late_count"]["value"]
        + kpis["kpi.ship.early_count"]["value"]
        + kpis["kpi.ship.exact_count"]["value"]
        == eligible
    )
    assert (
        kpis["kpi.ship.early_count"]["value"] + kpis["kpi.ship.exact_count"]["value"]
        == 2
    )
    assert Decimal(kpis["kpi.ship.on_schedule_rate"]["value"]) == (
        Decimal(2) / Decimal(eligible)
    ).quantize(Decimal("0.0001"))
    assert Decimal(kpis["kpi.ship.late_rate"]["value"]) == (
        Decimal(1) / Decimal(eligible)
    ).quantize(Decimal("0.0001"))
    assert Decimal(kpis["kpi.margin.profit"]["value"]) == (
        Decimal(kpis["kpi.profit.recorded"]["value"])
        / Decimal(kpis["kpi.value.net"]["value"])
    ).quantize(Decimal("0.0001"))


def test_reference_path_missing_means_pending() -> None:
    """The reference run stays pending without an authorized local file."""
    if REFERENCE_ENV_VAR in os.environ:
        pytest.skip("reference file configured; see test_dataco_reference_controls")
    assert REFERENCE_ENV_VAR not in os.environ


@pytest.mark.skipif(
    REFERENCE_ENV_VAR not in os.environ,
    reason="no authorized local DataCo file; reference verification pending",
)
def test_dataco_reference_controls(client: TestClient, session_root: str) -> None:
    """Full-file regression against the AGENTS.md controls (local only).

    Executes only when SUPPLYCHAIN_REFERENCE_CSV points at the unmodified
    public DataCo main CSV. Never runs in CI. Production code contains no
    constant from these expectations (ADR-020).
    """
    path = os.environ[REFERENCE_ENV_VAR]
    with open(path, "rb") as handle:
        content = handle.read()
    session_id = upload_ok(client, content)
    status = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert status["state"] == "READY", status
    kpis = overview(client, session_id)
    assert kpis["kpi.items.count"]["value"] == 180519
    assert kpis["kpi.orders.count"]["value"] == 65752
    assert kpis["kpi.orders.shipment_eligible_count"]["value"] == 62897
    assert kpis["kpi.customers.count"]["value"] == 20652
    assert kpis["kpi.products.count"]["value"] == 118
    assert kpis["kpi.units.total"]["value"] == 384079
    assert kpis["kpi.ship.late_count"]["value"] == 36048
    assert kpis["kpi.ship.early_count"]["value"] == 15127
    assert kpis["kpi.ship.exact_count"]["value"] == 11722
    assert kpis["kpi.value.gross"]["value"] == "36784735.01"
    assert kpis["kpi.value.discount"]["value"] == "3730378.40"
    assert kpis["kpi.value.net"]["value"] == "33054402.38"
    assert kpis["kpi.profit.recorded"]["value"] == "3966902.97"
    assert abs(
        Decimal(kpis["kpi.ship.late_rate"]["value"]) - Decimal("0.573127")
    ) < Decimal("0.0001")
    assert abs(
        Decimal(kpis["kpi.ship.on_schedule_rate"]["value"]) - Decimal("0.426873")
    ) < Decimal("0.0001")
    # Cancellation / fraud separation (ADR-013): strict, suspected-fraud,
    # and combined shipping-blocked counts reconcile (1367 + 1488 = 2855).
    strict = kpis["kpi.orders.strict_cancel_rate"]
    fraud = kpis["kpi.orders.fraud_rate"]
    blocked = kpis["kpi.orders.blocked_rate"]
    assert strict["numerator"] == 1367
    assert fraud["numerator"] == 1488
    assert blocked["numerator"] == 2855
    assert strict["numerator"] + fraud["numerator"] == blocked["numerator"]
    for entry in (strict, fraud, blocked):
        assert entry["denominator"] == 65752
    assert abs(Decimal(strict["value"]) - Decimal("0.0208")) < Decimal("0.0001")
    assert abs(Decimal(fraud["value"]) - Decimal("0.0226")) < Decimal("0.0001")
    assert abs(Decimal(blocked["value"]) - Decimal("0.0434")) < Decimal("0.0001")
    delivery = client.get(
        f"/api/v1/sessions/{session_id}/kpis/delivery?by=shipment_outcome"
    ).json()["data"]
    assert delivery["eligibleOrders"] == 62897
