import type {
  ApiErrorPayload,
  DataQualityData,
  ProfileData,
  SchemaReportData,
  SessionStatusData,
  UploadAcceptedData,
} from "@/lib/ingestion-contracts";

export type {
  ApiErrorPayload,
  DataQualityData,
  ProfileData,
  SchemaReportData,
  SessionStatusData,
  UploadAcceptedData,
};

/** Relative-first base URL: same-origin in production, Vite proxy in dev. */
const API_BASE: string =
  import.meta.env.VITE_API_BASE_URL !== undefined &&
  import.meta.env.VITE_API_BASE_URL !== ""
    ? String(import.meta.env.VITE_API_BASE_URL)
    : "";

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly details: Record<string, unknown> | null;

  constructor(
    status: number,
    message: string,
    code: string | null = null,
    details: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
  } | null;
}

function envelopeError(
  payload: unknown,
  fallback: string,
): {
  message: string;
  code: string | null;
  details: Record<string, unknown> | null;
} {
  if (typeof payload === "object" && payload !== null) {
    const envelope = payload as ErrorEnvelope;
    if (envelope.error !== undefined && envelope.error !== null) {
      return {
        message:
          typeof envelope.error.message === "string" &&
          envelope.error.message !== ""
            ? envelope.error.message
            : fallback,
        code:
          typeof envelope.error.code === "string" ? envelope.error.code : null,
        details:
          typeof envelope.error.details === "object" &&
          envelope.error.details !== null
            ? envelope.error.details
            : null,
      };
    }
  }
  return { message: fallback, code: null, details: null };
}

export interface UploadProgress {
  /** 0..1 while computable, null when the total is unknown. */
  fraction: number | null;
}

/**
 * Upload a CSV with byte-level progress where the browser supports it
 * (XMLHttpRequest upload events). Resolves with the 202 payload.
 */
export function uploadSession(
  file: File,
  onProgress?: (progress: UploadProgress) => void,
): Promise<UploadAcceptedData> {
  return new Promise<UploadAcceptedData>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/v1/sessions/uploads`);
    xhr.upload.onprogress = (event: ProgressEvent) => {
      if (onProgress === undefined) {
        return;
      }
      onProgress({
        fraction:
          event.lengthComputable && event.total > 0
            ? event.loaded / event.total
            : null,
      });
    };
    xhr.onreadystatechange = () => {
      if (xhr.readyState !== XMLHttpRequest.DONE) {
        return;
      }
      let payload: unknown;
      try {
        payload = xhr.responseText !== "" ? JSON.parse(xhr.responseText) : null;
      } catch {
        payload = null;
      }
      if (xhr.status === 202) {
        const data = (payload as { data?: UploadAcceptedData } | null)?.data;
        if (data !== undefined && data !== null) {
          resolve(data);
          return;
        }
        reject(new ApiRequestError(xhr.status, "Unexpected upload response."));
        return;
      }
      const { message, code, details } = envelopeError(
        payload,
        "The upload failed. Please try again.",
      );
      reject(new ApiRequestError(xhr.status, message, code, details));
    };
    xhr.onerror = () => {
      reject(
        new ApiRequestError(
          0,
          "Could not reach the local server. Start the backend and try again.",
        ),
      );
    };
    const form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  });
}

/** Read the Phase-4 session state (VALIDATING boundary; never faked READY). */
export async function fetchSessionStatus(
  sessionId: string,
): Promise<SessionStatusData> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/v1/sessions/${encodeURIComponent(sessionId)}/status`,
    );
  } catch {
    throw new ApiRequestError(
      0,
      "Could not reach the local server. Start the backend and try again.",
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (response.ok) {
    return (payload as { data: SessionStatusData }).data;
  }
  const { message, code, details } = envelopeError(
    payload,
    "Could not read the session status.",
  );
  throw new ApiRequestError(response.status, message, code, details);
}

/** Idempotent reset: delete the whole session tree on the server. */
export async function deleteSession(sessionId: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/v1/sessions/${encodeURIComponent(sessionId)}`,
      { method: "DELETE" },
    );
  } catch {
    throw new ApiRequestError(
      0,
      "Could not reach the local server. Start the backend and try again.",
    );
  }
  if (response.ok) {
    return;
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const { message, code, details } = envelopeError(
    payload,
    "Could not remove the session.",
  );
  throw new ApiRequestError(response.status, message, code, details);
}

interface SchemaWireMapping {
  source: string;
  canonical: string | null;
  class: string;
}

interface SchemaWireData {
  sourceColumns: string[];
  mapping: SchemaWireMapping[];
  missingCritical: string[];
}

/** Read the Phase-5 schema report (contract shape; `class` translated). */
export async function fetchSchemaReport(
  sessionId: string,
): Promise<SchemaReportData> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/v1/sessions/${encodeURIComponent(sessionId)}/schema`,
    );
  } catch {
    throw new ApiRequestError(
      0,
      "Could not reach the local server. Start the backend and try again.",
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (response.ok) {
    const data = (payload as { data: SchemaWireData }).data;
    return {
      sourceColumns: data.sourceColumns,
      mapping: data.mapping.map((entry) => ({
        source: entry.source,
        canonical: entry.canonical,
        fieldClass: entry.class,
      })),
      missingCritical: data.missingCritical,
    };
  }
  const { message, code, details } = envelopeError(
    payload,
    "Could not read the schema report.",
  );
  throw new ApiRequestError(response.status, message, code, details);
}

/** Read the Phase-6 pre-cleaning profile (contract shape; counts only). */
export async function fetchProfile(sessionId: string): Promise<ProfileData> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/v1/sessions/${encodeURIComponent(sessionId)}/profile`,
    );
  } catch {
    throw new ApiRequestError(
      0,
      "Could not reach the local server. Start the backend and try again.",
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (response.ok) {
    return (payload as { data: ProfileData }).data;
  }
  const { message, code, details } = envelopeError(
    payload,
    "Could not read the profiling report.",
  );
  throw new ApiRequestError(response.status, message, code, details);
}

/** Read the Phase-6 data-quality issues (contract shape; counts only). */
export async function fetchDataQuality(
  sessionId: string,
): Promise<DataQualityData> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/v1/sessions/${encodeURIComponent(sessionId)}/data-quality`,
    );
  } catch {
    throw new ApiRequestError(
      0,
      "Could not reach the local server. Start the backend and try again.",
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (response.ok) {
    return (payload as { data: DataQualityData }).data;
  }
  const { message, code, details } = envelopeError(
    payload,
    "Could not read the data-quality report.",
  );
  throw new ApiRequestError(response.status, message, code, details);
}
