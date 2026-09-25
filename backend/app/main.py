"""FastAPI application (Phase 7: ingestion + schema + profiling + cleaning).

Exposes the liveness endpoint plus the upload/status/reset routes and the
schema, profile, data-quality, and cleaning-report routes from
`docs/api-contract.md`. Canonicalization, KPI, and export routes belong to
later phases and must not be added here.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.sessions import ingestion_error_envelope
from app.api.sessions import router as sessions_router
from app.cleaning import recover_cleaning_sessions
from app.config import settings
from app.ingestion_errors import IngestionError
from app.profiling import recover_profiling_sessions
from app.schema_validation import recover_validating_sessions
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
    """Restart recovery: sweep, then re-run validation left VALIDATING.

    Covers the crash window between a 202 response and its post-response
    task (interrupted tasks leave no queue behind by design). Validation
    recovery chains into profiling and cleaning, and further sweeps cover
    sessions left PROFILING or CLEANING by a restart; expired/corrupt trees
    are swept first, valid resumable sessions are never deleted, later
    stages never start.
    """
    sweep_sessions(settings.session_root, datetime.now())
    recover_validating_sessions(settings.session_root)
    recover_profiling_sessions(settings.session_root)
    recover_cleaning_sessions(settings.session_root)
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
