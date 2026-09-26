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

function goToDataQuality(): void {
  fireEvent.click(screen.getByRole("button", { name: "Data Quality" }));
  expect(
    screen.getByRole("heading", { name: "Data Quality" }),
  ).toBeInTheDocument();
}

function schemaBody() {
  return {
    data: {
      sourceColumns: [
        "Order Id",
        "Sales",
        "Customer Segment",
        "Order Customer Id",
        "Customer First Name",
        "Extra Col",
      ],
      mapping: [
        { source: "Order Id", canonical: "order_id", class: "required" },
        { source: "Sales", canonical: "gross_sales", class: "required" },
        {
          source: "Customer Segment",
          canonical: "customer_segment",
          class: "optional",
        },
        { source: "Order Customer Id", canonical: null, class: "redundant" },
        {
          source: "Customer First Name",
          canonical: null,
          class: "excluded",
        },
        { source: "Extra Col", canonical: null, class: "unknown" },
      ],
      missingCritical: [],
    },
    meta: {},
    error: null,
  };
}

function profileBody(rows: number) {
  return {
    data: {
      rows,
      columns: 4,
      grain: "order_item",
      missingness: [
        {
          field: "customer_segment",
          source: "Customer Segment",
          missing: 2,
          total: rows,
          rate: 0.2857,
          parseFailures: 0,
        },
      ],
      cardinality: [
        { field: "shipping_mode", source: "Shipping Mode", distinct: 3 },
      ],
      duplicates: { exact: 1, keyDupes: 0 },
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
        rulesEvaluated: 20,
        rulesTriggered: 3,
        errors: 1,
        warnings: 1,
        infos: 1,
        blockingIssues: 1,
      },
      issues: [
        {
          ruleId: "DQ-KEY-001",
          severity: "ERROR",
          count: 2,
          treatment: "flagged",
          blockedStage: "CANONICALIZATION",
        },
        {
          ruleId: "DQ-NUM-002",
          severity: "WARNING",
          count: 1,
          treatment: "flagged",
          blockedStage: null,
        },
        {
          ruleId: "DQ-PRIVACY-001",
          severity: "INFO",
          count: 2,
          treatment: "excluded",
          blockedStage: null,
        },
      ],
    },
    meta: {},
    error: null,
  };
}

function cleaningBody() {
  return {
    data: {
      steps: [
        {
          ruleId: "DQ-CAT-005",
          field: "destination_country",
          detected: 3,
          fixed: 3,
          flagged: 0,
          excluded: 0,
          unchanged: 0,
          reason: "Trimmed leading/trailing whitespace; 3 cell(s) changed.",
        },
        {
          ruleId: "DQ-NUM-002",
          field: "gross_sales,discount_amount,net_sales",
          detected: 1,
          fixed: 0,
          flagged: 1,
          excluded: 0,
          unchanged: 0,
          reason: "1 observation(s) retained without change for investigation.",
        },
      ],
    },
    meta: {},
    error: null,
  };
}

type RouteOutcome = { status: number; body: unknown };

function ok(body: unknown): RouteOutcome {
  return { status: 200, body };
}

function notReady(): RouteOutcome {
  return {
    status: 409,
    body: {
      data: null,
      meta: {},
      error: {
        code: "NOT_READY",
        stage: "PROFILING",
        message: "Value-level profiling has not completed yet.",
        details: { state: "PROFILING" },
      },
    },
  };
}

let route: (url: string) => RouteOutcome | Promise<RouteOutcome>;

function defaultRoute(url: string): RouteOutcome {
  const rows = url.includes(SESSION_B) ? 9 : 7;
  if (url.endsWith("/schema")) {
    return ok(schemaBody());
  }
  if (url.endsWith("/profile")) {
    return ok(profileBody(rows));
  }
  if (url.endsWith("/data-quality")) {
    return ok(qualityBody());
  }
  if (url.endsWith("/cleaning-report")) {
    return ok(cleaningBody());
  }
  return notReady();
}

beforeEach(() => {
  route = defaultRoute;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: unknown) => {
      const { status, body } = await route(String(input));
      return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function fetchCalls(): string[] {
  const mock = vi.mocked(fetch);
  return mock.mock.calls.map((args) => String(args[0]));
}

describe("Phase-11 Data Quality view", () => {
  it("renders the governed empty state without requesting reports", () => {
    renderSeeded(snapshotFor(null, null));
    goToDataQuality();
    expect(screen.getByText("No dataset loaded")).toBeInTheDocument();
    expect(fetchCalls()).toHaveLength(0);
  });

  it("renders loading progress while reports are not ready", async () => {
    route = () => notReady();
    renderSeeded(snapshotFor(SESSION_A, "PROFILING"));
    goToDataQuality();
    expect(
      await screen.findByText(/loading the data-quality report/i),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/PROFILING/).length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchCalls().length).toBeGreaterThan(0);
  });

  it("renders profile, coverage, issues, and cleaning for the session", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDataQuality();
    expect(await screen.findByText(/7 order-item lines/)).toBeInTheDocument();
    expect(
      screen.getByText(/2 of 2 required fields mapped/),
    ).toBeInTheDocument();
    expect(screen.getByText("DQ-KEY-001")).toBeInTheDocument();
    expect(screen.getAllByText("DQ-NUM-002")).toHaveLength(2);
    expect(screen.getByText("DQ-PRIVACY-001")).toBeInTheDocument();
    expect(screen.getByText(/CANONICALIZATION/)).toBeInTheDocument();
    expect(
      screen.getByText(/detected is not the same as fixed/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/exports arrive in phase 16/i)).toBeInTheDocument();
    expect(screen.queryByText("No dataset loaded")).not.toBeInTheDocument();
  });

  it("uses the governed detected/fixed/flagged/excluded/unchanged vocabulary", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDataQuality();
    await screen.findByText(/7 order-item lines/);
    for (const header of [
      "Detected (count)",
      "Fixed (count)",
      "Flagged (count)",
      "Excluded (count)",
      "Unchanged (count)",
    ]) {
      expect(screen.getByText(header)).toBeInTheDocument();
    }
    expect(screen.getAllByText("flagged")).toHaveLength(2);
    expect(screen.getByText("excluded")).toBeInTheDocument();
    expect(screen.queryByText(/failed/i)).not.toBeInTheDocument();
  });

  it("explains blocked stages as recoverable gates, not terminal failure", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDataQuality();
    await screen.findByText("DQ-KEY-001");
    expect(
      screen.getByText(/gates work; recoverable, not terminal/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/no override/i)).toBeInTheDocument();
    expect(screen.queryByText(/pipeline failed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/ended in failed/i)).not.toBeInTheDocument();
  });

  it("shows a terminal FAILED state without requesting reports", async () => {
    renderSeeded(snapshotFor(SESSION_A, "FAILED"));
    goToDataQuality();
    expect(await screen.findByText(/ended in failed/i)).toBeInTheDocument();
    expect(fetchCalls()).toHaveLength(0);
    expect(screen.queryByText(/order-item lines/)).not.toBeInTheDocument();
  });

  it("surfaces a missing-critical schema error actionably", async () => {
    route = (url: string) => {
      if (url.endsWith("/schema")) {
        return {
          status: 422,
          body: {
            data: null,
            meta: {},
            error: {
              code: "SCHEMA_MISSING_COLUMN",
              stage: "VALIDATING",
              message: "The file is missing 1 required column: Sales.",
              details: { missing: ["Sales"] },
            },
          },
        };
      }
      return defaultRoute(url);
    };
    renderSeeded(snapshotFor(SESSION_A, "VALIDATING"));
    goToDataQuality();
    expect(
      await screen.findByText(/missing 1 required column/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/SCHEMA_MISSING_COLUMN/)).toBeInTheDocument();
    expect(screen.queryByText(/order-item lines/)).not.toBeInTheDocument();
  });

  it("shows an error state instead of stale content on API failure", async () => {
    route = (url: string) => {
      if (url.endsWith("/profile")) {
        return {
          status: 500,
          body: {
            data: null,
            meta: {},
            error: {
              code: "INTERNAL_STAGE_ERROR",
              stage: "PROFILING",
              message: "Profiling could not be completed.",
              details: {},
            },
          },
        };
      }
      return defaultRoute(url);
    };
    renderSeeded(snapshotFor(SESSION_A, "PROFILING"));
    goToDataQuality();
    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(/order-item lines/)).not.toBeInTheDocument();
  });

  it("clears the report when the session is reset", async () => {
    const { rerender } = renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDataQuality();
    await screen.findByText(/7 order-item lines/);
    rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(null, null)} />
      </SessionProvider>,
    );
    expect(screen.getByText("No dataset loaded")).toBeInTheDocument();
    expect(screen.queryByText(/7 order-item lines/)).not.toBeInTheDocument();
    expect(screen.queryByText("DQ-KEY-001")).not.toBeInTheDocument();
  });

  it("never lets a slow old session overwrite a new session", async () => {
    let resolveProfileA!: (outcome: RouteOutcome) => void;
    const profileAGate = new Promise<RouteOutcome>((resolve) => {
      resolveProfileA = resolve;
    });
    route = (url: string) => {
      if (url.includes(SESSION_A) && url.endsWith("/profile")) {
        return profileAGate;
      }
      return defaultRoute(url);
    };
    const { rerender } = renderSeeded(snapshotFor(SESSION_A, "CLEANING"));
    goToDataQuality();
    await waitFor(() => {
      expect(fetchCalls().some((url) => url.includes(SESSION_A))).toBe(true);
    });
    // Session B arrives while A's profile is still in flight; B resolves
    // immediately and renders.
    rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(SESSION_B, "READY")} />
      </SessionProvider>,
    );
    await screen.findByText(/9 order-item lines/);
    // A's late response must be ignored, never overwriting B.
    resolveProfileA(ok(profileBody(7)));
    await waitFor(() => {
      expect(fetchCalls().length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/9 order-item lines/)).toBeInTheDocument();
    expect(screen.queryByText(/7 order-item lines/)).not.toBeInTheDocument();
  });

  it("reloads safely across away/back navigation", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDataQuality();
    await screen.findByText(/7 order-item lines/);
    const callsAfterLoad = fetchCalls().length;
    fireEvent.click(screen.getByRole("button", { name: "Delivery" }));
    expect(
      screen.getByRole("heading", { name: "Delivery" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Data Quality" }));
    await screen.findByText(/7 order-item lines/);
    expect(fetchCalls().length).toBeGreaterThan(callsAfterLoad);
    expect(screen.getByText("DQ-KEY-001")).toBeInTheDocument();
  });

  it("shows counts and header names but no raw personal values", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDataQuality();
    await screen.findByText(/7 order-item lines/);
    // Governed header names are allowed; values never appear.
    expect(screen.getByText("Customer First Name")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/@|\.com|John|Smith/);
  });

  it("reports no axe violations on the loaded report", async () => {
    const { container } = renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDataQuality();
    await screen.findByText(/7 order-item lines/);
    expect(await axe(container)).toHaveNoViolations();
  });
});
