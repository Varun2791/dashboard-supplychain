"""Phase-6/7/8 lifecycle tests (synthetic data only, deterministic, no sleeps).

Covers: PROFILING -> CLEANING -> CANONICALIZING -> ANALYZING on success
(cleaning runs inline and chains canonicalization; KPI analysis never
starts), observational GETs, 409 pending behavior, terminal MALFORMED_CSV
failure with ADR-028 cleanup, restart recovery of PROFILING sessions,
duplicate-worker safety, reset no-resurrection, and idempotent reruns. HTTP
behavior goes through the FastAPI app; stage-level behavior calls the
service functions directly.
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
from app import profiling as profiling_service
from app.config import settings
from app.main import app
from app.schema_validation import ensure_schema_validated, run_schema_validation

CLEAN_BYTES = (Path(__file__).parent / "fixtures" / "profiling_clean.csv").read_bytes()
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


def upload_ok(client: TestClient, content: bytes) -> str:
    response = client.post(
        "/api/v1/sessions/uploads",
        files={"file": ("data.csv", content, "text/csv")},
    )
    assert response.status_code == 202
    return response.json()["data"]["sessionId"]


def park_at_profiling(session_root: str, content: bytes) -> str:
    """A PROFILING session with schema done but profiling never executed."""
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
    parked = ensure_schema_validated(paths, manifest, now)
    assert parked.state == "PROFILING"
    assert parked.profileArtifact is None
    return session_id


def test_success_advances_to_analyzing_and_stops(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CLEAN_BYTES)
    data = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert data["state"] == "ANALYZING"
    assert data["stage"] == "ANALYZING"
    assert data["error"] is None
    # Canonicalization ran; KPI analysis never starts: canonical artifacts
    # exist alongside cleaning artifacts, raw intact, no KPI output.
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
    with open(paths.raw, "rb") as handle:
        assert handle.read() == CLEAN_BYTES


def test_error_findings_do_not_block_cleaning(
    client: TestClient, session_root: str
) -> None:
    """ERRORs gating CANONICALIZATION/KPI_ANALYSIS travel; pipeline parks."""
    session_id = upload_ok(client, ISSUES_BYTES)
    data = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert data["state"] == "CANONICALIZING"
    quality = client.get(f"/api/v1/sessions/{session_id}/data-quality").json()["data"]
    blocked = [i for i in quality["issues"] if i["blockedStage"] is not None]
    assert {i["ruleId"] for i in blocked} == {
        "DQ-KEY-001",
        "DQ-DATE-001",
        "DQ-GRAIN-001",
        "DQ-GRAIN-004",
    }


def test_gets_are_observational_and_pending_is_409(
    client: TestClient, session_root: str
) -> None:
    session_id = park_at_profiling(session_root, CLEAN_BYTES)
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "PROFILING"
    )
    for route in ("profile", "data-quality", "cleaning-report"):
        response = client.get(f"/api/v1/sessions/{session_id}/{route}")
        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "NOT_READY"
        assert body["error"]["details"] == {"state": "PROFILING"}
    # Still pending afterwards: the GETs executed nothing.
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None and manifest.state == "PROFILING"
    assert manifest.profileArtifact is None
    assert not os.path.exists(os.path.join(paths.derived, "profiling_report.json"))


def test_failed_profiling_resurfaces_stored_error(
    client: TestClient, session_root: str
) -> None:
    header = REQUIRED_HEADER.encode()
    padding = b"9,9\n" * 300
    content = header + b"\n" + padding + b'"unclosed quote,2\n'
    session_id = upload_ok(client, content)
    status = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert status["state"] == "FAILED"
    assert status["error"]["code"] == "MALFORMED_CSV"
    assert status["error"]["stage"] == "PROFILING"
    for route in ("profile", "data-quality", "cleaning-report"):
        response = client.get(f"/api/v1/sessions/{session_id}/{route}")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "MALFORMED_CSV"
    # ADR-028 terminal cleanup: raw and derived gone, manifest retained.
    paths = session_store.session_paths(session_root, session_id)
    assert not os.path.exists(paths.raw)
    assert os.listdir(paths.derived) == []
    assert session_store.read_manifest(paths) is not None


def test_severity_filter_and_rejection(client: TestClient, session_root: str) -> None:
    session_id = upload_ok(client, ISSUES_BYTES)
    errors = client.get(
        f"/api/v1/sessions/{session_id}/data-quality?severity=ERROR"
    ).json()["data"]
    assert {i["ruleId"] for i in errors["issues"]} == {
        "DQ-KEY-001",
        "DQ-DATE-001",
        "DQ-GRAIN-001",
        "DQ-GRAIN-004",
    }
    # The summary always describes the full evaluated set.
    assert errors["summary"]["rulesTriggered"] == len(
        client.get(f"/api/v1/sessions/{session_id}/data-quality").json()["data"][
            "issues"
        ]
    )
    bogus = client.get(f"/api/v1/sessions/{session_id}/data-quality?severity=CRITICAL")
    assert bogus.status_code == 422
    assert bogus.json()["error"]["code"] == "INVALID_SEVERITY_FILTER"


def test_unknown_and_expired_sessions_on_new_endpoints(
    client: TestClient, session_root: str
) -> None:
    missing = str(uuid.uuid4())
    assert client.get(f"/api/v1/sessions/{missing}/profile").status_code == 404
    assert client.get(f"/api/v1/sessions/{missing}/data-quality").status_code == 404
    assert client.get("/api/v1/sessions/not-a-uuid/profile").status_code == 404
    session_id = upload_ok(client, CLEAN_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    manifest.lastAccessedAt = (
        (datetime.now() - timedelta(days=2)).replace(microsecond=0).isoformat()
    )
    session_store.write_manifest(paths, manifest)
    expired = client.get(f"/api/v1/sessions/{session_id}/profile")
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "SESSION_EXPIRED"


def test_recover_profiling_sessions_covers_crash_window(
    session_root: str,
) -> None:
    os.makedirs(session_root, exist_ok=True)
    good = park_at_profiling(session_root, CLEAN_BYTES)
    cleaned = park_at_profiling(session_root, CLEAN_BYTES)
    assert profiling_service.run_profiling(cleaned) is not None
    stale = park_at_profiling(session_root, CLEAN_BYTES)
    stale_paths = session_store.session_paths(session_root, stale)
    stale_manifest = session_store.read_manifest(stale_paths)
    assert stale_manifest is not None
    stale_manifest.lastAccessedAt = (
        (datetime.now() - timedelta(days=3)).replace(microsecond=0).isoformat()
    )
    session_store.write_manifest(stale_paths, stale_manifest)

    assert profiling_service.recover_profiling_sessions(session_root) == 1
    good_manifest = session_store.read_manifest(
        session_store.session_paths(session_root, good)
    )
    assert good_manifest is not None and good_manifest.state == "ANALYZING"
    # Expired leftovers are the sweep's job, not recovery's.
    assert os.path.isdir(stale_paths.root)


def test_duplicate_worker_invocation_is_safe(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CLEAN_BYTES)
    first = profiling_service.run_profiling(session_id)
    second = profiling_service.run_profiling(session_id)
    assert first is not None and second is not None
    assert first.state == second.state == "ANALYZING"
    paths = session_store.session_paths(session_root, session_id)
    with open(
        os.path.join(paths.derived, "profiling_report.json"), encoding="utf-8"
    ) as handle:
        assert handle.read()
    # A run already in progress is skipped, never duplicated.
    profiling_service._PROFILING_IN_PROGRESS.add(session_id)
    try:
        assert profiling_service.run_profiling(session_id) is None
    finally:
        profiling_service._PROFILING_IN_PROGRESS.discard(session_id)


def test_reset_cannot_be_resurrected_by_workers(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CLEAN_BYTES)
    assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 200
    assert profiling_service.run_profiling(session_id) is None
    assert run_schema_validation(session_id) is None
    assert profiling_service.recover_profiling_sessions(session_root) == 0
    assert os.listdir(session_root) == []


def test_rerun_after_cleaning_is_a_noop(client: TestClient, session_root: str) -> None:
    session_id = upload_ok(client, CLEAN_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    with open(
        os.path.join(paths.derived, "profiling_report.json"), encoding="utf-8"
    ) as handle:
        before = handle.read()
    manifest = profiling_service.run_profiling(session_id)
    assert manifest is not None and manifest.state == "ANALYZING"
    with open(
        os.path.join(paths.derived, "profiling_report.json"), encoding="utf-8"
    ) as handle:
        assert handle.read() == before


def test_concurrent_manifest_writes_never_fail(session_root: str) -> None:
    """Status touches racing pipeline transitions must not crash a rename.

    Regression: concurrent writers once shared one fixed `.tmp` name, so a
    status touch could unlink the pipeline's pending temp file between its
    create and rename (`FileNotFoundError`). Unique temp names keep every
    rename total; readers never see partial content.
    """
    import threading

    session_id = park_at_profiling(session_root, CLEAN_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    errors: list[BaseException] = []

    def touch() -> None:
        try:
            for _ in range(25):
                current = session_store.read_manifest(paths)
                assert current is not None
                # Production status touches use the CAS primitive
                # (GET /status): a raw full-manifest rewrite would model a
                # writer production forbids and could regress a transition
                # the pipeline has already written.
                session_store.touch_manifest_if_current(
                    paths, current, session_store.utcnow_naive_iso()
                )
        except BaseException as exc:  # noqa: BLE001 - collected, then raised
            errors.append(exc)

    threads = [threading.Thread(target=touch) for _ in range(8)]
    for thread in threads:
        thread.start()
    profiled = profiling_service.run_profiling(session_id)
    for thread in threads:
        thread.join()
    assert not errors
    assert profiled is not None and profiled.state == "ANALYZING"
    final = session_store.read_manifest(paths)
    assert final is not None and final.state == "ANALYZING"
    assert session_store.read_manifest(paths) is not None
    assert session_store.read_profiling_report(paths) is not None
    assert session_store.read_cleaning_report(paths) is not None


def test_torn_profiling_transition_is_adopted(
    client: TestClient, session_root: str
) -> None:
    """An artifact on disk without its manifest pointer still converges."""
    session_id = upload_ok(client, CLEAN_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None and manifest.state == "ANALYZING"
    manifest.state = "PROFILING"
    manifest.stage = "PROFILING"
    manifest.profileArtifact = None
    manifest.cleaningArtifact = None
    session_store.write_manifest(paths, manifest)
    adopted = profiling_service.run_profiling(session_id)
    assert adopted is not None and adopted.state == "ANALYZING"
    assert adopted.profileArtifact is not None


def test_artifact_write_failure_leaves_safe_rerunnable_state(
    session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case A: artifact write fails before rename → no false CLEANING."""
    session_id = park_at_profiling(session_root, CLEAN_BYTES)
    paths = session_store.session_paths(session_root, session_id)

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("injected artifact failure")

    real_write_report = session_store.write_profiling_report
    monkeypatch.setattr(session_store, "write_profiling_report", boom)
    stalled = profiling_service.run_profiling(session_id)
    assert stalled is not None and stalled.state == "PROFILING"
    assert stalled.profileArtifact is None
    assert session_store.read_profiling_report(paths) is None
    monkeypatch.setattr(session_store, "write_profiling_report", real_write_report)
    recovered = profiling_service.run_profiling(session_id)
    assert recovered is not None and recovered.state == "ANALYZING"


def test_manifest_write_failure_after_artifact_adopted_on_rerun(
    session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case B: artifact renamed but manifest update fails → adopt, no rework."""
    session_id = park_at_profiling(session_root, CLEAN_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    calls = {"count": 0}
    real_write = session_store.write_manifest

    def flaky(
        target: session_store.SessionPaths, manifest: session_store.SessionManifest
    ) -> None:
        calls["count"] += 1
        if calls["count"] >= 1 and manifest.state == "CLEANING":
            raise OSError("injected manifest failure")
        real_write(target, manifest)

    monkeypatch.setattr(session_store, "write_manifest", flaky)
    stalled = profiling_service.run_profiling(session_id)
    # Manifest write failed: pointer missing, state unchanged, no false claim.
    assert stalled is not None and stalled.state == "PROFILING"
    assert session_store.read_profiling_report(paths) is not None
    monkeypatch.setattr(session_store, "write_manifest", real_write)
    adopted = profiling_service.run_profiling(session_id)
    assert adopted is not None and adopted.state == "ANALYZING"
    assert adopted.profileArtifact is not None
    assert adopted.cleaningArtifact is not None
    assert adopted.canonicalArtifact is not None


def test_missing_or_tampered_raw_fails_safely(session_root: str) -> None:
    """Case E: raw gone or hash-mismatched → terminal failure, never parked."""
    gone = park_at_profiling(session_root, CLEAN_BYTES)
    gone_paths = session_store.session_paths(session_root, gone)
    os.remove(gone_paths.raw)
    failed = profiling_service.run_profiling(gone)
    assert failed is not None and failed.state == "FAILED"
    assert failed.error is not None
    assert failed.error.code == "INTERNAL_STAGE_ERROR"

    tampered = park_at_profiling(session_root, CLEAN_BYTES)
    tampered_paths = session_store.session_paths(session_root, tampered)
    with open(tampered_paths.raw, "ab") as handle:
        handle.write(b"tamper,bytes\n")
    failed_tampered = profiling_service.run_profiling(tampered)
    assert failed_tampered is not None and failed_tampered.state == "FAILED"
    assert failed_tampered.error is not None
    assert failed_tampered.error.code == "INTERNAL_STAGE_ERROR"


def test_corrupt_artifact_is_recomputed_not_trusted(session_root: str) -> None:
    """Case F: unreadable artifact JSON → full recompute, then parked."""
    session_id = park_at_profiling(session_root, CLEAN_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    with open(
        os.path.join(paths.derived, "profiling_report.json"), "w", encoding="utf-8"
    ) as handle:
        handle.write("{not valid json")
    recomputed = profiling_service.run_profiling(session_id)
    assert recomputed is not None and recomputed.state == "ANALYZING"
    assert session_store.read_profiling_report(paths) is not None


def test_foreign_artifact_is_recomputed_not_adopted(session_root: str) -> None:
    """A mismatched session/hash/version binding is never silently trusted."""
    session_id = park_at_profiling(session_root, CLEAN_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    assert profiling_service.run_profiling(session_id) is not None
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    artifact = session_store.read_profiling_report(paths)
    assert artifact is not None
    # Forge a binding mismatch and tear the pointer: the stale artifact must
    # be recomputed, and the tampered raw must then fail safely.
    artifact.sourceSha256 = "0" * 64
    session_store.write_profiling_report(paths, artifact)
    manifest.state = "PROFILING"
    manifest.stage = "PROFILING"
    manifest.profileArtifact = None
    session_store.write_manifest(paths, manifest)
    with open(paths.raw, "ab") as handle:
        handle.write(b"tamper,bytes\n")
    failed = profiling_service.run_profiling(session_id)
    assert failed is not None and failed.state == "FAILED"
