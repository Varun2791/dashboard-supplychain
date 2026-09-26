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

function goToCommercial(): void {
  fireEvent.click(screen.getByRole("button", { name: "Commercial" }));
  expect(
    screen.getByRole("heading", { name: "Commercial" }),
  ).toBeInTheDocument();
}

interface KpiFixture {
  id: string;
  label: string;
  value: number | string | null;
  status?: string;
  reason?: string | null;
  missing?: number;
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
    missingDataCount: fixture.missing ?? 0,
  };
}

function money(id: string, label: string, value: string): unknown {
  return kpi({ id, label, value });
}

function count(id: string, label: string, value: number): unknown {
  return kpi({ id, label, value });
}

/** Small arbitrary values — never DataCo reference controls. */
function overviewBody() {
  return {
    data: {
      kpis: [
        money("kpi.value.gross", "Gross order value", "1840.50"),
        kpi({
          id: "kpi.value.discount",
          label: "Discounts",
          value: "210.25",
          missing: 2,
        }),
        money("kpi.value.net", "Recorded net order value", "1630.25"),
        money("kpi.profit.recorded", "Recorded profit", "-45.67"),
        kpi({
          id: "kpi.margin.profit",
          label: "Profit margin",
          value: "-0.028",
        }),
        kpi({
          id: "kpi.rate.discount",
          label: "Discount rate",
          value: "0.1142",
        }),
        money("kpi.value.aov", "Average net per order", "41.75"),
        kpi({
          id: "kpi.units.per_order",
          label: "Units per order",
          value: "3.20",
        }),
        kpi({
          id: "kpi.lines.per_order",
          label: "Lines per order",
          value: "1.60",
        }),
        kpi({
          id: "kpi.orders.loss_making_rate",
          label: "Loss-making-order rate",
          value: "0.2",
        }),
        money(
          "kpi.value.net_associated_with_late",
          "Net order value associated with late shipments",
          "512.40",
        ),
        count("kpi.units.total", "Units", 96),
      ],
      totals: {
        items: 31,
        orders: 29,
        eligibleOrders: 27,
        grossValue: "1840.50",
        discountTotal: "210.25",
        netValue: "1630.25",
        profitTotal: "-45.67",
        units: 96,
      },
    },
    meta: {},
    error: null,
  };
}

function commercialBody() {
  return {
    data: {
      groups: [],
      statusScope: "all-status",
      weightedRates: { profitMargin: "-0.028", discountRate: "0.1142" },
    },
    meta: {},
    error: null,
  };
}

interface GroupSpec {
  key: string;
  net: string | null;
  profit: string | null;
  margin: string | null;
  discount: string;
  discountRate: string | null;
  lossRate: string | null;
}

function group(spec: GroupSpec): unknown {
  const entry = (
    id: string,
    label: string,
    value: number | string | null,
  ): unknown =>
    kpi({
      id,
      label,
      value,
      status: value === null ? "unavailable" : "ok",
      reason: value === null ? "zero-denominator" : null,
    });
  return {
    key: spec.key,
    kpis: [
      entry("kpi.value.net", "Recorded net order value", spec.net),
      entry("kpi.profit.recorded", "Recorded profit", spec.profit),
      entry("kpi.margin.profit", "Profit margin", spec.margin),
      entry("kpi.value.discount", "Discounts", spec.discount),
      entry("kpi.rate.discount", "Discount rate", spec.discountRate),
      entry(
        "kpi.orders.loss_making_rate",
        "Loss-making-order rate",
        spec.lossRate,
      ),
    ],
  };
}

function groupedBody(by: string, sessionB: boolean): unknown {
  const tables: Record<string, GroupSpec[]> = {
    department_name: sessionB
      ? [
          {
            key: "Golf",
            net: "1630.25",
            profit: "-45.67",
            margin: "-0.028",
            discount: "210.25",
            discountRate: "0.1142",
            lossRate: "0.2",
          },
        ]
      : [
          {
            key: "Apparel",
            net: "900.00",
            profit: "120.00",
            margin: "0.1333",
            discount: "100.00",
            discountRate: "0.1",
            lossRate: "0.1",
          },
          {
            key: "Footwear",
            net: "730.25",
            profit: "-165.67",
            margin: "-0.2269",
            discount: "110.25",
            discountRate: "0.1312",
            lossRate: "0.3",
          },
        ],
    category_name: [
      {
        key: "Cleats",
        net: "900.00",
        profit: "120.00",
        margin: "0.1333",
        discount: "100.00",
        discountRate: "0.1",
        lossRate: "0.1",
      },
    ],
    product_name: [
      {
        key: "Trail Boot X",
        net: "730.25",
        profit: "-165.67",
        margin: "-0.2269",
        discount: "110.25",
        discountRate: "0.1312",
        lossRate: "0.3",
      },
    ],
    destination_market: [
      {
        key: "Pacific Rim",
        net: "1630.25",
        profit: "-45.67",
        margin: "-0.028",
        discount: "210.25",
        discountRate: "0.1142",
        lossRate: "0.2",
      },
    ],
    destination_region: [
      {
        key: "North Coast",
        net: "1630.25",
        profit: "-45.67",
        margin: "-0.028",
        discount: "210.25",
        discountRate: "0.1142",
        lossRate: "0.2",
      },
    ],
    customer_segment: [
      {
        key: "Home Office",
        net: "1630.25",
        profit: "-45.67",
        margin: null,
        discount: "210.25",
        discountRate: "0.1142",
        lossRate: "0.2",
      },
    ],
  };
  return {
    data: {
      groups: (tables[by] ?? []).map((spec) => group(spec)),
      statusScope: "all-status",
      weightedRates: { profitMargin: "-0.028", discountRate: "0.1142" },
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
  if (url.includes("/kpis/commercial")) {
    const match = url.match(/by=([a-z_]+)/);
    if (match === null) {
      return ok(commercialBody());
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

function commercialSection(): HTMLElement {
  const heading = screen.getByRole("heading", { name: "Commercial" });
  const section = heading.closest("section");
  if (section === null) {
    throw new Error("Commercial section not found");
  }
  return section;
}

describe("Phase-14 Commercial analytics", () => {
  it("renders the governed empty state without requesting KPIs", () => {
    renderSeeded(snapshotFor(null, null));
    goToCommercial();
    expect(screen.getByText("No dataset loaded")).toBeInTheDocument();
    expect(fetchCalls()).toHaveLength(0);
  });

  it("renders loading progress while KPI analysis is not ready", async () => {
    route = () => notReady();
    renderSeeded(snapshotFor(SESSION_A, "ANALYZING"));
    goToCommercial();
    expect(
      await screen.findByText(/loading the commercial results/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchCalls().some((url) => url.includes("/kpis/commercial"))).toBe(
      true,
    );
  });

  it("explains a governed gate as recoverable, not terminal", async () => {
    route = () => notReady();
    renderSeeded(snapshotFor(SESSION_A, "CANONICALIZING"));
    goToCommercial();
    expect(
      await screen.findByText(/not a terminal failure/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/ended in failed/i)).not.toBeInTheDocument();
  });

  it("renders headline commercial cards with approved backend labels", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    for (const label of [
      "Gross order value",
      "Discounts",
      "Recorded net order value",
      "Recorded profit",
      "Profit margin",
      "Discount rate",
      "Average net per order",
      "Units per order",
      "Lines per order",
      "Loss-making-order rate",
      "Net order value associated with late shipments",
    ]) {
      expect(
        await screen.findAllByText(label, { exact: false }),
      ).not.toHaveLength(0);
    }
  });

  it("calls recorded value by its governed name, never revenue", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findAllByText("Recorded net order value");
    const section = commercialSection();
    // The page's own disclosure legitimately contrasts the approved term
    // with the prohibited one (as kpi-contracts.md does), so "revenue" is
    // asserted as a negation, and any other occurrence fails.
    expect(section.textContent).toMatch(/not recognized revenue/);
    expect(
      section.textContent?.replace(/not recognized revenue/gi, ""),
    ).not.toMatch(/revenue|turnover|GMV|EBIT/i);
    expect(
      screen.getAllByText(/authoritative commercial total/i).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("renders amounts currency-neutral with consistent decimals", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findAllByText("Recorded net order value");
    const section = commercialSection();
    expect(section.textContent).not.toMatch(/[$£€]|USD|GBP|EUR/);
    expect(screen.getAllByText("1,630.25").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("11.4%").length).toBeGreaterThanOrEqual(1);
  });

  it("retains negative recorded profit without clipping", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findAllByText("Recorded net order value");
    expect(screen.getAllByText("-45.67").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/never clipped/i).length).toBeGreaterThanOrEqual(
      1,
    );
    expect(screen.queryByText("0.00")).not.toBeInTheDocument();
  });

  it("renders the backend amount-weighted margin without averaging", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findAllByText("Recorded net order value");
    expect(screen.getAllByText("-2.8%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/never averages/i)).toBeInTheDocument();
  });

  it("renders an unavailable group margin as unavailable, never zero", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findByText("Home Office");
    const table = screen.getByRole("table", {
      name: /commercial value by customer segment/i,
    });
    expect(table).toHaveTextContent("Unavailable");
    // The margin cell itself is unavailable — never a zero percent. (The
    // loss-rate column legitimately holds 20.0%, so assert per-cell.)
    const body = within(table).getAllByRole("row").slice(1);
    expect(body).toHaveLength(1);
    const cells = within(body[0]).getAllByRole("cell");
    expect(cells[3].textContent).toBe("Unavailable");
  });

  it("describes discount without loss or leakage language", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findAllByText("Recorded net order value");
    const section = commercialSection();
    expect(section.textContent).not.toMatch(
      /lost revenue|profit leakage|avoidable loss/i,
    );
    expect(screen.getAllByText("11.4%").length).toBeGreaterThanOrEqual(1);
  });

  it("renders backend department groups that reconcile to the headline net", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findByText("Footwear");
    expect(screen.getByText("Apparel")).toBeInTheDocument();
    // Backend group keys verbatim; no frontend shares or subtotals.
    const table = screen.getByRole("table", {
      name: /commercial value by department/i,
    });
    expect(table).toHaveTextContent("900.00");
    expect(table).toHaveTextContent("730.25");
    expect(table).toHaveTextContent("-22.7%");
    expect(table).not.toHaveTextContent("Unavailable");
    // Grouped commercial responses never carry kpi.units.total
    // (compute_commercial does not emit it); units analysis lives on the
    // headline cards, so no group table may expose a Units column.
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    expect(headers).not.toContain("Units");
  });

  it("renders category, product, market, region, and segment breakdowns", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findByText("Footwear");
    for (const name of [
      /commercial value by product category/i,
      /commercial value by product$/i,
      /commercial value by destination market/i,
      /commercial value by destination region/i,
      /commercial value by customer segment/i,
    ]) {
      expect(screen.getByRole("table", { name })).toBeInTheDocument();
    }
    expect(screen.getByText("Cleats")).toBeInTheDocument();
    expect(screen.getByText("Trail Boot X")).toBeInTheDocument();
    expect(screen.getByText("Pacific Rim")).toBeInTheDocument();
    expect(screen.getByText("North Coast")).toBeInTheDocument();
    expect(screen.getByText("Home Office")).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: /recorded net order value.*product category/i,
      }),
    ).toBeInTheDocument();
  });

  it("keeps department, category, and product distinct", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findByText("Footwear");
    const section = commercialSection();
    expect(section.textContent).toMatch(/department, not category or product/i);
    expect(section.textContent).toMatch(/No reference price/i);
  });

  it("shows the order-status scope and late association without causal loss", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findAllByText("Recorded net order value");
    expect(
      screen.getByText(/order-status scope: all-status/i),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(/never lost sales/i).length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("512.40")).toBeInTheDocument();
    expect(commercialSection().textContent).not.toMatch(
      /caused lower profit|discount caused|shipping caused/i,
    );
  });

  it("surfaces missing-data context where the backend reports it", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findAllByText("Recorded net order value");
    expect(
      screen.getByText(/2 rows excluded for missing fields/i),
    ).toBeInTheDocument();
  });

  it("uses governed commercial terminology with association-only language", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findAllByText("Recorded net order value");
    const section = commercialSection();
    expect(section.textContent).not.toMatch(
      /OTIF|on-time delivery|perfect order|service level|forecast|prediction|inventory|supplier|warehouse|freight|returns analysis/i,
    );
    expect(section.textContent).not.toMatch(
      /\bbest\b|\bworst\b|top 3|bottom 3/i,
    );
    expect(section.textContent).not.toMatch(
      /because|causes|customer delivery/i,
    );
    expect(section.textContent).toMatch(/association, not causation/);
    expect(screen.getByText(/not recognized revenue/i)).toBeInTheDocument();
  });

  it("exposes no interactive filters; filtering stays deferred", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findAllByText("Recorded net order value");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(commercialSection().querySelector("select")).toBeNull();
  });

  it("exposes no personal fields in the customer-segment breakdown", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findByText("Home Office");
    expect(commercialSection().textContent).not.toMatch(
      /first name|last name|street|email|password/i,
    );
  });

  it("shows a terminal FAILED state without requesting KPIs", async () => {
    renderSeeded(snapshotFor(SESSION_A, "FAILED"));
    goToCommercial();
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
    goToCommercial();
    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument();
    expect(
      screen.queryByText("Recorded net order value"),
    ).not.toBeInTheDocument();
  });

  it("clears commercial results when the session is reset", async () => {
    const { rerender } = renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findByText("Footwear");
    rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(null, null)} />
      </SessionProvider>,
    );
    expect(screen.getByText("No dataset loaded")).toBeInTheDocument();
    expect(screen.queryByText("Footwear")).not.toBeInTheDocument();
  });

  it("never lets a slow old session overwrite a new session", async () => {
    let resolveDeptA!: (outcome: RouteOutcome) => void;
    const deptAGate = new Promise<RouteOutcome>((resolve) => {
      resolveDeptA = resolve;
    });
    route = (url: string) => {
      if (url.includes(SESSION_A) && url.includes("by=department_name")) {
        return deptAGate;
      }
      return defaultRoute(url);
    };
    const { rerender } = renderSeeded(snapshotFor(SESSION_A, "ANALYZING"));
    goToCommercial();
    await waitFor(() => {
      expect(fetchCalls().some((url) => url.includes(SESSION_A))).toBe(true);
    });
    rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(SESSION_B, "READY")} />
      </SessionProvider>,
    );
    // Session B's department group key; A's would be "Footwear".
    await screen.findByText("Golf");
    resolveDeptA(ok(groupedBody("department_name", false)));
    await waitFor(() => {
      expect(fetchCalls().length).toBeGreaterThan(0);
    });
    expect(screen.getByText("Golf")).toBeInTheDocument();
    expect(screen.queryByText("Footwear")).not.toBeInTheDocument();
  });

  it("reloads safely across away/back navigation", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findByText("Footwear");
    const callsAfterLoad = fetchCalls().length;
    fireEvent.click(screen.getByRole("button", { name: "Overview" }));
    expect(
      screen.getByRole("heading", { name: "Overview" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Commercial" }));
    await screen.findByText("Footwear");
    expect(fetchCalls().length).toBeGreaterThan(callsAfterLoad);
  });

  it("contains no reference-control constants", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findByText("Footwear");
    expect(commercialSection().textContent).not.toMatch(
      /33,054,402|65,752|180,519|20,652|384,079|3,730,378|3,966,902|36,784,735|13,909/,
    );
  });

  it("reports no axe violations on the loaded commercial page", async () => {
    const { container } = renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToCommercial();
    await screen.findByText("Footwear");
    expect(await axe(container)).toHaveNoViolations();
  });
});
