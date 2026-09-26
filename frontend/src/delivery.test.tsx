import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
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

function goToDelivery(): void {
  fireEvent.click(screen.getByRole("button", { name: "Delivery" }));
  expect(screen.getByRole("heading", { name: "Delivery" })).toBeInTheDocument();
}

interface KpiFixture {
  id: string;
  label: string;
  value: number | string | null;
  status?: string;
  reason?: string | null;
  denominator?: number | null;
  missing?: number;
}

function kpi(fixture: KpiFixture) {
  return {
    id: fixture.id,
    label: fixture.label,
    value: fixture.value,
    status: fixture.status ?? "ok",
    numerator: fixture.value,
    denominator: fixture.denominator ?? null,
    population: `Population for ${fixture.id}.`,
    exclusions: `Exclusions for ${fixture.id}.`,
    reason: fixture.reason ?? null,
    missingDataCount: fixture.missing ?? 0,
  };
}

function rate(
  id: string,
  label: string,
  fraction: string | null,
  count: number,
  eligible: number,
): unknown {
  const base = kpi({
    id,
    label,
    value: fraction,
    status: fraction === null ? "unavailable" : "ok",
    reason: fraction === null ? "empty-eligible-population" : null,
    denominator: eligible,
  });
  return { ...base, numerator: count };
}

function count(id: string, label: string, value: number): unknown {
  return kpi({ id, label, value });
}

/** Small arbitrary values — never DataCo reference controls. */
function overviewBody() {
  return {
    data: {
      kpis: [
        kpi({
          id: "kpi.ship.late_rate",
          label: "Late-shipment rate",
          value: "0.4",
          denominator: 20,
        }),
        kpi({
          id: "kpi.ship.on_schedule_rate",
          label: "On-schedule shipment rate",
          value: "0.6",
          denominator: 20,
        }),
        kpi({
          id: "kpi.ship.early_rate",
          label: "Early-shipment rate",
          value: "0.25",
          denominator: 20,
        }),
        kpi({
          id: "kpi.ship.exact_rate",
          label: "Exactly on-schedule rate",
          value: "0.35",
          denominator: 20,
        }),
        kpi({
          id: "kpi.ship.avg_actual_days",
          label: "Average actual shipping days",
          value: "3.25",
          missing: 2,
        }),
        kpi({
          id: "kpi.ship.avg_scheduled_days",
          label: "Average scheduled shipping days",
          value: "4.00",
        }),
        kpi({
          id: "kpi.ship.variance_days",
          label: "Average schedule variance (days)",
          value: null,
          status: "unavailable",
          reason: "missing-required-fields",
        }),
        kpi({
          id: "kpi.orders.strict_cancel_rate",
          label: "Strict cancellation rate",
          value: "0.02",
        }),
        kpi({
          id: "kpi.orders.fraud_rate",
          label: "Suspected-fraud rate",
          value: "0.03",
        }),
        kpi({
          id: "kpi.orders.blocked_rate",
          label: "Shipping-blocked rate",
          value: "0.05",
        }),
      ],
      totals: {
        items: 24,
        orders: 22,
        eligibleOrders: 20,
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
      eligibleOrders: 20,
      exclusions: "2 shipping-cancelled orders excluded",
    },
    meta: {},
    error: null,
  };
}

interface GroupSpec {
  key: string;
  lateRate: string | null;
  late: number;
  early: number;
  exact: number;
  eligible: number;
  avgActual?: string | null;
}

function group(spec: GroupSpec): unknown {
  return {
    key: spec.key,
    kpis: [
      rate(
        "kpi.ship.late_rate",
        "Late-shipment rate",
        spec.lateRate,
        spec.late,
        spec.eligible,
      ),
      count("kpi.ship.late_count", "Late orders", spec.late),
      count("kpi.ship.early_count", "Early orders", spec.early),
      count("kpi.ship.exact_count", "Exactly on-schedule orders", spec.exact),
      kpi({
        id: "kpi.ship.avg_actual_days",
        label: "Average actual shipping days",
        value: spec.avgActual ?? "3.10",
      }),
      kpi({
        id: "kpi.ship.avg_scheduled_days",
        label: "Average scheduled shipping days",
        value: "4.00",
      }),
      kpi({
        id: "kpi.ship.variance_days",
        label: "Average schedule variance (days)",
        value: "-0.90",
      }),
    ],
  };
}

function groupedBody(by: string, sessionB: boolean): unknown {
  const modeGroups = sessionB
    ? [
        {
          key: "Overnight",
          lateRate: "0.9",
          late: 9,
          early: 0,
          exact: 1,
          eligible: 10,
        },
      ]
    : [
        {
          key: "Second Class",
          lateRate: "0.3",
          late: 3,
          early: 4,
          exact: 3,
          eligible: 10,
        },
        {
          key: "Standard Class",
          lateRate: "0.5",
          late: 5,
          early: 2,
          exact: 3,
          eligible: 10,
        },
      ];
  const tables: Record<string, GroupSpec[]> = {
    shipping_mode: modeGroups,
    destination_region: sessionB
      ? [
          {
            key: "West",
            lateRate: "0.9",
            late: 9,
            early: 0,
            exact: 1,
            eligible: 10,
          },
        ]
      : [
          {
            key: "North",
            lateRate: "0.5",
            late: 6,
            early: 3,
            exact: 3,
            eligible: 12,
          },
          {
            key: "South",
            lateRate: "0.25",
            late: 2,
            early: 3,
            exact: 3,
            eligible: 8,
          },
        ],
    destination_market: [
      {
        key: "Pacific",
        lateRate: "0.4",
        late: 8,
        early: 6,
        exact: 6,
        eligible: 20,
      },
    ],
    category_name: [
      {
        key: "Fishing",
        lateRate: "0.4",
        late: 8,
        early: 6,
        exact: 6,
        eligible: 20,
      },
    ],
    order_month: [
      {
        key: "2024-01",
        lateRate: "0.5",
        late: 6,
        early: 3,
        exact: 3,
        eligible: 12,
      },
      {
        key: "2024-02",
        lateRate: "0.25",
        late: 2,
        early: 3,
        exact: 3,
        eligible: 8,
      },
      {
        key: "2024-03",
        lateRate: null,
        late: 0,
        early: 0,
        exact: 0,
        eligible: 0,
      },
    ],
  };
  return {
    data: {
      groups: (tables[by] ?? []).map((spec) => group(spec)),
      eligibleOrders: 20,
      exclusions: "2 shipping-cancelled orders excluded",
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
  const sessionB = url.includes(SESSION_B);
  if (url.includes("/kpis/overview")) {
    return ok(overviewBody());
  }
  if (url.includes("/kpis/delivery")) {
    const match = url.match(/by=([a-z_]+)/);
    if (match === null) {
      return ok(deliveryBody());
    }
    return ok(groupedBody(match[1], sessionB));
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

function deliverySection(): HTMLElement {
  const heading = screen.getByRole("heading", { name: "Delivery" });
  const section = heading.closest("section");
  if (section === null) {
    throw new Error("Delivery section not found");
  }
  return section;
}

describe("Phase-13 Delivery analytics", () => {
  it("renders the governed empty state without requesting KPIs", () => {
    renderSeeded(snapshotFor(null, null));
    goToDelivery();
    expect(screen.getByText("No dataset loaded")).toBeInTheDocument();
    expect(fetchCalls()).toHaveLength(0);
  });

  it("renders loading progress while KPI analysis is not ready", async () => {
    route = () => notReady();
    renderSeeded(snapshotFor(SESSION_A, "ANALYZING"));
    goToDelivery();
    expect(
      await screen.findByText(/loading the shipment results/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchCalls().some((url) => url.includes("/kpis/delivery"))).toBe(
      true,
    );
  });

  it("explains a governed gate as recoverable, not terminal", async () => {
    route = () => notReady();
    renderSeeded(snapshotFor(SESSION_A, "CANONICALIZING"));
    goToDelivery();
    expect(
      await screen.findByText(/not a terminal failure/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/ended in failed/i)).not.toBeInTheDocument();
  });

  it("renders headline delivery cards with approved labels", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    for (const label of [
      "Late-shipment rate",
      "On-schedule shipment rate",
      "Early-shipment rate",
      "Exactly on-schedule rate",
      "Average actual shipping days",
      "Average scheduled shipping days",
      "Average schedule variance (days)",
    ]) {
      expect(
        await screen.findAllByText(label, { exact: false }),
      ).not.toHaveLength(0);
    }
    expect(screen.getAllByText("40.0%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("60.0%")).toBeInTheDocument();
    expect(screen.getByText("3.25")).toBeInTheDocument();
  });

  it("keeps cancellation and suspected fraud separate", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    await screen.findAllByText("Late-shipment rate");
    for (const label of [
      "Strict cancellation rate",
      "Suspected-fraud rate",
      "Shipping-blocked rate",
    ]) {
      expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1);
    }
    expect(screen.getByText(/never implies fraud/i)).toBeInTheDocument();
    expect(screen.queryByText(/failed/i)).not.toBeInTheDocument();
    expect(screen.getByText("2.0%")).toBeInTheDocument();
  });

  it("explains the eligible population without cancelled-as-non-late", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    await screen.findAllByText("Late-shipment rate");
    expect(
      screen.getAllByText(/20 shipment-eligible orders/i).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByText(/2 shipping-cancelled orders excluded/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/never count as non-late/i)).toBeInTheDocument();
  });

  it("renders unavailable day averages as unavailable, never zero", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    await screen.findAllByText("Late-shipment rate");
    const card = screen
      .getAllByText("Average schedule variance (days)")[0]
      .closest("div");
    expect(card?.textContent).toMatch(/Unavailable/);
    expect(card?.textContent).toMatch(/missing-required-fields/);
    expect(screen.queryByText("0.00")).not.toBeInTheDocument();
  });

  it("renders backend mode groups with backend eligible counts", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    await screen.findByText("Standard Class");
    expect(screen.getByText("Second Class")).toBeInTheDocument();
    // Backend group keys verbatim; backend denominators, not arithmetic.
    const table = screen.getByRole("table", {
      name: /late-shipment rate by shipping mode/i,
    });
    expect(table).toHaveTextContent("50.0%");
    expect(table).toHaveTextContent("Standard Class");
    expect(
      screen.getByRole("img", { name: /late-shipment rate.*shipping mode/i }),
    ).toBeInTheDocument();
  });

  it("reconciles per-group eligible counts to the headline total", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    await screen.findByText("Standard Class");
    const table = screen.getByRole("table", {
      name: /late-shipment rate by shipping mode/i,
    });
    const body = within(table).getAllByRole("row").slice(1);
    // 10 + 10 eligible across the two mode groups == headline 20.
    expect(body).toHaveLength(2);
    for (const row of body) {
      expect(row.textContent).toMatch(/10/);
    }
  });

  it("renders region, market, category, and month breakdowns", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    await screen.findByText("Standard Class");
    for (const name of [
      /late-shipment rate by destination region/i,
      /late-shipment rate by destination market/i,
      /late-shipment rate by product category/i,
      /late-shipment rate by order month/i,
    ]) {
      expect(screen.getByRole("table", { name })).toBeInTheDocument();
    }
    expect(screen.getByText("North")).toBeInTheDocument();
    expect(screen.getByText("Pacific")).toBeInTheDocument();
    expect(screen.getByText("Fishing")).toBeInTheDocument();
    expect(screen.getByText("2024-01")).toBeInTheDocument();
    // Unavailable month renders honestly, never as zero.
    const monthTable = screen.getByRole("table", {
      name: /late-shipment rate by order month/i,
    });
    expect(monthTable).toHaveTextContent("Unavailable");
  });

  it("surfaces missing-data context where the backend reports it", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    await screen.findAllByText("Late-shipment rate");
    expect(
      screen.getByText(/2 rows excluded for missing fields/i),
    ).toBeInTheDocument();
  });

  it("uses shipment-adherence terminology, never customer-delivery claims", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    await screen.findAllByText("Late-shipment rate");
    const section = deliverySection();
    // Banned positive claims. The page's own disclosure legitimately
    // contrasts approved terms with prohibited ones (as kpi-contracts.md
    // does), so "customer delivery" is asserted separately as a negation.
    expect(section.textContent).not.toMatch(
      /OTIF|on-time delivery|perfect order|service level/i,
    );
    expect(
      screen.getByText(/not customer delivery performance/i),
    ).toBeInTheDocument();
    expect(section.textContent).not.toMatch(/causes lateness|because/i);
    expect(section.textContent).not.toMatch(/Late_delivery_risk/);
    expect(section.textContent).toMatch(/not causation|association/i);
    expect(
      screen.getByText(/not customer delivery performance/i),
    ).toBeInTheDocument();
  });

  it("exposes no interactive filters; filtering stays deferred", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    await screen.findAllByText("Late-shipment rate");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(deliverySection().querySelector("select")).toBeNull();
  });

  it("shows a terminal FAILED state without requesting KPIs", async () => {
    renderSeeded(snapshotFor(SESSION_A, "FAILED"));
    goToDelivery();
    expect(await screen.findByText(/ended in failed/i)).toBeInTheDocument();
    expect(fetchCalls()).toHaveLength(0);
    expect(screen.queryByText("Late-shipment rate")).not.toBeInTheDocument();
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
    goToDelivery();
    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText("Late-shipment rate")).not.toBeInTheDocument();
  });

  it("clears shipment results when the session is reset", async () => {
    const { rerender } = renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    await screen.findByText("Standard Class");
    rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(null, null)} />
      </SessionProvider>,
    );
    expect(screen.getByText("No dataset loaded")).toBeInTheDocument();
    expect(screen.queryByText("Standard Class")).not.toBeInTheDocument();
  });

  it("never lets a slow old session overwrite a new session", async () => {
    let resolveModeA!: (outcome: RouteOutcome) => void;
    const modeAGate = new Promise<RouteOutcome>((resolve) => {
      resolveModeA = resolve;
    });
    route = (url: string) => {
      if (url.includes(SESSION_A) && url.includes("by=shipping_mode")) {
        return modeAGate;
      }
      return defaultRoute(url);
    };
    const { rerender } = renderSeeded(snapshotFor(SESSION_A, "ANALYZING"));
    goToDelivery();
    await waitFor(() => {
      expect(fetchCalls().some((url) => url.includes(SESSION_A))).toBe(true);
    });
    rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(SESSION_B, "READY")} />
      </SessionProvider>,
    );
    // Session B's mode group key; A's would be "Standard Class".
    await screen.findByText("Overnight");
    resolveModeA(ok(groupedBody("shipping_mode", false)));
    await waitFor(() => {
      expect(fetchCalls().length).toBeGreaterThan(0);
    });
    expect(screen.getByText("Overnight")).toBeInTheDocument();
    expect(screen.queryByText("Standard Class")).not.toBeInTheDocument();
  });

  it("reloads safely across away/back navigation", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    await screen.findByText("Standard Class");
    const callsAfterLoad = fetchCalls().length;
    fireEvent.click(screen.getByRole("button", { name: "Overview" }));
    expect(
      screen.getByRole("heading", { name: "Overview" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delivery" }));
    await screen.findByText("Standard Class");
    expect(fetchCalls().length).toBeGreaterThan(callsAfterLoad);
  });

  it("contains no reference-control constants", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    await screen.findByText("Standard Class");
    expect(deliverySection().textContent).not.toMatch(
      /33,054,402|65,752|180,519|57\.3127|42\.6873|36,048|15,127|11,722/,
    );
  });

  it("reports no axe violations on the loaded delivery page", async () => {
    const { container } = renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDelivery();
    await screen.findByText("Standard Class");
    expect(await axe(container)).toHaveNoViolations();
  });
});
