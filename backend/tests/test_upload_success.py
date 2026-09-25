"""Phase-4 upload success paths (real HTTP through the FastAPI app)."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

import app.sessions as session_store
from app.config import settings
from app.main import app

VALID_CSV = b"order_id,product_id,quantity\n1,10,2\n2,11,1\n"


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


def test_valid_utf8_csv_returns_202_envelope(
    client: TestClient, session_root: str
) -> None:
    """Success shape: 202 + sessionId/statusUrl/filenameSafe/bytes/sha/enc."""
    response = post_csv(client, "orders.csv", VALID_CSV)
    assert response.status_code == 202
    body = response.json()
    assert body["error"] is None
    data = body["data"]
    assert uuid.UUID(data["sessionId"], version=4)
    assert data["statusUrl"] == f"/api/v1/sessions/{data['sessionId']}/status"
    assert data["filenameSafe"] == "orders.csv"
    assert data["bytes"] == len(VALID_CSV)
    assert data["sha256"] == hashlib.sha256(VALID_CSV).hexdigest()
    assert data["encoding"] == "utf-8"
    assert body["meta"]["sessionId"] == data["sessionId"]
    assert body["meta"]["sessionState"] == "VALIDATING"
    assert body["meta"]["appVersion"] == settings.app_version


def test_utf8_bom_csv_records_sig_encoding(
    client: TestClient, session_root: str
) -> None:
    """BOM input is accepted and recorded as utf-8-sig (bytes preserved)."""
    content = b"\xef\xbb\xbforder_id\n1\n"
    response = post_csv(client, "bom.csv", content)
    assert response.status_code == 202
    assert response.json()["data"]["encoding"] == "utf-8-sig"


def test_latin1_csv_records_latin1_encoding(
    client: TestClient, session_root: str
) -> None:
    """DataCo-compatible Latin-1 bytes (invalid UTF-8) decode via fallback."""
    content = "produit,quantité\ncafé,2\n".encode("latin-1")
    try:
        content.decode("utf-8-sig")
        raise AssertionError("fixture must not decode as UTF-8")
    except UnicodeDecodeError:
        pass
    response = post_csv(client, "latin1.csv", content)
    assert response.status_code == 202
    assert response.json()["data"]["encoding"] == "latin-1"


def test_dataco_shaped_headers_are_not_schema_gated(
    client: TestClient, session_root: str
) -> None:
    """Phase 4 accepts DataCo-like headers without Phase-5 validation."""
    content = (
        b"Order Id,Order Item Id,Customer Id,Sales,order date (DateOrders)\n"
        b"1001,1,7,29.99,01-02-2018 12:00\n"
    )
    response = post_csv(client, "dataco.csv", content)
    assert response.status_code == 202


def test_raw_is_byte_identical_hashed_and_read_only(
    client: TestClient, session_root: str
) -> None:
    """Immutability: exact bytes, matching SHA-256, read-only raw.csv."""
    response = post_csv(client, "orders.csv", VALID_CSV)
    session_id = response.json()["data"]["sessionId"]
    paths = session_store.session_paths(session_root, session_id)
    with open(paths.raw, "rb") as handle:
        stored = handle.read()
    assert stored == VALID_CSV
    assert hashlib.sha256(stored).hexdigest() == (response.json()["data"]["sha256"])
    mode = os.stat(paths.raw).st_mode
    assert mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
    assert not os.path.exists(paths.partial)
    assert os.path.isdir(paths.derived)
    assert os.path.isdir(paths.exports)


def test_manifest_carries_safe_metadata_only(
    client: TestClient, session_root: str
) -> None:
    """Manifest records versions/hash/size/encoding/state, never contents."""
    response = post_csv(client, "orders.csv", VALID_CSV)
    session_id = response.json()["data"]["sessionId"]
    manifest = session_store.read_manifest(
        session_store.session_paths(session_root, session_id)
    )
    assert manifest is not None
    assert manifest.sessionId == session_id
    assert manifest.appVersion == settings.app_version
    assert manifest.schemaVersion == settings.schema_version
    assert manifest.bytes == len(VALID_CSV)
    assert manifest.state == "VALIDATING"
    assert manifest.stage == "VALIDATING"
    assert manifest.error is None
    assert manifest.createdAt and manifest.lastAccessedAt


def test_status_reports_validating_boundary(
    client: TestClient, session_root: str
) -> None:
    """Status is truthful: VALIDATING with progress, no faked READY."""
    session_id = post_csv(client, "orders.csv", VALID_CSV).json()["data"]["sessionId"]
    response = client.get(f"/api/v1/sessions/{session_id}/status")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["state"] == "VALIDATING"
    assert data["stage"] == "VALIDATING"
    assert data["progress"]["currentStage"] == "VALIDATING"
    assert "READY" not in data["progress"]["completedStages"]
    assert data["startedAt"] and data["updatedAt"]
    assert data["error"] is None


def test_reset_is_idempotent_and_removes_tree(
    client: TestClient, session_root: str
) -> None:
    """DELETE removes the tree; repeats and post-delete status are safe."""
    session_id = post_csv(client, "orders.csv", VALID_CSV).json()["data"]["sessionId"]
    paths = session_store.session_paths(session_root, session_id)
    assert os.path.isdir(paths.root)
    first = client.delete(f"/api/v1/sessions/{session_id}")
    assert first.status_code == 200
    assert first.json()["data"] == {"deleted": True}
    assert not os.path.exists(paths.root)
    second = client.delete(f"/api/v1/sessions/{session_id}")
    assert second.status_code == 200
    assert client.get(f"/api/v1/sessions/{session_id}/status").status_code == (404)
