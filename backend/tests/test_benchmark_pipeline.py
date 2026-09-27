"""Pipeline integration: synthetic SMALL data drives the real app to READY.

Exercises production code only (direct ``ensure_*`` stage chain plus
TestClient endpoints); no KPI or business logic is duplicated here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.sessions as session_store
from app.config import settings
from app.main import app
from benchmarks.generator import generate_dataset
from benchmarks.run import _drive_stage_chain


def test_small_synthetic_reaches_ready_with_served_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_dir = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", session_dir)
    created: list[str] = []
    try:
        dataset = generate_dataset(tier="small", seed=7, rows=1200)
        assert dataset.actual_rows == 1200
        session_id, stages = _drive_stage_chain(
            dataset.content, session_dir, "bench.csv"
        )
        created.append(session_id)
        for stage in (
            "validationDurationSeconds",
            "profilingDurationSeconds",
            "cleaningDurationSeconds",
            "canonicalizationDurationSeconds",
            "kpiDurationSeconds",
            "readyDurationSeconds",
        ):
            assert stages[stage] >= 0

        client = TestClient(app)
        status = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
        assert status["state"] == "READY"
        base = f"/api/v1/sessions/{session_id}"
        for url in (
            f"{base}/kpis/overview",
            f"{base}/kpis/delivery",
            f"{base}/kpis/commercial",
            f"{base}/filter-options",
            f"{base}/orders",
        ):
            response = client.get(url)
            assert response.status_code == 200, url

        created_export = client.post(f"{base}/exports", json={"kind": "orders"})
        assert created_export.status_code == 201
        export_id = created_export.json()["data"]["exportId"]
        download = client.get(f"{base}/exports/{export_id}")
        assert download.status_code == 200
        assert len(download.content) > 0

        manifest = session_store.read_manifest(
            session_store.session_paths(session_dir, session_id)
        )
        assert manifest is not None and manifest.state == "READY"
    finally:
        for sid in created:
            try:
                TestClient(app).delete(f"/api/v1/sessions/{sid}")
            except Exception:  # noqa: BLE001 - best-effort test cleanup
                pass


def test_benchmark_run_cleans_sessions_on_endpoint_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure after session creation still removes session trees (F3)."""
    import benchmarks.report as report_module
    import benchmarks.run as run_module

    monkeypatch.setattr(report_module, "default_scratch_dir", lambda: tmp_path)
    monkeypatch.setattr(report_module, "default_reports_dir", lambda: tmp_path / "r")
    monkeypatch.setattr(run_module, "default_scratch_dir", lambda: tmp_path)
    monkeypatch.setattr(run_module, "default_reports_dir", lambda: tmp_path / "r")
    monkeypatch.setattr(settings, "session_root", str(tmp_path / "sessions"))

    def _boom(client: object, url: str) -> tuple[int, float]:
        return 500, 0.0

    monkeypatch.setattr(run_module, "_get", _boom)
    code = run_module.main(
        ["--tier", "small", "--seed", "99", "--rows", "150", "--profile", "valid"]
    )
    assert code == 1
    sessions_dir = tmp_path / "sessions"
    assert not sessions_dir.is_dir() or list(sessions_dir.iterdir()) == []
