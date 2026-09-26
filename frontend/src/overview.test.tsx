import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import * as matchers from "vitest-axe/matchers";
import AppShell from "./components/AppShell";
import { formatKpiValue } from "./lib/kpi-format";
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

function goToOverview(): void {
  fireEvent.click(screen.getByRole("button", { name: "Overview" }));
  expect(screen.getByRole("heading", { name: "Overview" })).toBeInTheDocument();
}

interface KpiFixture {
  id: string;
  label: string;
  value: number | string | null;
  status?: string;
  reason?: string | null;
}

function kpi(fixture: KpiFixture) {
  return {
    id: fixture.id,
    label: fixture.label,
    value: fixture.value,
    status: fixture.status ?? "ok",
    numerator: fixture.value,
    denominator: null,
    population: `Population for ${fixture.id}.`,
    exclusions: `Exclusions for ${fixture.id}.`,
    reason: fixture.reason ?? null,
    missingDataCount: 0,
  };
}

/** Small arbitrary values — never DataCo reference controls. */
function overviewBody() {
  return {
    data: {
      kpis: [
        kpi({
          id: "kpi.value.net",
          label: "Recorded net order value",
          value: "1234.56",
        }),
        kpi({
          id: "kpi.profit.recorded",
          label: "Recorded profit",
          value: "-45.67",
        }),
        kpi({
          id: "kpi.margin.profit",
          label: "Profit margin",
          value: null,
          status: "unavailable",
          reason: "zero-denominator",
        }),
        kpi({
          id: "kpi.ship.late_rate",
          label: "Late-shipment rate",
          value: "0.5",
        }),
        kpi({
          id: "kpi.ship.on_schedule_rate",
          label: "On-schedule shipment rate",
          value: "0.5",
        }),
        kpi({ id: "kpi.orders.count", label: "Orders", value: 10 }),
        kpi({
          id: "kpi.orders.shipment_eligible_count",
          label: "Shipment-eligible orders",
          value: 8,
        }),
        kpi({ id: "kpi.units.total", label: "Units", value: 25 }),
        kpi({ id: "kpi.ship.late_count", label: "Late orders", value: 4 }),
        kpi({ id: "kpi.ship.early_count", label: "Early orders", value: 2 }),
        kpi({
          id: "kpi.ship.exact_count",
          label: "Exactly on-schedule orders",
          value: 2,
        }),
      ],
      totals: {
        items: 12,
        orders: 10,
        eligibleOrders: 8,
        grossValue: "1500.00",
        discountTotal: "265.44",
        netValue: "1234.56",
        profitTotal: "-45.67",
        units: 25,
      },
    },
    meta: {},
    error: null,
  };
}

function deliveryBody() {
  return {
    data: {
      groups: [],
      eligibleOrders: 8,
      exclusions: "1 shipping-cancelled order excluded",
    },
    meta: {},
    error: null,
  };
}

function monthGroup(
  key: string,
  net: string | null,
  profit: string | null,
): unknown {
  return {
    key,
    kpis: [
      kpi({
        id: "kpi.value.net",
        label: "Recorded net order value",
        value: net,
        status: net === null ? "unavailable" : "ok",
        reason: net === null ? "empty-eligible-population" : null,
      }),
      kpi({
        id: "kpi.profit.recorded",
        label: "Recorded profit",
        value: profit,
        status: profit === null ? "unavailable" : "ok",
        reason: profit === null ? "empty-eligible-population" : null,
      }),
    ],
  };
}

function trendBody() {
  return {
    data: {
      groups: [
        monthGroup("2024-01", "800.00", "100.00"),
        monthGroup("2024-02", "434.56", "-145.67"),
        monthGroup("2024-03", null, null),
      ],
      statusScope: "All order statuses included",
      weightedRates: { profitMargin: null, discountRate: null },
    },
    meta: {},
    error: null,
  };
}

function regionBody(netNorth: string) {
  return {
    data: {
      groups: [
        {
          key: "North",
          kpis: [
            kpi({
              id: "kpi.value.net",
              label: "Recorded net order value",
              value: netNorth,
            }),
          ],
        },
        {
          key: "South",
          kpis: [
            kpi({
              id: "kpi.value.net",
              label: "Recorded net order value",
              value: "334.56",
            }),
          ],
        },
      ],
      statusScope: "All order statuses included",
      weightedRates: { profitMargin: null, discountRate: null },
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
        stage: "ANALYZING",
        message: "KPI analysis has not completed yet.",
        details: { state: "ANALYZING" },
      },
    },
  };
}

let route: (url: string) => RouteOutcome | Promise<RouteOutcome>;

function defaultRoute(url: string): RouteOutcome {
  const north = url.includes(SESSION_B) ? "700.00" : "900.00";
  if (url.includes("/kpis/overview")) {
    return ok(overviewBody());
  }
  if (url.includes("/kpis/delivery")) {
    return ok(deliveryBody());
  }
  if (url.includes("/kpis/commercial")) {
    if (url.includes("by=order_month")) {
      return ok(trendBody());
    }
    return ok(regionBody(north));
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

describe("Phase-12 Executive Overview", () => {
  it("renders the governed empty state without requesting KPIs", () => {
    renderSeeded(snapshotFor(null, null));
    goToOverview();
    expect(screen.getByText("No dataset loaded")).toBeInTheDocument();
    expect(fetchCalls()).toHaveLength(0);
  });

  it("renders loading progress while KPI analysis is not ready", async () => {
    route = () => notReady();
    renderSeeded(snapshotFor(SESSION_A, "ANALYZING"));
    goToOverview();
    expect(
      await screen.findByText(/loading the headline results/i),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/ANALYZING/).length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchCalls().some((url) => url.includes("/kpis/overview"))).toBe(
      true,
    );
  });

  it("explains a governed gate as recoverable, not terminal", async () => {
    route = () => notReady();
    renderSeeded(snapshotFor(SESSION_A, "CANONICALIZING"));
    goToOverview();
    expect(
      await screen.findByText(/not a terminal failure/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/ended in failed/i)).not.toBeInTheDocument();
  });

  it("renders headline cards with approved labels", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToOverview();
    for (const label of [
      "Recorded net order value",
      "Recorded profit",
      "Profit margin",
      "Late-shipment rate",
      "On-schedule shipment rate",
      "Orders",
      "Shipment-eligible orders",
      "Units",
    ]) {
      // Each label appears on its card and inside its definition disclosure.
      expect(
        await screen.findAllByText(label, { exact: false }),
      ).not.toHaveLength(0);
    }
    expect(screen.getByText("1,234.56")).toBeInTheDocument();
    expect(screen.getAllByText("50.0%")).toHaveLength(2);
    expect(
      screen.getByText(/commercial scope: all order statuses included/i),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(/1 shipping-cancelled order excluded/i).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("renders unavailable KPIs as unavailable, never zero", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToOverview();
    await screen.findAllByText("Recorded net order value");
    const card = screen.getAllByText("Profit margin")[0].closest("div");
    expect(card?.textContent).toMatch(/Unavailable/);
    expect(card?.textContent).toMatch(/zero-denominator/);
    expect(card?.textContent).not.toMatch(/0\.0%|^0$/);
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("renders amounts with no invented currency", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToOverview();
    await screen.findByText("1,234.56");
    expect(document.body.textContent).not.toMatch(/\$|£|€/);
    expect(screen.getByText(/currency is unspecified/i)).toBeInTheDocument();
  });

  it("renders negative recorded profit honestly", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToOverview();
    await screen.findAllByText("Recorded profit");
    expect(screen.getByText("-45.67")).toBeInTheDocument();
    expect(screen.queryByText(/data error/i)).not.toBeInTheDocument();
  });

  it("renders the monthly trend with an accessible data table", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToOverview();
    await screen.findByText(/by order month/i);
    expect(
      screen.getByRole("img", { name: /monthly recorded net order value/i }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("2024-01").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("2024-03").length).toBeGreaterThanOrEqual(1);
    // Unavailable month leaves an honest gap marker in the table.
    const table = screen.getByRole("table", {
      name: /monthly net order value and profit/i,
    });
    expect(table).toHaveTextContent("Unavailable");
  });

  it("renders the shipment outcome distribution with eligible context", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToOverview();
    await screen.findByText(/shipment outcome distribution/i);
    expect(
      screen.getByRole("img", { name: /late, early, and exactly/i }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(/8 shipment-eligible orders/i).length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/never counted as non-late/i)).toBeInTheDocument();
  });

  it("renders regional performance and the methodology disclosure", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToOverview();
    await screen.findByText(/by destination region/i);
    expect(screen.getByText("North")).toBeInTheDocument();
    expect(screen.getByText("900.00")).toBeInTheDocument();
    expect(screen.getByText(/synthetic demo dataset/i)).toBeInTheDocument();
    expect(
      screen.getByText(/not customer delivery performance/i),
    ).toBeInTheDocument();
  });

  it("exposes no interactive filters; filtering stays deferred", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToOverview();
    await screen.findAllByText("Recorded net order value");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(document.querySelector("#overview select")).toBeNull();
  });

  it("shows a terminal FAILED state without requesting KPIs", async () => {
    renderSeeded(snapshotFor(SESSION_A, "FAILED"));
    goToOverview();
    expect(await screen.findByText(/ended in failed/i)).toBeInTheDocument();
    expect(fetchCalls()).toHaveLength(0);
    expect(
      screen.queryByText("Recorded net order value"),
    ).not.toBeInTheDocument();
  });

  it("shows an error state instead of stale content on API failure", async () => {
    route = (url: string) => {
      if (url.includes("/kpis/overview")) {
        return {
          status: 500,
          body: {
            data: null,
            meta: {},
            error: {
              code: "INTERNAL_STAGE_ERROR",
              stage: "ANALYZING",
              message: "KPI analysis could not be completed.",
              details: {},
            },
          },
        };
      }
      return defaultRoute(url);
    };
    renderSeeded(snapshotFor(SESSION_A, "ANALYZING"));
    goToOverview();
    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument();
    expect(
      screen.queryByText("Recorded net order value"),
    ).not.toBeInTheDocument();
  });

  it("clears headline results when the session is reset", async () => {
    const { rerender } = renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToOverview();
    await screen.findByText("1,234.56");
    rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(null, null)} />
      </SessionProvider>,
    );
    expect(screen.getByText("No dataset loaded")).toBeInTheDocument();
    expect(screen.queryByText("1,234.56")).not.toBeInTheDocument();
  });

  it("never lets a slow old session overwrite a new session", async () => {
    let resolveOverviewA!: (outcome: RouteOutcome) => void;
    const overviewAGate = new Promise<RouteOutcome>((resolve) => {
      resolveOverviewA = resolve;
    });
    route = (url: string) => {
      if (url.includes(SESSION_A) && url.includes("/kpis/overview")) {
        return overviewAGate;
      }
      return defaultRoute(url);
    };
    const { rerender } = renderSeeded(snapshotFor(SESSION_A, "ANALYZING"));
    goToOverview();
    await waitFor(() => {
      expect(fetchCalls().some((url) => url.includes(SESSION_A))).toBe(true);
    });
    rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(SESSION_B, "READY")} />
      </SessionProvider>,
    );
    // Session B's region value (North 700.00; A would show 900.00).
    await screen.findByText("700.00");
    // A's late overview response must be ignored, never overwriting B.
    resolveOverviewA(ok(overviewBody()));
    await waitFor(() => {
      expect(fetchCalls().length).toBeGreaterThan(0);
    });
    expect(screen.getByText("700.00")).toBeInTheDocument();
    expect(screen.queryByText("900.00")).not.toBeInTheDocument();
  });

  it("reloads safely across away/back navigation", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToOverview();
    await screen.findByText("1,234.56");
    const callsAfterLoad = fetchCalls().length;
    fireEvent.click(screen.getByRole("button", { name: "Delivery" }));
    expect(
      screen.getByRole("heading", { name: "Delivery" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Overview" }));
    await screen.findByText("1,234.56");
    expect(fetchCalls().length).toBeGreaterThan(callsAfterLoad);
  });

  it("contains no reference-control constants", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToOverview();
    await screen.findByText("1,234.56");
    // Scoped to the Overview section: the hidden Upload view retains the
    // pre-existing governed reference-file copy ("180,519 rows"), which is
    // upload guidance, not an Overview constant.
    const section = screen
      .getByRole("heading", { name: "Overview" })
      .closest("section");
    expect(section?.textContent).not.toMatch(
      /33,054,402|65,752|180,519|57\.3127|42\.6873/,
    );
  });

  it("reports no axe violations on the loaded overview", async () => {
    const { container } = renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToOverview();
    await screen.findByText("1,234.56");
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("formatKpiValue (display-only formatting)", () => {
  it("formats counts, money, rates, and negatives without arithmetic", () => {
    expect(formatKpiValue("kpi.orders.count", 10)).toBe("10");
    expect(formatKpiValue("kpi.units.total", 275310)).toBe("275,310");
    expect(formatKpiValue("kpi.value.net", "1234.56")).toBe("1,234.56");
    expect(formatKpiValue("kpi.profit.recorded", "-45.67")).toBe("-45.67");
    expect(formatKpiValue("kpi.ship.late_rate", "0.5731")).toBe("57.3%");
    expect(formatKpiValue("kpi.margin.profit", "0.1203")).toBe("12.0%");
    expect(formatKpiValue("kpi.ship.avg_actual_days", "3.25")).toBe("3.25");
    expect(formatKpiValue("kpi.unknown.future", "7")).toBe("7");
  });
});
