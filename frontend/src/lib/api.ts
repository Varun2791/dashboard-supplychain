import type {
  ApiErrorPayload,
  CleaningReportData,
  DataQualityData,
  FilterOptionsData,
  KpiCommercialData,
  KpiDeliveryData,
  KpiGroup,
  KpiOverviewData,
  KpiResult,
  OrdersData,
  OrderRow,
  ProfileData,
  SchemaReportData,
  SessionStatusData,
  UploadAcceptedData,
} from "@/lib/ingestion-contracts";

export type {
  ApiErrorPayload,
  CleaningReportData,
  DataQualityData,
  FilterOptionsData,
  KpiCommercialData,
  KpiDeliveryData,
  KpiGroup,
  KpiOverviewData,
  KpiResult,
  OrdersData,
  OrderRow,
  ProfileData,
  SchemaReportData,
  SessionStatusData,
  UploadAcceptedData,
};

/**
 * Shared Phase-15 analytics filter query (ADR-038 subset, contract §5).
 * Single value per dimension; absent means "All". `department` and
 * `customer_segment` stay accepted backend parameters but are not Phase-15
 * UI filters, so they never appear here.
 */
export interface FilterQuery {
  from?: string;
  to?: string;
  market?: string;
  region?: string;
  category?: string;
  shipping_mode?: string;
  order_status?: string;
  shipment_outcome?: string;
}

/**
 * One shared serialization path for active analytics filters (contract §5
 * query names). Inactive/All values are omitted — never sent as empty
 * strings, "All", or undefined text. Used identically by overview,
 * delivery, commercial, and orders requests: no per-view reinterpretation.
 */
export function serializeFilters(query: FilterQuery): string {
  const params = new URLSearchParams();
  const entries: Array<[string, string | undefined]> = [
    ["from", query.from],
    ["to", query.to],
    ["market", query.market],
    ["region", query.region],
    ["category", query.category],
    ["shipping_mode", query.shipping_mode],
    ["order_status", query.order_status],
    ["shipment_outcome", query.shipment_outcome],
  ];
  for (const [name, value] of entries) {
    if (value !== undefined && value !== "") {
      params.set(name, value);
    }
  }
  return params.toString();
}

/** Append serialized active filters to a path (`?`/`&` handled). */
function withFilters(path: string, filters?: FilterQuery): string {
  if (filters === undefined) {
    return path;
  }
  const serialized = serializeFilters(filters);
  if (serialized === "") {
    return path;
  }
  return path.includes("?") ? `${path}&${serialized}` : `${path}?${serialized}`;
}

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

/** Read the Phase-7 cleaning audit log (contract shape; counts only). */
export async function fetchCleaningReport(
  sessionId: string,
): Promise<CleaningReportData> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/v1/sessions/${encodeURIComponent(sessionId)}/cleaning-report`,
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
    return (payload as { data: CleaningReportData }).data;
  }
  const { message, code, details } = envelopeError(
    payload,
    "Could not read the cleaning report.",
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

/** Read the Phase-9 headline commercial + shipment KPIs (contract shape). */
export async function fetchKpisOverview(
  sessionId: string,
  filters?: FilterQuery,
): Promise<KpiOverviewData> {
  let response: Response;
  try {
    response = await fetch(
      withFilters(
        `${API_BASE}/api/v1/sessions/${encodeURIComponent(sessionId)}/kpis/overview`,
        filters,
      ),
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
    return (payload as { data: KpiOverviewData }).data;
  }
  const { message, code, details } = envelopeError(
    payload,
    "Could not read the headline KPIs.",
  );
  throw new ApiRequestError(response.status, message, code, details);
}

/** Read Phase-9 shipment KPIs with a governed `by=` grouping (contract shape). */
export async function fetchKpisDelivery(
  sessionId: string,
  by: string | null,
  filters?: FilterQuery,
): Promise<KpiDeliveryData> {
  const query = by !== null ? `?by=${encodeURIComponent(by)}` : "";
  let response: Response;
  try {
    response = await fetch(
      withFilters(
        `${API_BASE}/api/v1/sessions/${encodeURIComponent(sessionId)}/kpis/delivery${query}`,
        filters,
      ),
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
    return (payload as { data: KpiDeliveryData }).data;
  }
  const { message, code, details } = envelopeError(
    payload,
    "Could not read the shipment KPIs.",
  );
  throw new ApiRequestError(response.status, message, code, details);
}

/** Read Phase-9 commercial KPIs with a governed `by=` grouping (contract shape). */
export async function fetchKpisCommercial(
  sessionId: string,
  by: string | null,
  filters?: FilterQuery,
): Promise<KpiCommercialData> {
  const query = by !== null ? `?by=${encodeURIComponent(by)}` : "";
  let response: Response;
  try {
    response = await fetch(
      withFilters(
        `${API_BASE}/api/v1/sessions/${encodeURIComponent(sessionId)}/kpis/commercial${query}`,
        filters,
      ),
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
    return (payload as { data: KpiCommercialData }).data;
  }
  const { message, code, details } = envelopeError(
    payload,
    "Could not read the commercial KPIs.",
  );
  throw new ApiRequestError(response.status, message, code, details);
}

/**
 * Read the Phase-15 open filter domains + date extent (ADR-038, contract
 * §3). Session-wide and non-cascading: no filter parameters are accepted,
 * so the UNFILTERED session domain is always returned.
 */
export async function fetchFilterOptions(
  sessionId: string,
): Promise<FilterOptionsData> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/v1/sessions/${encodeURIComponent(sessionId)}/filter-options`,
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
    const data = (payload as { data: unknown }).data;
    if (!isFilterOptionsData(data)) {
      throw new ApiRequestError(
        response.status,
        "The filter options had an unexpected shape.",
        null,
        null,
      );
    }
    return data;
  }
  const { message, code, details } = envelopeError(
    payload,
    "Could not read the filter options.",
  );
  throw new ApiRequestError(response.status, message, code, details);
}

/** Producer-realistic shape guard: never trust a 200 payload blindly. */
function isFilterOptionsData(data: unknown): data is FilterOptionsData {
  if (typeof data !== "object" || data === null) {
    return false;
  }
  const record = data as Record<string, unknown>;
  const range = record.dateRange;
  if (typeof range !== "object" || range === null) {
    return false;
  }
  const rangeRecord = range as Record<string, unknown>;
  for (const key of ["minOrderDate", "maxOrderDate"]) {
    const value = rangeRecord[key];
    if (value !== null && typeof value !== "string") {
      return false;
    }
  }
  for (const key of ["markets", "regions", "categories"]) {
    const value = record[key];
    if (
      !Array.isArray(value) ||
      value.some((entry) => typeof entry !== "string")
    ) {
      return false;
    }
  }
  return true;
}

export interface OrdersQuery extends FilterQuery {
  limit?: number;
  /** Opaque producer cursor; absent starts at the first page. Never decoded. */
  cursor?: string;
}

/**
 * Read the sanitized one-row-per-order drilldown (ADR-038, contract §3)
 * under the shared filters. The cursor is treated as opaque: callers pass
 * back the returned `nextCursor` verbatim and never derive positions from
 * row values.
 */
export async function fetchOrders(
  sessionId: string,
  query: OrdersQuery = {},
): Promise<OrdersData> {
  const params = new URLSearchParams(serializeFilters(query));
  if (query.limit !== undefined) {
    params.set("limit", String(query.limit));
  }
  if (query.cursor !== undefined && query.cursor !== "") {
    params.set("cursor", query.cursor);
  }
  const suffix = params.toString() === "" ? "" : `?${params.toString()}`;
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/v1/sessions/${encodeURIComponent(sessionId)}/orders${suffix}`,
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
    return (payload as { data: OrdersData }).data;
  }
  const { message, code, details } = envelopeError(
    payload,
    "Could not read the order records.",
  );
  throw new ApiRequestError(response.status, message, code, details);
}
