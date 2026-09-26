import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  createExport,
  downloadExportMetadata,
  downloadExportPrimary,
} from "@/lib/api";
import type { ExportIdentity, ExportKind } from "@/lib/api";
import { useAnalyticsFilters } from "@/lib/analytics-filters";
import { useSession } from "@/lib/session";
import { triggerBlobDownload } from "@/lib/export-download";

type KindPhase = "idle" | "creating" | "ready" | "error";

interface KindState {
  phase: KindPhase;
  identity: ExportIdentity | null;
  code: string | null;
  message: string | null;
  downloadBusy: "primary" | "metadata" | null;
  downloadError: string | null;
  downloadErrorCode: string | null;
  downloadFailedTarget: "primary" | "metadata" | null;
}

const KIND_ORDER: ExportKind[] = [
  "cleaned_items",
  "orders",
  "quality_report",
  "cleaning_report",
];

const KIND_META: Record<
  ExportKind,
  { title: string; body: string; exportLabel: string; filtered: boolean }
> = {
  cleaned_items: {
    title: "Sanitized cleaned items",
    body: "One row per sanitized order-item line. Respects the active dashboard filters.",
    exportLabel: "Export sanitized cleaned items",
    filtered: true,
  },
  orders: {
    title: "Canonical orders",
    body: "One row per order with aggregated totals. Respects the active dashboard filters.",
    exportLabel: "Export canonical orders",
    filtered: true,
  },
  quality_report: {
    title: "Data-quality report",
    body: "Whole-session profiling and issue evidence. Not filtered by dashboard selections.",
    exportLabel: "Export data-quality report",
    filtered: false,
  },
  cleaning_report: {
    title: "Cleaning report",
    body: "Whole-session cleaning audit log. Not filtered by dashboard selections.",
    exportLabel: "Export cleaning report",
    filtered: false,
  },
};

const CSV_KINDS: ReadonlySet<ExportKind> = new Set(["cleaned_items", "orders"]);

function initialStates(): Record<ExportKind, KindState> {
  const idle = (): KindState => ({
    phase: "idle",
    identity: null,
    code: null,
    message: null,
    downloadBusy: null,
    downloadError: null,
    downloadErrorCode: null,
    downloadFailedTarget: null,
  });
  return {
    cleaned_items: idle(),
    orders: idle(),
    quality_report: idle(),
    cleaning_report: idle(),
  };
}

/** Governed user-facing export errors: clear, no stack traces or paths. */
function exportErrorText(error: unknown): {
  message: string;
  code: string | null;
} {
  if (error instanceof ApiRequestError) {
    switch (error.code) {
      case "EXPORT_BLOCKED":
        return {
          message:
            "The export was prevented by the privacy gate. No file was downloaded.",
          code: error.code,
        };
      case "INVALID_FILTER_VALUE":
        return {
          message:
            "The export rejected the supplied filters. Audit reports accept no filters; data exports accept only the governed filter values. No file was downloaded.",
          code: error.code,
        };
      case "NOT_READY":
        return {
          message:
            "This session is not ready for exports yet. Wait for processing to finish and try again.",
          code: error.code,
        };
      case "INVALID_EXPORT_KIND":
        return {
          message: "Unknown export kind. No file was downloaded.",
          code: error.code,
        };
      case "EXPORT_NOT_FOUND":
        return {
          message:
            "This export is no longer available. Build the export again.",
          code: error.code,
        };
      case "SESSION_NOT_FOUND":
      case "SESSION_EXPIRED":
        return {
          message:
            "This session is gone from the server. Upload the file again to start a new session.",
          code: error.code,
        };
      default:
        return { message: error.message, code: error.code };
    }
  }
  return {
    message: "Something went wrong. Please try again.",
    code: null,
  };
}

/**
 * Phase-16 governed export experience (ADR-033/040). Lives on the Data
 * Quality page: exactly four kinds, data exports under the shared
 * analytics filters, reports whole-session, backend-owned bytes only.
 * Data Quality fetch/render never depends on analytics filters; only the
 * export POST payloads read the shared filter state.
 */
export default function ExportSection() {
  const { session } = useSession();
  const { query } = useAnalyticsFilters();
  const sessionId = session?.sessionId ?? null;
  const [states, setStates] =
    useState<Record<ExportKind, KindState>>(initialStates);
  // The parent keys this section by session id, so one mounted instance
  // always belongs to one session: no reset effect is needed and a
  // replacement or reset session never inherits old export identities.
  const sessionRef = useRef<string | null>(sessionId);
  useEffect(() => {
    sessionRef.current = sessionId;
  }, [sessionId]);
  // A replaced session unmounts this section while DQ reloads; a reset
  // unmounts it too. Late resolutions must never act on an unmounted
  // instance (no success UI, no download) even though the captured
  // session ref can no longer observe the change.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  if (sessionId === null) {
    return null;
  }

  const patch = (kind: ExportKind, next: Partial<KindState>) => {
    setStates((prev) => ({ ...prev, [kind]: { ...prev[kind], ...next } }));
  };

  async function handleCreate(kind: ExportKind): Promise<void> {
    const requestSession = sessionRef.current;
    if (requestSession === null) {
      return;
    }
    patch(kind, {
      phase: "creating",
      code: null,
      message: null,
      downloadError: null,
      downloadErrorCode: null,
      downloadFailedTarget: null,
    });
    try {
      // Data exports carry the active shared filters (inactive omitted by
      // the shared query); reports deliberately send no filters field.
      const identity =
        KIND_META[kind].filtered && Object.keys(query).length > 0
          ? await createExport(requestSession, { kind, filters: { ...query } })
          : await createExport(requestSession, { kind });
      if (!mountedRef.current || sessionRef.current !== requestSession) {
        return;
      }
      patch(kind, { phase: "ready", identity });
    } catch (error) {
      if (!mountedRef.current || sessionRef.current !== requestSession) {
        return;
      }
      const { message, code } = exportErrorText(error);
      patch(kind, { phase: "error", code, message, identity: null });
    }
  }

  async function handleDownload(
    kind: ExportKind,
    target: "primary" | "metadata",
  ): Promise<void> {
    const requestSession = sessionRef.current;
    const identity = states[kind].identity;
    if (requestSession === null || identity === null) {
      return;
    }
    patch(kind, {
      downloadBusy: target,
      downloadError: null,
      downloadErrorCode: null,
      downloadFailedTarget: null,
    });
    try {
      const result =
        target === "primary"
          ? await downloadExportPrimary(requestSession, identity.exportId)
          : await downloadExportMetadata(requestSession, identity.exportId);
      if (!mountedRef.current || sessionRef.current !== requestSession) {
        return;
      }
      // Prefer the POST-identity filename as the UI-known name; the GET
      // Content-Disposition filename is authoritative transport metadata
      // when present. Never derived from the original upload.
      const fallbackName =
        target === "primary"
          ? identity.filename
          : (identity.metadata?.filename ?? identity.filename);
      triggerBlobDownload(result.blob, result.filename ?? fallbackName);
      patch(kind, { downloadBusy: null });
    } catch (error) {
      if (!mountedRef.current || sessionRef.current !== requestSession) {
        return;
      }
      const { message, code } = exportErrorText(error);
      patch(kind, {
        downloadBusy: null,
        downloadError: message,
        downloadErrorCode: code,
        downloadFailedTarget: target,
      });
    }
  }

  return (
    <section aria-labelledby="dq-export-heading">
      <h3 id="dq-export-heading" className="text-base font-semibold">
        Exports
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Data exports respect the active dashboard filters. Audit reports cover
        the whole session and are not filtered by dashboard selections. All
        processing stays local; exports are sanitized and carry provenance
        metadata.
      </p>
      <details className="mt-2 rounded-lg border px-3 py-2 text-sm">
        <summary className="cursor-pointer font-medium">
          About filtered populations
        </summary>
        <p className="mt-1 text-muted-foreground">
          Cleaned items are an item-grain filtered population; orders are an
          order-grain filtered population. Under category/merchandise filters,
          totals can differ because multi-merchandise orders use the governed
          order-level category semantics.
        </p>
      </details>
      <div className="mt-3 flex flex-col gap-3">
        {KIND_ORDER.map((kind) => {
          const meta = KIND_META[kind];
          const state = states[kind];
          const isCsv = CSV_KINDS.has(kind);
          return (
            <div
              key={kind}
              className="flex flex-col gap-2 rounded-lg border p-4"
            >
              <div>
                <p className="text-sm font-medium">{meta.title}</p>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  {meta.body}
                </p>
              </div>
              {state.phase === "creating" ? (
                <p role="status" className="text-sm text-muted-foreground">
                  Building the {meta.title.toLowerCase()} export…
                </p>
              ) : null}
              {state.phase === "ready" && state.identity !== null ? (
                <p role="status" className="text-sm text-muted-foreground">
                  The {meta.title.toLowerCase()} export is ready to download.
                </p>
              ) : null}
              {state.phase === "error" && state.message !== null ? (
                <div role="alert" className="rounded-lg border p-3 text-sm">
                  <p className="font-medium">
                    The {meta.title.toLowerCase()} export could not be created.
                  </p>
                  <p className="mt-0.5 text-muted-foreground">
                    {state.message}
                  </p>
                  {state.code !== null ? (
                    <p className="mt-0.5 text-muted-foreground">
                      Code: {state.code}.
                    </p>
                  ) : null}
                </div>
              ) : null}
              <div className="flex flex-wrap gap-2">
                {state.phase === "ready" && state.identity !== null ? (
                  <>
                    <button
                      type="button"
                      onClick={() => void handleCreate(kind)}
                      className="rounded-md border px-3 py-1.5 text-sm font-medium"
                    >
                      {`Rebuild ${meta.title.toLowerCase()} export`}
                    </button>
                    <button
                      type="button"
                      disabled={state.downloadBusy !== null}
                      onClick={() => void handleDownload(kind, "primary")}
                      className="rounded-md bg-secondary px-3 py-1.5 text-sm font-medium disabled:opacity-60"
                    >
                      {isCsv
                        ? `Download ${meta.title.toLowerCase()} CSV`
                        : `Download ${meta.title.toLowerCase()}`}
                    </button>
                    {isCsv ? (
                      <button
                        type="button"
                        disabled={state.downloadBusy !== null}
                        onClick={() => void handleDownload(kind, "metadata")}
                        className="rounded-md border px-3 py-1.5 text-sm font-medium disabled:opacity-60"
                      >
                        {`Download ${meta.title.toLowerCase()} metadata`}
                      </button>
                    ) : null}
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      disabled={state.phase === "creating"}
                      onClick={() => void handleCreate(kind)}
                      className="rounded-md bg-secondary px-3 py-1.5 text-sm font-medium disabled:opacity-60"
                    >
                      {meta.exportLabel}
                    </button>
                    {state.phase === "error" ? (
                      <button
                        type="button"
                        onClick={() => void handleCreate(kind)}
                        className="rounded-md border px-3 py-1.5 text-sm font-medium"
                      >
                        {`Retry ${meta.title.toLowerCase()} export`}
                      </button>
                    ) : null}
                  </>
                )}
              </div>
              {state.downloadBusy !== null ? (
                <p role="status" className="text-sm text-muted-foreground">
                  Downloading…
                </p>
              ) : null}
              {state.downloadError !== null ? (
                <div role="alert" className="rounded-lg border p-3 text-sm">
                  <p className="font-medium">The download failed.</p>
                  <p className="mt-0.5 text-muted-foreground">
                    {state.downloadError}
                  </p>
                  {state.downloadErrorCode !== null ? (
                    <p className="mt-0.5 text-muted-foreground">
                      Code: {state.downloadErrorCode}.
                    </p>
                  ) : null}
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        void handleDownload(
                          kind,
                          state.downloadFailedTarget ?? "primary",
                        )
                      }
                      className="rounded-md border px-3 py-1.5 text-sm font-medium"
                    >
                      {`Retry ${meta.title.toLowerCase()} download`}
                    </button>
                  </div>
                </div>
              ) : null}
              {state.phase === "ready" && state.identity !== null ? (
                <details className="rounded-lg border px-3 py-2 text-sm">
                  <summary className="cursor-pointer font-medium">
                    Provenance and integrity
                  </summary>
                  <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                    <li>Primary file: {state.identity.filename}</li>
                    <li>Primary size: {state.identity.bytes} bytes</li>
                    <li>Primary SHA-256: {state.identity.sha256}</li>
                    {state.identity.metadata !== null ? (
                      <>
                        <li>
                          Metadata sidecar file:{" "}
                          {state.identity.metadata.filename}
                        </li>
                        <li>
                          Metadata sidecar size: {state.identity.metadata.bytes}{" "}
                          bytes
                        </li>
                        <li>
                          Metadata sidecar SHA-256:{" "}
                          {state.identity.metadata.sha256}
                        </li>
                      </>
                    ) : (
                      <li>
                        No metadata sidecar: provenance is embedded in the
                        report.
                      </li>
                    )}
                  </ul>
                </details>
              ) : null}
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Exports are sanitized: direct personal fields never appear. Currency is
        unspecified (numeric units only); findings describe the demo file, not a
        real company.
      </p>
    </section>
  );
}
