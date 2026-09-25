"""Phase-9 KPI lifecycle and serving tests (synthetic data only).

Covers: ANALYZING -> READY on success with the KPI artifact beside the
canonical tables, artifact identity and adoption (torn/corrupt/stale),
startup recovery, duplicate-worker safety, reset no-resurrection, rerun
idempotence, the overview/delivery/commercial endpoints (shapes, filters,
`by=` groupings, 409/404/410/422 behavior), and the canonical-blocker
smoke (parked builds never analyzed, endpoints stay 409 NOT_READY).

No DataCo rows are used; expectations recompute from the fixtures.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.sessions as session_store
from app import kpis as kpi_service
from app.config import settings
from app.main import app

CANON_BYTES = (Path(__file__).parent / "fixtures" / "canonical_small.csv").read_bytes()
ISSUES_BYTES = (
    Path(__file__).parent / "fixtures" / "profiling_issues.csv"
).read_bytes()


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
    assert canonicalized.canonicalArtifact is not None
    assert canonicalized.kpiArtifact is None
    return session_id


# ---------------------------------------------------------------------------
# Lifecycle: ANALYZING -> READY
# ---------------------------------------------------------------------------


def test_upload_settles_at_ready_with_kpi_artifact(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    data = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert data["state"] == "READY"
    assert data["stage"] == "READY"
    assert data["error"] is None
    assert data["progress"]["currentStage"] == "READY"
    assert "ANALYZING" in data["progress"]["completedStages"]
    paths = session_store.session_paths(session_root, session_id)
    assert os.path.isfile(os.path.join(paths.derived, "kpi_report.json"))
    manifest = session_store.read_manifest(paths)
    assert manifest is not None and manifest.kpiArtifact is not None
    artifact = session_store.read_kpi_report(paths)
    assert artifact is not None
    assert artifact.sessionId == session_id
    assert artifact.sourceSha256 == manifest.sha256
    assert artifact.appVersion == settings.app_version
    assert artifact.schemaVersion == settings.schema_version
    assert artifact.status == "complete"
    assert len(artifact.kpis) == 30
    canonical = session_store.read_canonical_report(paths)
    assert canonical is not None
    assert artifact.inputCanonicalizedAt == canonical.canonicalizedAt
    assert artifact.sourceRows == canonical.sourceRows
    assert set(artifact.inputTableShas) == {t.name for t in canonical.tables}
    with open(paths.raw, "rb") as handle:
        assert handle.read() == CANON_BYTES


def test_stored_headline_matches_recomputation(
    client: TestClient, session_root: str
) -> None:
    """Serving the stored headline equals recomputing it (deterministic)."""
    session_id = upload_ok(client, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    artifact = session_store.read_kpi_report(paths)
    assert artifact is not None
    tables = kpi_service.load_canonical_tables(paths)
    recomputed = kpi_service.compute_headline(tables)
    assert [k.model_dump() for k in artifact.kpis] == [
        k.model_dump() for k in recomputed
    ]


def test_torn_kpi_transition_is_adopted_not_recomputed(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    with open(os.path.join(paths.derived, "kpi_report.json"), "rb") as handle:
        before = handle.read()
    manifest = session_store.read_manifest(paths)
    assert manifest is not None and manifest.state == "READY"
    manifest.state = "ANALYZING"
    manifest.stage = "ANALYZING"
    manifest.kpiArtifact = None
    session_store.write_manifest(paths, manifest)
    adopted = kpi_service.run_kpi_analysis(session_id)
    assert adopted is not None and adopted.state == "READY"
    assert adopted.kpiArtifact is not None
    with open(os.path.join(paths.derived, "kpi_report.json"), "rb") as handle:
        assert handle.read() == before


def test_corrupt_kpi_report_is_recomputed(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    with open(
        os.path.join(paths.derived, "kpi_report.json"), "w", encoding="utf-8"
    ) as handle:
        handle.write("{not valid json")
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    manifest.state = "ANALYZING"
    manifest.stage = "ANALYZING"
    manifest.kpiArtifact = None
    session_store.write_manifest(paths, manifest)
    recomputed = kpi_service.run_kpi_analysis(session_id)
    assert recomputed is not None and recomputed.state == "READY"
    assert session_store.read_kpi_report(paths) is not None


def test_stale_version_is_recomputed_not_adopted(
    client: TestClient, session_root: str
) -> None:
    import json

    session_id = upload_ok(client, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    report_path = os.path.join(paths.derived, "kpi_report.json")
    with open(report_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["appVersion"] = "0.0.0-stale"
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    manifest.state = "ANALYZING"
    manifest.stage = "ANALYZING"
    manifest.kpiArtifact = None
    session_store.write_manifest(paths, manifest)
    recomputed = kpi_service.run_kpi_analysis(session_id)
    assert recomputed is not None and recomputed.state == "READY"
    reread = session_store.read_kpi_report(paths)
    assert reread is not None
    assert reread.appVersion == settings.app_version


def test_recover_analyzing_sessions_covers_crash_window(
    session_root: str,
) -> None:
    os.makedirs(session_root, exist_ok=True)
    # True crash window: canonical done, KPI report never written.
    session_id = park_at_analyzing(session_root, CANON_BYTES)
    assert kpi_service.recover_analyzing_sessions(session_root) == 1
    recovered = session_store.read_manifest(
        session_store.session_paths(session_root, session_id)
    )
    assert recovered is not None and recovered.state == "READY"
    # Settled sessions are skipped; parked CANONICALIZING sessions are
    # never analyzed; expired trees are the sweep's job.
    assert kpi_service.recover_analyzing_sessions(session_root) == 0


def test_recovery_adopts_orphaned_kpi_report(
    client: TestClient, session_root: str
) -> None:
    """Torn write (report persisted, manifest not updated) settles READY."""
    session_id = upload_ok(client, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    with open(os.path.join(paths.derived, "kpi_report.json"), "rb") as handle:
        before = handle.read()
    manifest = session_store.read_manifest(paths)
    assert manifest is not None and manifest.state == "READY"
    manifest.state = "ANALYZING"
    manifest.stage = "ANALYZING"
    manifest.kpiArtifact = None
    session_store.write_manifest(paths, manifest)
    assert kpi_service.recover_analyzing_sessions(session_root) == 1
    reread = session_store.read_manifest(paths)
    assert reread is not None and reread.state == "READY"
    assert reread.kpiArtifact is not None
    with open(os.path.join(paths.derived, "kpi_report.json"), "rb") as handle:
        assert handle.read() == before


def test_recovery_recomputes_corrupt_orphaned_report(
    client: TestClient, session_root: str
) -> None:
    """A corrupt orphaned report is recomputed, never adopted."""
    session_id = upload_ok(client, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None and manifest.state == "READY"
    with open(os.path.join(paths.derived, "kpi_report.json"), "wb") as handle:
        handle.write(b"{not valid json")
    manifest.state = "ANALYZING"
    manifest.stage = "ANALYZING"
    manifest.kpiArtifact = None
    session_store.write_manifest(paths, manifest)
    assert kpi_service.recover_analyzing_sessions(session_root) == 1
    reread = session_store.read_manifest(paths)
    assert reread is not None and reread.state == "READY"
    artifact = session_store.read_kpi_report(paths)
    assert artifact is not None and len(artifact.kpis) == 30


def test_duplicate_worker_invocation_is_safe(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    first = kpi_service.run_kpi_analysis(session_id)
    second = kpi_service.run_kpi_analysis(session_id)
    assert first is not None and second is not None
    assert first.state == second.state == "READY"
    kpi_service._KPI_ANALYSIS_IN_PROGRESS.add(session_id)
    try:
        assert kpi_service.run_kpi_analysis(session_id) is None
    finally:
        kpi_service._KPI_ANALYSIS_IN_PROGRESS.discard(session_id)


def test_reset_cannot_be_resurrected_by_workers(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 200
    assert kpi_service.run_kpi_analysis(session_id) is None
    assert kpi_service.recover_analyzing_sessions(session_root) == 0
    assert os.listdir(session_root) == []


def test_rerun_is_byte_identical(client: TestClient, session_root: str) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    with open(os.path.join(paths.derived, "kpi_report.json"), "rb") as handle:
        before = handle.read()
    rerun = kpi_service.run_kpi_analysis(session_id)
    assert rerun is not None and rerun.state == "READY"
    with open(os.path.join(paths.derived, "kpi_report.json"), "rb") as handle:
        assert handle.read() == before


def test_artifact_write_failure_stays_rerunnable(
    session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = park_at_analyzing(session_root, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("injected kpi failure")

    real_write = session_store.write_kpi_report
    monkeypatch.setattr(session_store, "write_kpi_report", boom)
    stalled = kpi_service.run_kpi_analysis(session_id)
    assert stalled is not None and stalled.state == "ANALYZING"
    assert stalled.kpiArtifact is None
    assert session_store.read_kpi_report(paths) is None
    monkeypatch.setattr(session_store, "write_kpi_report", real_write)
    recovered = kpi_service.run_kpi_analysis(session_id)
    assert recovered is not None and recovered.state == "READY"


# ---------------------------------------------------------------------------
# Endpoints: shapes, filters, groupings, errors
# ---------------------------------------------------------------------------


def test_overview_shape_and_totals(client: TestClient, session_root: str) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    response = client.get(f"/api/v1/sessions/{session_id}/kpis/overview")
    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert len(data["kpis"]) == 30
    for entry in data["kpis"]:
        assert set(entry) >= {
            "id",
            "label",
            "value",
            "status",
            "numerator",
            "denominator",
            "population",
            "exclusions",
        }
        assert entry["label"] == kpi_service.KPI_LABELS[entry["id"]]
    totals = data["totals"]
    assert totals["items"] == 6
    assert totals["orders"] == 4
    assert totals["eligibleOrders"] == 3
    assert totals["grossValue"] == "129.98"
    assert totals["discountTotal"] == "6.50"
    assert totals["netValue"] == "123.48"
    assert totals["profitTotal"] == "15.15"
    assert totals["units"] == 9
    assert body["meta"]["sessionState"] == "READY"
    assert body["meta"]["filters"] == {}


def test_overview_filter_narrows_and_echoes(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    response = client.get(f"/api/v1/sessions/{session_id}/kpis/overview?region=South")
    assert response.status_code == 200
    body = response.json()
    entry = {k["id"]: k for k in body["data"]["kpis"]}
    # Only SYN-ORDER-200 (South) survives: exact on-schedule, net 50.00.
    assert entry["kpi.items.count"]["value"] == 1
    assert entry["kpi.orders.count"]["value"] == 1
    assert entry["kpi.value.net"]["value"] == "50.00"
    assert entry["kpi.ship.late_rate"]["value"] == "0.0000"
    assert entry["kpi.ship.late_rate"]["status"] == "ok"
    assert "region=South" in entry["kpi.value.net"]["population"]
    assert body["meta"]["filters"] == {"region": "South"}
    assert body["data"]["totals"]["netValue"] == "50.00"


def test_filtered_overview_narrows_entity_counts(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    plain = {
        k["id"]: k
        for k in client.get(f"/api/v1/sessions/{session_id}/kpis/overview").json()[
            "data"
        ]["kpis"]
    }
    assert plain["kpi.customers.count"]["value"] == 4
    assert plain["kpi.products.count"]["value"] == 4
    narrowed = {
        k["id"]: k
        for k in client.get(
            f"/api/v1/sessions/{session_id}/kpis/overview?region=South"
        ).json()["data"]["kpis"]
    }
    # Only SYN-ORDER-200 (SYN-CUST-02, SYN-PROD-A) survives the filter.
    assert narrowed["kpi.customers.count"]["value"] == 1
    assert narrowed["kpi.products.count"]["value"] == 1
    assert narrowed["kpi.value.net"]["value"] == "50.00"


def test_empty_filter_result_is_unavailable_not_error(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    response = client.get(
        f"/api/v1/sessions/{session_id}/kpis/overview?from=2025-01-01&to=2025-12-31"
    )
    assert response.status_code == 200
    entry = {k["id"]: k for k in response.json()["data"]["kpis"]}
    assert entry["kpi.ship.late_rate"]["status"] == "unavailable"
    assert entry["kpi.ship.late_rate"]["value"] is None
    assert entry["kpi.orders.count"]["status"] == "unavailable"


def test_unknown_filter_and_grouping_rejected(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    bogus = client.get(
        f"/api/v1/sessions/{session_id}/kpis/overview?shipping_mode=ROCKET"
    )
    assert bogus.status_code == 422
    assert bogus.json()["error"]["code"] == "INVALID_FILTER_VALUE"
    bad_date = client.get(f"/api/v1/sessions/{session_id}/kpis/overview?from=nope")
    assert bad_date.status_code == 422
    assert bad_date.json()["error"]["code"] == "INVALID_FILTER_VALUE"
    bad_group = client.get(f"/api/v1/sessions/{session_id}/kpis/delivery?by=warehouse")
    assert bad_group.status_code == 422
    assert bad_group.json()["error"]["code"] == "INVALID_GROUPING"


def test_delivery_grouping_reconciles(client: TestClient, session_root: str) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    response = client.get(
        f"/api/v1/sessions/{session_id}/kpis/delivery?by=shipment_outcome"
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["eligibleOrders"] == 3
    assert "1 shipping-cancelled orders excluded" in data["exclusions"]
    groups = {g["key"]: {k["id"]: k for k in g["kpis"]} for g in data["groups"]}
    assert set(groups) == {"LATE", "EARLY", "ON_SCHEDULE", "SHIPPING_CANCELED"}
    # Group numerators sum to the headline numerators (order grain kept).
    assert sum(g["kpi.ship.late_count"]["value"] for g in groups.values()) == 1
    assert sum(g["kpi.ship.early_count"]["value"] for g in groups.values()) == 1
    assert groups["LATE"]["kpi.ship.late_rate"]["value"] == "1.0000"
    assert groups["LATE"]["kpi.ship.late_rate"]["denominator"] == 1
    # The shipping-cancelled group carries no adherence population, but its
    # governed all-orders cancellation denominators stay exact.
    cancelled = groups["SHIPPING_CANCELED"]
    assert cancelled["kpi.ship.late_rate"]["status"] == "unavailable"
    assert cancelled["kpi.ship.late_rate"]["value"] is None
    assert cancelled["kpi.orders.blocked_rate"]["value"] == "1.0000"
    assert cancelled["kpi.orders.blocked_rate"]["numerator"] == 1
    assert cancelled["kpi.orders.blocked_rate"]["denominator"] == 1
    assert cancelled["kpi.orders.strict_cancel_rate"]["value"] == "1.0000"
    assert cancelled["kpi.orders.fraud_rate"]["value"] == "0.0000"
    # Adherence groups see no cancellations in their all-orders slice.
    assert groups["LATE"]["kpi.orders.blocked_rate"]["value"] == "0.0000"


def test_commercial_grouping_excludes_unknown_splits(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    response = client.get(
        f"/api/v1/sessions/{session_id}/kpis/commercial?by=customer_segment"
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["statusScope"] == "all-status"
    assert data["weightedRates"]["profitMargin"] == "0.1227"
    assert data["weightedRates"]["discountRate"] == "0.0500"
    groups = {g["key"]: {k["id"]: k for k in g["kpis"]} for g in data["groups"]}
    # Enterprise maps to UNKNOWN_FLAGGED: counted in the headline but
    # excluded from split KPIs (ADR-030).
    assert set(groups) == {"CONSUMER", "HOME_OFFICE"}
    # All-status commercial scope: CONSUMER holds orders 100 (47.48) and
    # the cancelled order 400 (17.00).
    assert groups["CONSUMER"]["kpi.value.net"]["value"] == "64.48"
    assert groups["HOME_OFFICE"]["kpi.value.net"]["value"] == "50.00"


def test_commercial_status_scope_labels_filter(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CANON_BYTES)
    response = client.get(
        f"/api/v1/sessions/{session_id}/kpis/commercial?order_status=CANCELED"
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["statusScope"] == "order_status=CANCELED"
    groups = data["groups"]
    assert groups == []


def test_kpi_endpoints_reject_unknown_and_expired(
    client: TestClient, session_root: str
) -> None:
    missing = str(uuid.uuid4())
    for route in ("kpis/overview", "kpis/delivery", "kpis/commercial"):
        assert client.get(f"/api/v1/sessions/{missing}/{route}").status_code == 404
    session_id = upload_ok(client, CANON_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    manifest.lastAccessedAt = (
        (datetime.now() - timedelta(days=2)).replace(microsecond=0).isoformat()
    )
    session_store.write_manifest(paths, manifest)
    expired = client.get(f"/api/v1/sessions/{session_id}/kpis/overview")
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "SESSION_EXPIRED"


def test_kpi_endpoints_resurface_terminal_error(
    client: TestClient, session_root: str
) -> None:
    response = client.post(
        "/api/v1/sessions/uploads",
        files={"file": ("orders.csv", b"a,b\n1,2\n", "text/csv")},
    )
    session_id = response.json()["data"]["sessionId"]
    status = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert status["state"] == "FAILED"
    for route in ("kpis/overview", "kpis/delivery", "kpis/commercial"):
        failed = client.get(f"/api/v1/sessions/{session_id}/{route}")
        assert failed.status_code == 422
        assert failed.json()["error"]["code"] == "SCHEMA_MISSING_COLUMN"


# ---------------------------------------------------------------------------
# Canonical-blocker smoke: parked builds are never analyzed
# ---------------------------------------------------------------------------


def test_blocked_build_is_never_analyzed(client: TestClient, session_root: str) -> None:
    session_id = upload_ok(client, ISSUES_BYTES)
    status = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert status["state"] == "CANONICALIZING"
    paths = session_store.session_paths(session_root, session_id)
    assert not os.path.exists(os.path.join(paths.derived, "kpi_report.json"))
    manifest = session_store.read_manifest(paths)
    assert manifest is not None and manifest.kpiArtifact is None
    for route in ("kpis/overview", "kpis/delivery", "kpis/commercial"):
        parked = client.get(f"/api/v1/sessions/{session_id}/{route}")
        assert parked.status_code == 409
        body = parked.json()
        assert body["error"]["code"] == "NOT_READY"
        assert body["error"]["stage"] == "ANALYZING"
        assert body["error"]["details"] == {"state": "CANONICALIZING"}
    # The blocker was not bypassed by a worker rerun either.
    assert kpi_service.run_kpi_analysis(session_id) is not None
    reread = session_store.read_manifest(paths)
    assert reread is not None and reread.state == "CANONICALIZING"
    assert not os.path.exists(os.path.join(paths.derived, "kpi_report.json"))
