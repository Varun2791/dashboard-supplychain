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
# to CLEANING on success or FAILED on an unparseable body; Phase 7 advances
# CLEANING sessions to CANONICALIZING on success (parking there without
# performing canonicalization) or FAILED on terminal cleaning failure.
# Phase 8 advances CANONICALIZING sessions to ANALYZING on success (parking
# there without performing KPI analysis) while governed quality blocks keep
# the session parked at CANONICALIZING. READY belongs to Phase 9: the KPI
# engine advances ANALYZING sessions to READY on success.
STATE_UPLOADING = "UPLOADING"
STATE_VALIDATING = "VALIDATING"
STATE_PROFILING = "PROFILING"
STATE_CLEANING = "CLEANING"
STATE_CANONICALIZING = "CANONICALIZING"
STATE_ANALYZING = "ANALYZING"
STATE_READY = "READY"
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
    filters: dict[str, str] = {}


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
    cleaningArtifact: str | None = None
    canonicalArtifact: str | None = None
    kpiArtifact: str | None = None


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


class DimensionFieldConflicts(BaseModel):
    """Per-field dimension-invariance conflict count (keys affected)."""

    field: str
    conflictingKeys: int


class DimensionInvarianceConflicts(BaseModel):
    """Product/customer-grain consistency summary (counts only).

    Kept separate from the order-grain `InvarianceConflicts` model so no
    population is misrepresented: `keysChecked` counts distinct non-missing
    dimension keys, `conflictingKeys` counts keys with ≥2 distinct
    non-missing governed values in at least one invariant attribute.
    """

    keysChecked: int
    conflictingKeys: int
    byField: list[DimensionFieldConflicts]


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
    productInvarianceConflicts: DimensionInvarianceConflicts
    customerInvarianceConflicts: DimensionInvarianceConflicts


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


class CleaningStep(BaseModel):
    """One audited cleaning outcome (contract-exact shape).

    Counts describe detected observations only: `detected` always equals
    `fixed + flagged + excluded + unchanged` per step. Unaffected rows are
    never counted. Carries rule IDs, governed field names, and counts only —
    never cell values, row samples, or personal fields.
    """

    ruleId: str
    # Canonical field; comma-joined for multi-field rules, "" when column-grain.
    field: str
    detected: int
    fixed: int
    flagged: int
    excluded: int
    unchanged: int
    reason: str


class CleaningReportData(BaseModel):
    """`GET /sessions/{id}/cleaning-report` payload (contract-exact shape)."""

    steps: list[CleaningStep]


class CleaningReportResponse(BaseModel):
    """Success envelope for the cleaning-report endpoint."""

    data: CleaningReportData
    meta: EnvelopeMeta
    error: None = None


class CleaningTotals(BaseModel):
    """Session-level cleaning totals (rows distinct; step sums overlap by design)."""

    rows: int
    rowsWithPaddingDetected: int  # distinct rows with CAT-005 padding
    rowsFixed: int  # distinct rows with >= 1 trimmed cell
    cellsFixed: int  # total trimmed cells across governed label fields
    fieldsTrimmed: int  # governed label fields with >= 1 trimmed cell


class MoneyReconciliation(BaseModel):
    """Pre/post cleaning money totals: trim-only cleaning must not move these."""

    grossPre: str
    grossPost: str
    discountPre: str
    discountPost: str
    netPre: str
    netPost: str
    profitPre: str
    profitPost: str


class CleaningArtifact(BaseModel):
    """Derived `cleaning_report.json`: audit log + provenance (counts only).

    Internal superset of the public projection. Stores per-rule/field steps,
    totals, money reconciliation, output identity, versions, and timestamps —
    never row contents, cell values, or personal fields.
    """

    sessionId: str
    appVersion: str
    schemaVersion: int
    sourceSha256: str
    inputProfileArtifact: str
    inputProfiledAt: str
    inputSourceRows: int
    rulesEvaluated: list[str]
    steps: list[CleaningStep]
    totals: CleaningTotals
    reconciliation: MoneyReconciliation
    outputArtifact: str
    outputSha256: str
    outputBytes: int
    outputRows: int
    cleanedAt: str


class CanonicalTableIdentity(BaseModel):
    """One persisted canonical table: relative path, rows, SHA, columns."""

    name: str  # e.g. "derived/canonical_order_items.csv"
    table: str  # e.g. "order_items"
    rows: int
    sha256: str
    columns: list[str]


class CanonicalBlocker(BaseModel):
    """Governed quality gate that parked the build (counts only, no values)."""

    # DUPLICATE_ITEM_KEY | ORDER_INVARIANCE_CONFLICT |
    # PRODUCT_INVARIANCE_CONFLICT | CUSTOMER_INVARIANCE_CONFLICT | DQ-DATE-001
    code: str
    stage: str  # always CANONICALIZING for Phase-8 gates
    scope: str  # canonical entity(s) blocked, e.g. "order_items" or "orders"
    detail: str  # governed-field counts only, never cell values


class CanonicalReconciliation(BaseModel):
    """Item-aggregate reconciliation (sums/counts only; no KPI math)."""

    itemRows: int
    itemsWithOrder: int
    orderCount: int | None  # None when the orders build is blocked
    linesInOrders: int | None
    foreignKeysReconcile: bool | None  # None when orders are blocked
    totalsReconcile: bool | None  # None when orders are blocked


class CanonicalArtifact(BaseModel):
    """Derived `canonical_report.json`: build identity + gates (counts only).

    Internal superset: no public endpoint serves it in Phase 8. Stores
    per-table identity, blocker evidence, reconciliation, applied
    derivations, versions, and timestamps — never row contents, cell values,
    or personal fields.
    """

    sessionId: str
    appVersion: str
    schemaVersion: int
    sourceSha256: str
    sourceRows: int
    inputProfiledAt: str
    inputCleanedAt: str
    status: str  # "complete" | "blocked"
    blocker: CanonicalBlocker | None
    tables: list[CanonicalTableIdentity]
    reconciliation: CanonicalReconciliation
    derivations: list[str]
    notes: list[str]
    canonicalizedAt: str


class KpiResult(BaseModel):
    """One computed KPI (`docs/api-contract.md` kpis[] shape exactly).

    Value representation (api-contract section 6 plus the governed reading
    recorded in `app/kpis.py`): counts are integers; money is a 2-dp string
    with no currency symbol; rates are 4-dp fraction strings; day averages
    and per-order means are 2-dp strings. Unavailable KPIs carry
    `value: null`, `status: "unavailable"`, and a pinned-vocabulary reason —
    never zero. `missingDataCount` counts eligible-population rows excluded
    for a missing required field (kpi-contracts global rule).
    """

    id: str  # e.g. "kpi.ship.late_rate"
    label: str  # approved display label from docs/kpi-contracts.md
    value: int | str | None
    status: str  # "ok" | "unavailable"
    numerator: int | str | None
    denominator: int | str | None
    population: str
    exclusions: str
    reason: str | None = None
    missingDataCount: int = 0


class KpiArtifact(BaseModel):
    """Derived `kpi_report.json`: headline KPI results + build identity.

    Internal cache: the unfiltered headline set, computed once from the
    governed canonical tables. Filtered/grouped serving recomputes
    synchronously from the cached canonical tables (api-contract section 3)
    and is never persisted. Counts/aggregates only — never row contents,
    cell values, or personal fields.
    """

    sessionId: str
    appVersion: str
    schemaVersion: int
    sourceSha256: str
    sourceRows: int
    inputCanonicalizedAt: str
    inputTableShas: dict[str, str]
    status: str  # "complete"
    kpis: list[KpiResult]
    computedAt: str


class KpiTotals(BaseModel):
    """Overview `totals`: unfiltered headline population anchors.

    The underlying populations that filtered views reconcile against
    (PLAN Phase-9 exit criterion), formatted exactly like KPI values.
    """

    items: int
    orders: int
    eligibleOrders: int
    grossValue: str
    discountTotal: str
    netValue: str
    profitTotal: str
    units: int


class KpiOverviewData(BaseModel):
    """`GET /sessions/{id}/kpis/overview` payload (contract shape exactly)."""

    kpis: list[KpiResult]
    totals: KpiTotals


class KpiOverviewResponse(BaseModel):
    """Success envelope for headline commercial + shipment KPIs."""

    data: KpiOverviewData
    meta: EnvelopeMeta
    error: None = None


class KpiGroup(BaseModel):
    """One `by=` slice: the group key plus the re-sliced KPI set.

    Grouping re-slices numerator/denominator under identical formulas
    (kpi-contracts); per-group unavailable rules apply independently.
    `UNKNOWN_FLAGGED`/null group keys are excluded from splits (ADR-030).
    """

    key: str
    kpis: list[KpiResult]


class KpiDeliveryData(BaseModel):
    """`GET /sessions/{id}/kpis/delivery` payload (contract shape exactly)."""

    groups: list[KpiGroup]
    eligibleOrders: int
    exclusions: str


class KpiDeliveryResponse(BaseModel):
    """Success envelope for shipment breakdowns."""

    data: KpiDeliveryData
    meta: EnvelopeMeta
    error: None = None


class KpiWeightedRates(BaseModel):
    """Amount-weighted headline rates echoed on the commercial endpoint."""

    profitMargin: str | None
    discountRate: str | None


class KpiCommercialData(BaseModel):
    """`GET /sessions/{id}/kpis/commercial` payload (contract shape exactly)."""

    groups: list[KpiGroup]
    statusScope: str
    weightedRates: KpiWeightedRates


class KpiCommercialResponse(BaseModel):
    """Success envelope for value/profit/discount/units breakdowns."""

    data: KpiCommercialData
    meta: EnvelopeMeta
    error: None = None
