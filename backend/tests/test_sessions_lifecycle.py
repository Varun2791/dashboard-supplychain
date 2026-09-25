"""Phase-4 session lifecycle: expiry, restart sweep, and raw stability.

All time-dependent behavior is deterministic: tests freeze "now" or backdate
manifest timestamps instead of sleeping.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

import app.sessions as session_store
from app.config import settings
from app.main import app
from app.schemas import SessionManifest


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", root)
    return root


def upload(client: TestClient, content: bytes = b"a,b\n1,2\n") -> Response:
    return client.post(
        "/api/v1/sessions/uploads",
        files={"file": ("data.csv", content, "text/csv")},
    )


COMPATIBLE_BYTES = (
    Path(__file__).parent / "fixtures" / "v1_reference_synthetic.csv"
).read_bytes()


def backdate_last_access(session_root: str, session_id: str, days_ago: int) -> None:
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    old = (datetime.now() - timedelta(days=days_ago)).replace(microsecond=0).isoformat()
    manifest.lastAccessedAt = old
    session_store.write_manifest(paths, manifest)


def test_expired_session_returns_410_and_tree_is_removed(
    client: TestClient, session_root: str
) -> None:
    session_id = upload(client).json()["data"]["sessionId"]
    backdate_last_access(session_root, session_id, days_ago=2)
    response = client.get(f"/api/v1/sessions/{session_id}/status")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"
    paths = session_store.session_paths(session_root, session_id)
    assert not os.path.exists(paths.root)


def test_second_get_after_expiry_is_404_no_tombstone(
    client: TestClient, session_root: str
) -> None:
    """Expiry keeps no tombstone: 410 fires once at detection, then 404.

    ADR-028 fixes expiry as TTL plus sweeps that log counts only, so no
    per-session evidence is retained after cleanup. Callers must treat 404
    after a 410 as 'gone', not as a different session.
    """
    session_id = upload(client).json()["data"]["sessionId"]
    backdate_last_access(session_root, session_id, days_ago=2)
    first = client.get(f"/api/v1/sessions/{session_id}/status")
    assert first.status_code == 410
    second = client.get(f"/api/v1/sessions/{session_id}/status")
    assert second.status_code == 404
    assert second.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_fresh_session_is_not_expired(client: TestClient, session_root: str) -> None:
    session_id = upload(client).json()["data"]["sessionId"]
    manifest = session_store.read_manifest(
        session_store.session_paths(session_root, session_id)
    )
    assert manifest is not None
    assert session_store.is_expired(manifest, datetime.now()) is False


def test_status_refreshes_sliding_expiry(client: TestClient, session_root: str) -> None:
    """Each status read refreshes lastAccessedAt (sliding TTL)."""
    session_id = upload(client, COMPATIBLE_BYTES).json()["data"]["sessionId"]
    paths = session_store.session_paths(session_root, session_id)
    before = session_store.read_manifest(paths)
    assert before is not None
    backdate_last_access(session_root, session_id, days_ago=0)
    # lastAccessedAt is now ~now; a status read keeps the session alive.
    response = client.get(f"/api/v1/sessions/{session_id}/status")
    assert response.status_code == 200
    after = session_store.read_manifest(paths)
    assert after is not None
    assert after.lastAccessedAt >= before.lastAccessedAt


def _write_minimal_session(
    session_root: str,
    *,
    state: str = "VALIDATING",
    with_raw: bool = True,
    corrupt: bool = False,
) -> str:
    session_id = str(uuid.uuid4())
    paths = session_store.session_paths(session_root, session_id)
    os.makedirs(paths.derived)
    os.makedirs(paths.exports)
    if corrupt:
        with open(paths.manifest, "w", encoding="utf-8") as handle:
            handle.write("{not json")
    else:
        now = session_store.utcnow_naive_iso()
        manifest = session_store.build_manifest(
            session_id=session_id,
            filename_safe="data.csv",
            size_bytes=8,
            sha256_hex="0" * 64,
            encoding="utf-8",
            now=now,
        )
        manifest.state = state
        session_store.write_manifest(paths, manifest)
    if with_raw:
        with open(paths.raw, "wb") as handle:
            handle.write(b"a,b\n1,2\n")
    return session_id


def test_sweep_removes_corrupt_and_incomplete_trees(
    session_root: str,
) -> None:
    os.makedirs(session_root, exist_ok=True)
    corrupt_id = _write_minimal_session(session_root, corrupt=True)
    incomplete_id = str(uuid.uuid4())
    os.makedirs(session_store.session_paths(session_root, incomplete_id).root)
    outcome = session_store.sweep_sessions(session_root, datetime.now())
    assert outcome.removed_corrupt == 2
    assert outcome.kept == 0
    assert not os.path.exists(
        session_store.session_paths(session_root, corrupt_id).root
    )
    assert not os.path.exists(
        session_store.session_paths(session_root, incomplete_id).root
    )


def test_sweep_removes_terminal_failed_tree_including_raw(
    session_root: str,
) -> None:
    os.makedirs(session_root, exist_ok=True)
    failed_id = _write_minimal_session(session_root, state="FAILED")
    outcome = session_store.sweep_sessions(session_root, datetime.now())
    assert outcome.removed_failed == 1
    assert not os.path.exists(session_store.session_paths(session_root, failed_id).root)


def test_sweep_removes_expired_but_keeps_active(
    session_root: str,
) -> None:
    os.makedirs(session_root, exist_ok=True)
    old_id = _write_minimal_session(session_root)
    active_id = _write_minimal_session(session_root)
    backdate = (datetime.now() - timedelta(days=3)).replace(microsecond=0).isoformat()
    old_paths = session_store.session_paths(session_root, old_id)
    manifest = session_store.read_manifest(old_paths)
    assert manifest is not None
    manifest.lastAccessedAt = backdate
    session_store.write_manifest(old_paths, manifest)
    outcome = session_store.sweep_sessions(session_root, datetime.now())
    assert outcome.removed_expired == 1
    assert outcome.kept == 1
    assert not os.path.exists(old_paths.root)
    assert os.path.isdir(session_store.session_paths(session_root, active_id).root)


def test_sweep_ignores_non_uuid_entries(session_root: str) -> None:
    os.makedirs(session_root, exist_ok=True)
    stray = os.path.join(session_root, "not-a-session")
    os.makedirs(stray)
    outcome = session_store.sweep_sessions(session_root, datetime.now())
    assert outcome.scanned == 0
    assert os.path.isdir(stray)


def test_sweep_handles_missing_root() -> None:
    outcome = session_store.sweep_sessions("/nonexistent-root-xyz", datetime.now())
    assert outcome.scanned == 0


def test_raw_never_rewritten_by_status_or_polling(
    client: TestClient, session_root: str
) -> None:
    content = COMPATIBLE_BYTES
    session_id = upload(client, content).json()["data"]["sessionId"]
    paths = session_store.session_paths(session_root, session_id)
    raw_before = os.stat(paths.raw)
    for _ in range(3):
        assert client.get(f"/api/v1/sessions/{session_id}/status").status_code == 200
    with open(paths.raw, "rb") as handle:
        assert handle.read() == content
    raw_after = os.stat(paths.raw)
    assert (raw_before.st_mtime_ns, raw_before.st_size) == (
        raw_after.st_mtime_ns,
        raw_after.st_size,
    )


def test_manifest_model_rejects_personal_payload_shape() -> None:
    """The manifest schema has no field that could carry row contents."""
    allowed = {
        "sessionId",
        "appVersion",
        "schemaVersion",
        "filenameSafe",
        "bytes",
        "sha256",
        "encoding",
        "state",
        "stage",
        "progress",
        "createdAt",
        "updatedAt",
        "lastAccessedAt",
        "error",
        "schemaArtifact",
    }
    assert set(SessionManifest.model_fields) == allowed
