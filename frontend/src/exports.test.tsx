import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import * as matchers from "vitest-axe/matchers";
import AppShell from "./components/AppShell";
import { SessionProvider } from "./lib/session-context";
import { useSession } from "./lib/session";
import type { SessionSnapshot } from "./lib/session";

expect.extend(matchers);

const SESSION_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa";
const SESSION_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb";

function snapshotFor(
  sessionId: string | null,
  sessionState: string | null,
): SessionSnapshot {
  return {
    session:
      sessionId === null
        ? null
        : {
            sessionId,
            statusUrl: `/api/v1/sessions/${sessionId}/status`,
            filenameSafe: "orders.csv",
            bytes: 41,
            sha256: "ab".repeat(32),
            encoding: "utf-8",
          },
    sessionState,
  };
}

function SeedHost({ snapshot }: { snapshot: SessionSnapshot }) {
  const { updateSnapshot } = useSession();
  useEffect(() => {
    updateSnapshot(snapshot);
  }, [updateSnapshot, snapshot]);
  return <AppShell onSessionChange={updateSnapshot} />;
}

function renderSeeded(snapshot: SessionSnapshot) {
  return render(
    <SessionProvider>
      <SeedHost snapshot={snapshot} />
    </SessionProvider>,
  );
}

function goTo(label: string): void {
  fireEvent.click(screen.getByRole("button", { name: label }));
}

async function goToDataQualityReady(): Promise<void> {
  goTo("Data Quality");
  await screen.findByRole("button", {
    name: "Export sanitized cleaned items",
  });
}

function schemaBody() {
  return {
    data: { sourceColumns: [], mapping: [], missingCritical: [] },
    meta: {},
    error: null,
  };
}

function profileBody() {
  return {
    data: {
      rows: 7,
      columns: 4,
      grain: "order item",
      missingness: [],
      cardinality: [],
      duplicates: { exact: 0, keyDupes: 0 },
      invarianceConflicts: {
        ordersChecked: 5,
        conflictingOrders: 0,
        byField: [],
      },
      productInvarianceConflicts: {
        keysChecked: 3,
        conflictingKeys: 0,
        byField: [],
      },
      customerInvarianceConflicts: {
        keysChecked: 4,
        conflictingKeys: 0,
        byField: [],
      },
    },
    meta: {},
    error: null,
  };
}

function qualityBody() {
  return {
    data: {
      summary: {
        rulesEvaluated: 3,
        rulesTriggered: 0,
        errors: 0,
        warnings: 0,
        infos: 0,
        blockingIssues: 0,
      },
      issues: [],
    },
    meta: {},
    error: null,
  };
}

function cleaningBody() {
  return {
    data: { steps: [] },
    meta: {},
    error: null,
  };
}

function filterOptionsBody() {
  return {
    data: {
      dateRange: { minOrderDate: "2021-03-10", maxOrderDate: "2021-03-20" },
      markets: ["M1"],
      regions: ["R1"],
      categories: ["Alpha"],
    },
    meta: {},
    error: null,
  };
}

function kpiMinimalBody() {
  return {
    data: {
      kpis: [],
      totals: {
        items: 0,
        orders: 0,
        eligibleOrders: 0,
        grossValue: "0.00",
        discountTotal: "0.00",
        netValue: "0.00",
        profitTotal: "0.00",
        units: 0,
      },
    },
    meta: {},
    error: null,
  };
}

interface RecordedCall {
  url: string;
  method: string;
  body: unknown;
}

let calls: RecordedCall[];
let postHandler:
  ((url: string, body: unknown) => Response | Promise<Response>) | null;
let getExportHandler: ((url: string) => Response | Promise<Response>) | null;

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function exportIdentityBody(opts: {
  exportId: string;
  filename: string;
  sidecar: boolean;
}) {
  return {
    data: {
      exportId: opts.exportId,
      filename: opts.filename,
      bytes: 18,
      sha256: "cc".repeat(32),
      metadata: opts.sidecar
        ? {
            filename: opts.filename.replace(/\.csv$/, "") + ".meta.json",
            bytes: 9,
            sha256: "dd".repeat(32),
          }
        : null,
    },
    meta: {},
    error: null,
  };
}

function errorBody(code: string, message: string) {
  return {
    data: null,
    meta: {},
    error: { code, stage: "ANALYZING", message, details: {} },
  };
}

/** Deterministic deferred promise: no sleeps, explicit resolution. */
function deferredResponse(): {
  promise: Promise<Response>;
  resolve: (value: Response) => void;
} {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

beforeEach(() => {
  calls = [];
  postHandler = null;
  getExportHandler = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: unknown, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      let body: unknown = null;
      if (typeof init?.body === "string" && init.body !== "") {
        try {
          body = JSON.parse(init.body);
        } catch {
          body = init.body;
        }
      }
      calls.push({ url, method, body });
      if (method === "POST" && url.endsWith("/exports")) {
        if (postHandler !== null) {
          return postHandler(url, body);
        }
        const kind = (body as { kind?: string })?.kind ?? "cleaned_items";
        const isCsv = kind === "cleaned_items" || kind === "orders";
        const filename =
          kind === "cleaned_items"
            ? "orders_cleaned_items_app0.1.0_schema1_20260310T000000.csv"
            : kind === "orders"
              ? "orders_orders_app0.1.0_schema1_20260310T000000.csv"
              : `orders_${kind}_app0.1.0_schema1_20260310T000000.json`;
        return jsonResponse(
          exportIdentityBody({
            exportId: "a1b2c3d4e5f60718293a4b5c6d7e8f90",
            filename,
            sidecar: isCsv,
          }),
          201,
        );
      }
      if (url.includes("/exports/")) {
        if (getExportHandler !== null) {
          return getExportHandler(url);
        }
        if (url.endsWith("/metadata")) {
          return new Response('{"provenance":"sidecar"}', {
            status: 200,
            headers: {
              "Content-Type": "application/json",
              "Content-Disposition":
                'attachment; filename="orders_cleaned_items_app0.1.0_schema1_20260310T000000.meta.json"',
            },
          });
        }
        const isJson =
          url.includes("quality_report") || url.includes("cleaning_report");
        void isJson;
        return new Response("a,b\n1,2\n", {
          status: 200,
          headers: {
            "Content-Type": "text/csv",
            "Content-Disposition":
              'attachment; filename="orders_cleaned_items_app0.1.0_schema1_20260310T000000.csv"',
          },
        });
      }
      if (url.endsWith("/schema")) return jsonResponse(schemaBody(), 200);
      if (url.endsWith("/profile")) return jsonResponse(profileBody(), 200);
      if (url.endsWith("/data-quality"))
        return jsonResponse(qualityBody(), 200);
      if (url.endsWith("/cleaning-report"))
        return jsonResponse(cleaningBody(), 200);
      if (url.includes("/filter-options"))
        return jsonResponse(filterOptionsBody(), 200);
      if (url.includes("/kpis/")) return jsonResponse(kpiMinimalBody(), 200);
      if (url.includes("/orders")) {
        return jsonResponse(
          {
            data: { rows: [], page: { nextCursor: null, total: 0 } },
            meta: {},
            error: null,
          },
          200,
        );
      }
      return jsonResponse({ data: null, meta: {}, error: null }, 200);
    }),
  );
  const created: string[] = [];
  void created;
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function postCalls(): RecordedCall[] {
  return calls.filter(
    (entry) => entry.method === "POST" && entry.url.endsWith("/exports"),
  );
}

function stubObjectUrls(captured: { blob: Blob | null }) {
  const create = vi.fn((blob: Blob) => {
    captured.blob = blob;
    return "blob:mock-url";
  });
  const revoke = vi.fn(() => {});
  Object.defineProperty(URL, "createObjectURL", {
    value: create,
    writable: true,
    configurable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    value: revoke,
    writable: true,
    configurable: true,
  });
  return { create, revoke };
}

function setAllEightFilters(): void {
  goTo("Overview");
  fireEvent.change(screen.getByLabelText("From (order date)"), {
    target: { value: "2021-03-11" },
  });
  fireEvent.change(screen.getByLabelText("To (order date)"), {
    target: { value: "2021-03-19" },
  });
  fireEvent.change(screen.getByLabelText("Market"), {
    target: { value: "M1" },
  });
  fireEvent.change(screen.getByLabelText("Region"), {
    target: { value: "R1" },
  });
  fireEvent.change(screen.getByLabelText("Category"), {
    target: { value: "Alpha" },
  });
  fireEvent.change(screen.getByLabelText("Shipping mode"), {
    target: { value: "STANDARD_CLASS" },
  });
  fireEvent.change(screen.getByLabelText("Order status"), {
    target: { value: "COMPLETE" },
  });
  fireEvent.change(screen.getByLabelText("Shipment outcome"), {
    target: { value: "LATE" },
  });
}

describe("Phase-16B export experience", () => {
  it("exposes exactly the four governed export kinds and no other artifact", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await goToDataQualityReady();
    expect(
      screen.getByRole("button", { name: "Export sanitized cleaned items" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Export canonical orders" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Export data-quality report" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Export cleaning report" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /raw/i }),
    ).not.toBeInTheDocument();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/cleaned\.csv/);
    expect(text).not.toMatch(/KPI CSV/);
    expect(text).not.toMatch(/screenshot/i);
    expect(text).not.toMatch(/Power BI/);
    expect(text).not.toMatch(/\bZIP\b/);
  });

  it("explains the filtered versus whole-session scope before export", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await goToDataQualityReady();
    expect(
      screen.getByText(/data exports respect the active dashboard filters/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /audit reports cover the whole session and are not filtered/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/item-grain filtered population/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/order-grain filtered population/i),
    ).toBeInTheDocument();
  });

  it("sends the full 8-filter set for data exports and nothing extra", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await screen.findByRole("button", { name: "Overview" });
    setAllEightFilters();
    goTo("Data Quality");
    await screen.findByRole("button", {
      name: "Export sanitized cleaned items",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Export sanitized cleaned items" }),
    );
    await waitFor(() => expect(postCalls()).toHaveLength(1));
    const payload = postCalls()[0].body as Record<string, unknown>;
    expect(payload.kind).toBe("cleaned_items");
    expect(payload.filters).toEqual({
      from: "2021-03-11",
      to: "2021-03-19",
      market: "M1",
      region: "R1",
      category: "Alpha",
      shipping_mode: "STANDARD_CLASS",
      order_status: "COMPLETE",
      shipment_outcome: "LATE",
    });
    expect(payload.filters as Record<string, unknown>).not.toHaveProperty(
      "department",
    );
    expect(payload.filters as Record<string, unknown>).not.toHaveProperty(
      "customer_segment",
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Export canonical orders" }),
    );
    await waitFor(() => expect(postCalls()).toHaveLength(2));
    const ordersPayload = postCalls()[1].body as Record<string, unknown>;
    expect(ordersPayload.kind).toBe("orders");
    expect(ordersPayload.filters).toEqual({
      from: "2021-03-11",
      to: "2021-03-19",
      market: "M1",
      region: "R1",
      category: "Alpha",
      shipping_mode: "STANDARD_CLASS",
      order_status: "COMPLETE",
      shipment_outcome: "LATE",
    });
  });

  it("sends no filters for either audit report even with filters active", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await screen.findByRole("button", { name: "Overview" });
    setAllEightFilters();
    goTo("Data Quality");
    await screen.findByRole("button", {
      name: "Export data-quality report",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Export data-quality report" }),
    );
    await waitFor(() => expect(postCalls()).toHaveLength(1));
    const qualityPayload = postCalls()[0].body as Record<string, unknown>;
    expect(qualityPayload.kind).toBe("quality_report");
    expect(qualityPayload).not.toHaveProperty("filters");

    fireEvent.click(
      screen.getByRole("button", { name: "Export cleaning report" }),
    );
    await waitFor(() => expect(postCalls()).toHaveLength(2));
    const cleaningPayload = postCalls()[1].body as Record<string, unknown>;
    expect(cleaningPayload.kind).toBe("cleaning_report");
    expect(cleaningPayload).not.toHaveProperty("filters");
  });

  it("downloads a CSV primary plus its metadata sidecar under server filenames", async () => {
    const captured: { blob: Blob | null } = { blob: null };
    const { create, revoke } = stubObjectUrls(captured);
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await goToDataQualityReady();
    fireEvent.click(
      screen.getByRole("button", { name: "Export sanitized cleaned items" }),
    );
    const csvButton = await screen.findByRole("button", {
      name: "Download sanitized cleaned items CSV",
    });
    expect(
      screen.getByRole("button", {
        name: "Download sanitized cleaned items metadata",
      }),
    ).toBeInTheDocument();
    fireEvent.click(csvButton);
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(captured.blob).toBeInstanceOf(Blob);
    expect(await captured.blob?.text()).toContain("a,b");
    expect(revoke).toHaveBeenCalledWith("blob:mock-url");

    create.mockClear();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Download sanitized cleaned items metadata",
      }),
    );
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(revoke).toHaveBeenCalledWith("blob:mock-url");
  });

  it("offers a single download for JSON reports with no metadata action", async () => {
    const captured: { blob: Blob | null } = { blob: null };
    const { create } = stubObjectUrls(captured);
    getExportHandler = (url: string) => {
      if (url.endsWith("/metadata")) {
        return jsonResponse(errorBody("EXPORT_NOT_FOUND", "gone"), 404);
      }
      return new Response('{"provenance":"report"}', {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await goToDataQualityReady();
    fireEvent.click(
      screen.getByRole("button", { name: "Export data-quality report" }),
    );
    const download = await screen.findByRole("button", {
      name: "Download data-quality report",
    });
    expect(
      screen.queryByRole("button", {
        name: "Download data-quality report metadata",
      }),
    ).not.toBeInTheDocument();
    fireEvent.click(download);
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(await captured.blob?.text()).toContain("provenance");
  });

  it("renders governed errors with retry and never a false success", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await goToDataQualityReady();
    postHandler = () =>
      jsonResponse(
        errorBody(
          "EXPORT_BLOCKED",
          "The export was blocked by the privacy gate.",
        ),
        422,
      );
    fireEvent.click(
      screen.getByRole("button", { name: "Export canonical orders" }),
    );
    const alert = await screen.findByRole("alert");
    expect(alert.textContent ?? "").toMatch(/privacy gate/i);
    expect(alert.textContent ?? "").toMatch(/no file was downloaded/i);
    expect(
      screen.queryByRole("button", { name: /download canonical orders/i }),
    ).not.toBeInTheDocument();
    const retry = screen.getByRole("button", {
      name: "Retry canonical orders export",
    });
    postHandler = null;
    fireEvent.click(retry);
    await screen.findByRole("button", {
      name: "Download canonical orders CSV",
    });
  });

  it("maps invalid-filter, not-ready, and server failures without leaking internals", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await goToDataQualityReady();

    postHandler = () =>
      jsonResponse(
        errorBody("INVALID_FILTER_VALUE", "Unknown export filter keys."),
        422,
      );
    fireEvent.click(
      screen.getByRole("button", { name: "Export sanitized cleaned items" }),
    );
    expect((await screen.findByRole("alert")).textContent ?? "").toMatch(
      /rejected the supplied filters/i,
    );

    postHandler = () =>
      jsonResponse(errorBody("NOT_READY", "Not processed yet."), 409);
    fireEvent.click(
      screen.getByRole("button", { name: "Export cleaning report" }),
    );
    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));
    expect(screen.getAllByRole("alert")[1]?.textContent ?? "").toMatch(
      /not ready for exports/i,
    );

    postHandler = () => jsonResponse(errorBody("OOPS", "boom"), 500);
    fireEvent.click(
      screen.getByRole("button", { name: "Export canonical orders" }),
    );
    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(3));
    // Alerts render in governed kind order (cleaned_items, orders,
    // cleaning_report), not chronological order: the orders card is index 1.
    const alerts = screen.getAllByRole("alert");
    expect(alerts[1]?.textContent ?? "").toMatch(/boom/);
    expect(document.body.textContent ?? "").not.toMatch(/Traceback/);
    expect(document.body.textContent ?? "").not.toMatch(/\/tmp\//);
  });

  it("makes primary and metadata download failures retryable without recreating", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await goToDataQualityReady();
    fireEvent.click(
      screen.getByRole("button", { name: "Export sanitized cleaned items" }),
    );
    await screen.findByRole("button", {
      name: "Download sanitized cleaned items CSV",
    });
    const postsBefore = postCalls().length;
    getExportHandler = () =>
      jsonResponse(errorBody("EXPORT_NOT_FOUND", "gone"), 404);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Download sanitized cleaned items CSV",
      }),
    );
    await screen.findByText(/the download failed/i);
    expect(postCalls()).toHaveLength(postsBefore);
    getExportHandler = null;
    fireEvent.click(
      screen.getByRole("button", {
        name: /retry sanitized cleaned items download/i,
      }),
    );
    await waitFor(() =>
      expect(
        screen.queryByText(/the download failed/i),
      ).not.toBeInTheDocument(),
    );
  });

  it("clears export identities when the session is replaced or reset", async () => {
    const view = renderSeeded(snapshotFor(SESSION_A, "READY"));
    await goToDataQualityReady();
    fireEvent.click(
      screen.getByRole("button", { name: "Export canonical orders" }),
    );
    await screen.findByRole("button", {
      name: "Download canonical orders CSV",
    });
    view.rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(SESSION_B, "READY")} />
      </SessionProvider>,
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: "Download canonical orders CSV",
        }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Export canonical orders" }),
    ).toBeInTheDocument();

    view.rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(null, null)} />
      </SessionProvider>,
    );
    expect(screen.getByText(/no dataset loaded/i)).toBeInTheDocument();
  });

  it("ignores a stale export POST that resolves after session replacement", async () => {
    const gate = deferredResponse();
    postHandler = () => gate.promise;
    const view = renderSeeded(snapshotFor(SESSION_A, "READY"));
    await goToDataQualityReady();
    fireEvent.click(
      screen.getByRole("button", { name: "Export data-quality report" }),
    );
    await screen.findByText(/building the data-quality report export/i);
    view.rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(SESSION_B, "READY")} />
      </SessionProvider>,
    );
    // Let the replacement session clear the pending state first, so the
    // late POST resolution is deterministically stale.
    await waitFor(() =>
      expect(
        screen.queryByText(/building the data-quality report export/i),
      ).not.toBeInTheDocument(),
    );
    gate.resolve(
      jsonResponse(
        exportIdentityBody({
          exportId: "ffffffffffffffffffffffffffffffff",
          filename:
            "orders_quality_report_app0.1.0_schema1_20260310T000000.json",
          sidecar: false,
        }),
        201,
      ),
    );
    await screen.findByRole("button", {
      name: "Export data-quality report",
    });
    expect(
      screen.queryByRole("button", {
        name: "Download data-quality report",
      }),
    ).not.toBeInTheDocument();
  });

  it("does not trigger an old download when a stale GET resolves late", async () => {
    const captured: { blob: Blob | null } = { blob: null };
    const { create } = stubObjectUrls(captured);
    const gate = deferredResponse();
    getExportHandler = () => gate.promise;
    const view = renderSeeded(snapshotFor(SESSION_A, "READY"));
    await goToDataQualityReady();
    fireEvent.click(
      screen.getByRole("button", { name: "Export sanitized cleaned items" }),
    );
    const csvButton = await screen.findByRole("button", {
      name: "Download sanitized cleaned items CSV",
    });
    fireEvent.click(csvButton);
    await screen.findByText(/downloading/i);
    view.rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(SESSION_B, "READY")} />
      </SessionProvider>,
    );
    // Let the replacement session clear the old export state first, so the
    // late GET resolution is deterministically stale.
    await waitFor(() =>
      expect(screen.queryByText(/downloading/i)).not.toBeInTheDocument(),
    );
    gate.resolve(
      new Response("a,b\n9,9\n", {
        status: 200,
        headers: { "Content-Type": "text/csv" },
      }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: "Download sanitized cleaned items CSV",
        }),
      ).not.toBeInTheDocument(),
    );
    expect(create).not.toHaveBeenCalled();
  });

  it("keeps dashboard filters and DQ evidence independent of exporting", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await screen.findByRole("button", { name: "Overview" });
    setAllEightFilters();
    goTo("Data Quality");
    await screen.findByRole("button", {
      name: "Export sanitized cleaned items",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Export sanitized cleaned items" }),
    );
    await screen.findByRole("button", {
      name: "Download sanitized cleaned items CSV",
    });
    const dqGets = calls.filter(
      (entry) =>
        entry.method === "GET" &&
        (entry.url.endsWith("/profile") ||
          entry.url.endsWith("/data-quality") ||
          entry.url.endsWith("/cleaning-report") ||
          entry.url.endsWith("/schema")),
    );
    expect(dqGets.length).toBeGreaterThan(0);
    for (const entry of dqGets) {
      expect(entry.url).not.toContain("market=");
      expect(entry.url).not.toContain("region=");
      expect(entry.url).not.toContain("category=");
    }
    goTo("Overview");
    expect(screen.getByLabelText("Market")).toHaveValue("M1");
    expect(screen.getByRole("button", { name: "Reset filters" })).toBeEnabled();
  });

  it("labels primary and sidecar integrity separately without frontend math", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await goToDataQualityReady();
    fireEvent.click(
      screen.getByRole("button", { name: "Export sanitized cleaned items" }),
    );
    await screen.findByRole("button", {
      name: "Download sanitized cleaned items CSV",
    });
    fireEvent.click(screen.getByText("Provenance and integrity"));
    expect(screen.getByText(/primary size:/i)).toBeInTheDocument();
    expect(screen.getByText(/primary sha-256:/i)).toBeInTheDocument();
    expect(screen.getByText(/metadata sidecar size:/i)).toBeInTheDocument();
    expect(screen.getByText(/metadata sidecar sha-256:/i)).toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toMatch(/combined.*hash/i);
  });

  it("remains axe-clean with the export controls loaded", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await goToDataQualityReady();
    const results = await axe(document.body);
    expect(results.violations).toEqual([]);
  });
});
