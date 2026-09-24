"""Health-endpoint contract test (Phase 3 foundation)."""

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_health_returns_versions_and_limits() -> None:
    """GET /api/v1/health matches the envelope in docs/api-contract.md."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["data"] == {
        "appVersion": settings.app_version,
        "schemaVersion": settings.schema_version,
        "maxUploadMB": settings.max_upload_mb,
    }
    assert body["meta"] == {
        "appVersion": settings.app_version,
        "schemaVersion": settings.schema_version,
    }
