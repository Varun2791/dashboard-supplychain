"""Pydantic boundaries for Phase-4 ingestion and Phase-5 schema validation.

Phase 5 adds source-schema recognition metadata from `docs/api-contract.md`
and `docs/canonical-schema.md`. Still no supply-chain value semantics: every
model carries headers, mapping facts, states, and error facts only — never
row contents or cell values.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# Accepted lifecycle states (ADR-029). Phase 6 advances PROFILING sessions
# to CLEANING on success or FAILED on an unparseable body; later states
# belong to Phases 7-9.
STATE_UPLOADING = "UPLOADING"
STATE_VALIDATING = "VALIDATING"
STATE_PROFILING = "PROFILING"
STATE_CLEANING = "CLEANING"
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
    """Typed `manifest.json`: Phase-4/5-safe metadata only.

    Never stores row contents, cell values, personal fields, source paths,
    client IPs, or browser fingerprints. The schema report lives in the
    derived artifact referenced by `schemaArtifact`; the manifest carries
    only lifecycle state plus that pointer.
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
    schemaArtifact: str | None = None
    profileArtifact: str | None = None


class SchemaFieldMapping(BaseModel):
    """One classified source header (original text always preserved)."""

    source: str
    canonical: str | None
    fieldClass: str  # required | optional | redundant | excluded | unknown
    required: bool
    role: str


class SchemaMappingView(BaseModel):
    """Contract-exact mapping entry: `{source, canonical, class}` only.

    The API projects the full internal mapping to this view so the endpoint
    matches `docs/api-contract.md` exactly; richer detail stays in the
    derived artifact. Serializes under the contract key `"class"`.
    """

    source: str
    canonical: str | None
    fieldClass: str = Field(serialization_alias="class")


class SchemaTimestampContract(BaseModel):
    """Parser expectation recorded as metadata (Phase 5 parses nothing)."""

    canonicalField: str
    sourceHeader: str
    parse: str
    timezoneNaive: bool


class SchemaRuleOutcome(BaseModel):
    """A triggered header-level DQ rule (schema scope only, never values)."""

    ruleId: str
    severity: str
    message: str


class SchemaReport(BaseModel):
    """Deterministic schema-validation result: headers + registry only.

    Contains no row samples, cell values, or profiling statistics.
    """

    schemaReferenceId: str
    compatible: bool
    sourceGrain: str
    sourceColumns: list[str]
    mapping: list[SchemaFieldMapping]
    missingRequired: list[str]
    unrecognized: list[str]
    redundant: list[str]
    auditOnly: list[str]
    timestampContracts: list[SchemaTimestampContract]
    ruleOutcomes: list[SchemaRuleOutcome]
    appVersion: str
    schemaVersion: int
    decidedAt: str


class SchemaReportData(BaseModel):
    """`GET /sessions/{id}/schema` payload (contract-exact shape)."""

    sourceColumns: list[str]
    mapping: list[SchemaMappingView]
    missingCritical: list[str]


class SchemaReportResponse(BaseModel):
    """Success envelope for the schema report endpoint."""

    data: SchemaReportData
    meta: EnvelopeMeta
    error: None = None


class ProfileMissingness(BaseModel):
    """Per-field missing-value statistics (counts only, never values)."""

    field: str  # canonical field name
    source: str  # original source header
    missing: int
    total: int
    rate: float  # 0..1, rounded to 4 dp
    parseFailures: int  # non-missing values failing governed type parsing


class ProfileCardinality(BaseModel):
    """Per-field distinct-value count (counts only, never value lists)."""

    field: str
    source: str
    distinct: int  # distinct non-missing stripped values


class ProfileDuplicates(BaseModel):
    """Duplicate statistics: excess rows beyond first occurrence."""

    exact: int  # fully identical rows across profiled columns
    keyDupes: int  # rows sharing a duplicate Order Item Id


class InvarianceFieldConflicts(BaseModel):
    """Per-field order-invariance conflict count (orders affected)."""

    field: str
    conflictingOrders: int


class InvarianceConflicts(BaseModel):
    """Order-grain consistency summary (counts only)."""

    ordersChecked: int
    conflictingOrders: int
    byField: list[InvarianceFieldConflicts]


class ProfileData(BaseModel):
    """`GET /sessions/{id}/profile` payload (contract-exact shape).

    `columns` is the number of governed mapped fields assessed; profiling
    never reads unmapped extras. Carries counts only: no row samples, no
    cell values, no distinct-value lists, no personal fields.
    """

    rows: int
    columns: int
    grain: str
    missingness: list[ProfileMissingness]
    cardinality: list[ProfileCardinality]
    duplicates: ProfileDuplicates
    invarianceConflicts: InvarianceConflicts


class ProfileResponse(BaseModel):
    """Success envelope for the profile endpoint."""

    data: ProfileData
    meta: EnvelopeMeta
    error: None = None


class DataQualityIssue(BaseModel):
    """One triggered governed DQ rule (contract-exact shape).

    Counts affected rows (or columns for privacy rules, or orders for
    grain rules — see the rule catalogue notes). Messages name governed
    fields and counts only, never cell values.
    """

    ruleId: str
    severity: str  # ERROR | WARNING | INFO
    count: int
    treatment: str  # detected | flagged | excluded | unchanged (never fixed)
    blockedStage: str | None  # exact downstream stage gated, if any


class DataQualitySummary(BaseModel):
    """Aggregate counts over the evaluated PROFILING-stage rule set."""

    rulesEvaluated: int
    rulesTriggered: int
    errors: int
    warnings: int
    infos: int
    blockingIssues: int  # issues with a non-null blockedStage


class DataQualityData(BaseModel):
    """`GET /sessions/{id}/data-quality` payload (contract-exact shape)."""

    summary: DataQualitySummary
    issues: list[DataQualityIssue]


class DataQualityResponse(BaseModel):
    """Success envelope for the data-quality endpoint."""

    data: DataQualityData
    meta: EnvelopeMeta
    error: None = None


class RuleContext(BaseModel):
    """Per-rule audit context kept in the internal artifact only."""

    title: str
    fields: list[str]
    grain: str
    population: str


class ProfilingArtifact(BaseModel):
    """Derived `profiling_report.json`: profile + full DQ findings.

    Internal superset of the two public projections. Stores counts, rule
    IDs, severities, treatments, blocked stages, safe messages, versions,
    and timestamps — never row contents, cell values, or personal fields.
    """

    sessionId: str
    appVersion: str
    schemaVersion: int
    sourceSha256: str
    sourceRows: int
    mappedFields: int
    profile: ProfileData
    issues: list[DataQualityIssue]
    issueMessages: dict[str, str]  # ruleId -> safe message
    ruleContext: dict[str, RuleContext]  # ruleId -> audit context
    rulesEvaluated: list[str]
    rulesDeferred: list[str]
    profiledAt: str
