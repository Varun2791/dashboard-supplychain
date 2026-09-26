/**
 * Phase-4 ingestion contract shapes (mirror of the backend envelope).
 * The frontend renders these; it never recomputes or redefines them.
 */
export interface ApiErrorPayload {
  code: string;
  stage: string;
  message: string;
  details: Record<string, unknown>;
}

export interface UploadAcceptedData {
  sessionId: string;
  statusUrl: string;
  filenameSafe: string;
  bytes: number;
  sha256: string;
  encoding: string;
}

export interface SessionProgress {
  completedStages: string[];
  currentStage: string;
  remainingStages: string[];
  note: string;
}

export interface SessionStatusData {
  state: string;
  stage: string;
  progress: SessionProgress;
  startedAt: string;
  updatedAt: string;
  error: ApiErrorPayload | null;
}

/** One contract-exact mapping entry (`class` translated to fieldClass). */
export interface SchemaFieldMapping {
  source: string;
  canonical: string | null;
  fieldClass: string;
}

/** `GET /sessions/{id}/schema` payload (contract shape). */
export interface SchemaReportData {
  sourceColumns: string[];
  mapping: SchemaFieldMapping[];
  missingCritical: string[];
}

/** Per-field missing-value statistics (contract shape; counts only). */
export interface ProfileMissingness {
  field: string;
  source: string;
  missing: number;
  total: number;
  rate: number;
  parseFailures: number;
}

/** Per-field distinct-value count (contract shape; counts only). */
export interface ProfileCardinality {
  field: string;
  source: string;
  distinct: number;
}

/** Order-grain consistency summary (contract shape; counts only). */
export interface ProfileInvarianceConflicts {
  ordersChecked: number;
  conflictingOrders: number;
  byField: Array<{ field: string; conflictingOrders: number }>;
}

/** Product/customer-grain consistency summary (contract shape; counts only). */
export interface ProfileDimensionConflicts {
  keysChecked: number;
  conflictingKeys: number;
  byField: Array<{ field: string; conflictingKeys: number }>;
}

/** `GET /sessions/{id}/profile` payload (contract shape; counts only). */
export interface ProfileData {
  rows: number;
  columns: number;
  grain: string;
  missingness: ProfileMissingness[];
  cardinality: ProfileCardinality[];
  duplicates: {
    exact: number;
    keyDupes: number;
  };
  invarianceConflicts: ProfileInvarianceConflicts;
  productInvarianceConflicts: ProfileDimensionConflicts;
  customerInvarianceConflicts: ProfileDimensionConflicts;
}

/** One data-quality issue (contract shape; counts only, never values). */
export interface DataQualityIssue {
  ruleId: string;
  severity: string;
  count: number;
  treatment: string;
  blockedStage: string | null;
}

/** `GET /sessions/{id}/data-quality` payload (contract shape). */
export interface DataQualityData {
  summary: {
    rulesEvaluated: number;
    rulesTriggered: number;
    errors: number;
    warnings: number;
    infos: number;
    blockingIssues: number;
  };
  issues: DataQualityIssue[];
}

/** One audited cleaning outcome (contract shape; counts only, never values). */
export interface CleaningStep {
  ruleId: string;
  field: string;
  detected: number;
  fixed: number;
  flagged: number;
  excluded: number;
  unchanged: number;
  reason: string;
}

/** `GET /sessions/{id}/cleaning-report` payload (contract shape). */
export interface CleaningReportData {
  steps: CleaningStep[];
}
