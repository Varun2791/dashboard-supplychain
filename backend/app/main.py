"""FastAPI application (Phase 4: foundation shell + CSV ingestion).

Exposes the session-independent liveness endpoint plus the Phase-4
upload/status/reset routes from `docs/api-contract.md`. Profiling, cleaning,
canonicalization, KPI, and export routes belong to later phases and must not
be added here.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.sessions import ingestion_error_envelope
from app.api.sessions import router as sessions_router
from app.config import settings
from app.ingestion_errors import IngestionError
from app.sessions import sweep_sessions


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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Restart sweep: remove corrupt/failed/expired trees, log counts only."""
    sweep_sessions(settings.session_root, datetime.now())
    yield


app = FastAPI(title="Supply Chain Analytics API", lifespan=lifespan)
app.include_router(sessions_router)


@app.exception_handler(IngestionError)
async def ingestion_error_handler(
    request: Request, exc: IngestionError
) -> JSONResponse:
    """Render domain failures as the contract error envelope."""
    envelope = ingestion_error_envelope(exc)
    return JSONResponse(status_code=exc.http_status, content=envelope.model_dump())


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
