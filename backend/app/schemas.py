"""Pydantic boundaries for Phase-4 ingestion API and session manifests.

Phase 4 owns only the upload/status/reset contracts from
`docs/api-contract.md`. No supply-chain semantics live here: every model
carries transport metadata, hashes, sizes, states, and error facts only.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# Accepted lifecycle states (ADR-029). Phase 4 only ever writes UPLOADING
# transiently and VALIDATING on success; later states belong to Phases 5-9.
STATE_UPLOADING = "UPLOADING"
STATE_VALIDATING = "VALIDATING"
STATE_FAILED = "FAILED"
STATE_EXPIRED = "EXPIRED"

# Ordered forward states used for Phase-4 progress reporting. The session is
# left at VALIDATING because downstream stages do not exist yet.
FORWARD_STATES = (
    "UPLOADING",
    "VALIDATING",
    "PROFILING",
    "CLEANING",
    "CANONICALIZING",
    "ANALYZING",
    "READY",
)


class ApiErrorModel(BaseModel):
    """Machine-readable failure: code + failing stage + safe details."""

    code: str
    stage: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class EnvelopeMeta(BaseModel):
    """Envelope metadata. `sessionId` is null when no session exists."""

    appVersion: str
    schemaVersion: int
    generatedAt: str
    sessionId: str | None = None
    sessionState: str | None = None


class UploadAcceptedData(BaseModel):
    """`202 Accepted` payload for `POST /sessions/uploads`."""

    sessionId: str
    statusUrl: str
    filenameSafe: str
    bytes: int
    sha256: str
    encoding: str


class UploadAcceptedResponse(BaseModel):
    """Success envelope for an accepted upload."""

    data: UploadAcceptedData
    meta: EnvelopeMeta
    error: None = None


class SessionProgress(BaseModel):
    """Truthful Phase-4 progress: no downstream stage is faked as done."""

    completedStages: list[str] = Field(default_factory=list)
    currentStage: str
    remainingStages: list[str] = Field(default_factory=list)
    note: str


class SessionStatusData(BaseModel):
    """`GET /sessions/{id}/status` payload."""

    state: str
    stage: str
    progress: SessionProgress
    startedAt: str
    updatedAt: str
    error: ApiErrorModel | None = None


class SessionStatusResponse(BaseModel):
    """Success envelope for the status endpoint."""

    data: SessionStatusData
    meta: EnvelopeMeta
    error: None = None


class SessionDeletedData(BaseModel):
    """`DELETE /sessions/{id}` payload (idempotent)."""

    deleted: bool


class SessionDeletedResponse(BaseModel):
    """Success envelope for session reset."""

    data: SessionDeletedData
    meta: EnvelopeMeta
    error: None = None


class ErrorResponse(BaseModel):
    """Error envelope: `data` is always null, `error` carries the facts."""

    data: None = None
    meta: EnvelopeMeta
    error: ApiErrorModel


class SessionManifest(BaseModel):
    """Typed `manifest.json`: Phase-4-safe metadata only.

    Never stores row contents, cell values, personal fields, source paths,
    client IPs, or browser fingerprints.
    """

    sessionId: str
    appVersion: str
    schemaVersion: int
    filenameSafe: str
    bytes: int
    sha256: str
    encoding: str
    state: str
    stage: str
    progress: SessionProgress
    createdAt: str
    updatedAt: str
    lastAccessedAt: str
    error: ApiErrorModel | None = None
