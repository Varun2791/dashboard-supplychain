"""FastAPI application (Phase 3 foundation shell).

Exposes only the session-independent liveness endpoint from
`docs/api-contract.md`. Upload, profiling, cleaning, canonicalization,
KPI, and export routes belong to later phases and must not be added here.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import settings


class HealthData(BaseModel):
    """Liveness payload: versions and enforced limits."""

    appVersion: str
    schemaVersion: int
    maxUploadMB: int


class HealthMeta(BaseModel):
    """Envelope metadata (no session exists before upload)."""

    appVersion: str
    schemaVersion: int


class HealthResponse(BaseModel):
    """Typed success envelope for the health endpoint."""

    data: HealthData
    meta: HealthMeta
    error: None = None


app = FastAPI(title="Supply Chain Analytics API")


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return application versions and the enforced upload limit."""
    return HealthResponse(
        data=HealthData(
            appVersion=settings.app_version,
            schemaVersion=settings.schema_version,
            maxUploadMB=settings.max_upload_mb,
        ),
        meta=HealthMeta(
            appVersion=settings.app_version,
            schemaVersion=settings.schema_version,
        ),
        error=None,
    )
