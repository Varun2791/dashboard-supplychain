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

/** `GET /sessions/{id}/profile` payload (contract shape; counts only). */
export interface ProfileData {
  rows: number;
  columns: number;
  grain: string;
  missingness: unknown[];
  cardinality: unknown[];
  duplicates: {
    exact: number;
    keyDupes: number;
  };
  invarianceConflicts: unknown;
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
