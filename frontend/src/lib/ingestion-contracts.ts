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
