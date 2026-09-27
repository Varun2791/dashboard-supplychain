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

function goToDiagnostics(): void {
  fireEvent.click(screen.getByRole("button", { name: "Diagnostics" }));
  expect(
    screen.getByRole("heading", { name: "Diagnostics" }),
  ).toBeInTheDocument();
}

function kpi(
  id: string,
  label: string,
  value: number | string | null,
  denominator: number | null,
  status?: string,
) {
  return {
    id,
    label,
    value,
    status: status ?? (value === null ? "unavailable" : "ok"),
    numerator: value,
    denominator,
    population: `Population for ${id}.`,
    exclusions: `Exclusions for ${id}.`,
    reason: value === null ? "empty-eligible-population" : null,
    missingDataCount: 0,
  };
}

function lateGroup(key: string, rate: string | null, eligible: number | null) {
  return {
    key,
    kpis: [
      kpi("kpi.ship.late_rate", "Late-shipment rate", rate, eligible),
      kpi("kpi.ship.late_count", "Late orders", 1, null),
    ],
  };
}

function lossGroup(key: string, rate: string | null, orders: number | null) {
  return {
    key,
    kpis: [
      kpi(
        "kpi.orders.loss_making_rate",
        "Loss-making-order rate",
        rate,
        orders,
      ),
    ],
  };
}

/** Source order deliberately differs from the expected presentation order. */
function shipmentGroups() {
  return [
    lateGroup("QM-Gamma", "0.1000", 10),
    lateGroup("QM-Zeta", "0.9000", 4),
    lateGroup("QM-Void", null, null),
    lateGroup("QM-Beta", "0.5000", 8),
    lateGroup("QM-Alpha", "0.5000", 6),
  ];
}

function commercialGroups() {
  return [
    lossGroup("D-Two", "0.1000", 10),
    lossGroup("D-One", "0.6000", 5),
    lossGroup("D-Gone", null, null),
  ];
}

function orderRow(overrides: Record<string, unknown>) {
  return {
    order_id: "O-1",
    order_timestamp: "2021-03-15T10:00:00",
    order_status: "COMPLETE",
    shipping_mode: "STANDARD_CLASS",
    customer_segment: "CONSUMER",
    destination_country: "C-Land",
    destination_region: "R1",
    destination_market: "M1",
    scheduled_shipping_days: 2,
    actual_shipping_days: 2,
    shipment_outcome: "ON_SCHEDULE",
    is_late: false,
    line_count: 1,
    total_units: 2,
    gross_value: "100.00",
    discount_total: "0.00",
    net_value: "100.00",
    profit_total: "5.00",
    ...overrides,
  };
}

function ordersPageOne() {
  return {
    data: {
      rows: [
        orderRow({
          order_id: "O-11",
          order_timestamp: "2021-03-20T08:00:00",
          order_status: "SUSPECTED_FRAUD",
          shipment_outcome: "LATE",
          is_late: true,
          net_value: "70.00",
          profit_total: "7.00",
        }),
        orderRow({
          order_id: "O-9",
          order_timestamp: "2021-03-10T09:00:00",
          order_status: "CANCELED",
          shipment_outcome: "SHIPPING_CANCELED",
          is_late: null,
          actual_shipping_days: null,
          net_value: "60.00",
          profit_total: "6.00",
        }),
      ],
      page: { nextCursor: "CURSOR-1", total: 3 },
    },
    meta: {},
    error: null,
  };
}

function ordersPageTwo() {
  return {
    data: {
      rows: [
        orderRow({
          order_id: "O-7",
          order_timestamp: "2021-03-12T08:00:00",
          order_status: "PROCESSING",
          shipment_outcome: "EARLY",
          is_late: false,
          actual_shipping_days: 1,
          net_value: "40.00",
          profit_total: "-50.00",
        }),
      ],
      page: { nextCursor: null, total: 3 },
    },
    meta: {},
    error: null,
  };
}

function filterOptionsBody() {
  return {
    data: {
      dateRange: { minOrderDate: "2021-03-10", maxOrderDate: "2021-03-20" },
      markets: ["M1", "M2"],
      regions: ["R1", "R2"],
      categories: ["Alpha", "Beta"],
    },
    meta: {},
    error: null,
  };
}

type RouteOutcome = { status: number; body: unknown };

function ok(body: unknown): RouteOutcome {
  return { status: 200, body };
}

let route: (url: string) => RouteOutcome | Promise<RouteOutcome>;

function deliveryPayload(by: string | null) {
  if (by === null) {
    return {
      data: {
        groups: [],
        eligibleOrders: 8,
        exclusions: "0 shipping-cancelled orders excluded",
      },
      meta: {},
      error: null,
    };
  }
  return {
    data: {
      groups: shipmentGroups(),
      eligibleOrders: 8,
      exclusions: "0 shipping-cancelled orders excluded",
    },
    meta: {},
    error: null,
  };
}

function commercialPayload() {
  return {
    data: {
      groups: commercialGroups(),
      statusScope: "all-status",
      weightedRates: { profitMargin: null, discountRate: null },
    },
    meta: {},
    error: null,
  };
}

function defaultRoute(url: string): RouteOutcome {
  if (url.includes("/filter-options")) {
    return ok(filterOptionsBody());
  }
  if (url.includes("/kpis/delivery")) {
    const match = url.match(/by=([a-z_]+)/);
    return ok(deliveryPayload(match === null ? null : match[1]));
  }
  if (url.includes("/kpis/commercial")) {
    return ok(commercialPayload());
  }
  if (url.includes("/orders")) {
    if (url.includes("category=Beta")) {
      return ok({
        data: { rows: [], page: { nextCursor: null, total: 0 } },
        meta: {},
        error: null,
      });
    }
    if (url.includes("cursor=")) {
      return ok(ordersPageTwo());
    }
    return ok(ordersPageOne());
  }
  return ok(overviewBody());
}

function overviewBody() {
  return {
    data: {
      kpis: [kpi("kpi.orders.count", "Orders", 3, null)],
      totals: {
        items: 4,
        orders: 3,
        eligibleOrders: 2,
        grossValue: "170.00",
        discountTotal: "0.00",
        netValue: "170.00",
        profitTotal: "-37.00",
        units: 6,
      },
    },
    meta: {},
    error: null,
  };
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

function shipmentTable(): HTMLElement {
  return screen.getByRole("table", {
    name: "Associated groups ordered by observed late-shipment rate",
  });
}

function commercialTable(): HTMLElement {
  return screen.getByRole("table", {
    name: "Associated groups ordered by observed loss-making-order rate",
  });
}

function rowKeys(table: HTMLElement): string[] {
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0].textContent ?? "");
}

describe("Phase-15B diagnostics rankings", () => {
  it("offers only the four governed shipment dimensions", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByRole("table", {
      name: "Associated groups ordered by observed late-shipment rate",
    });
    const select = screen.getByLabelText("Rank by", {
      selector: "#diagnostics-shipment-dimension",
    }) as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.value)).toEqual([
      "shipping_mode",
      "destination_market",
      "destination_region",
      "category_name",
    ]);
  });

  it("orders backend late rates descending with deterministic ties", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByRole("table", {
      name: "Associated groups ordered by observed late-shipment rate",
    });
    // Source order was Gamma, Zeta, Void, Beta, Alpha: presentation proves
    // the frontend ordering (Zeta, Alpha, Beta, Gamma, Void).
    expect(rowKeys(shipmentTable())).toEqual([
      "QM-Zeta",
      "QM-Alpha",
      "QM-Beta",
      "QM-Gamma",
      "QM-Void",
    ]);
    const table = shipmentTable();
    expect(within(table).getByText("90.0%")).toBeInTheDocument();
    // Every ranked rate carries its backend denominator beside it: the
    // top-ranked Zeta row pairs 90.0% with its eligible population of 4
    // and carries rank 1 in the final column.
    const zeta = within(table)
      .getAllByRole("row")
      .find((row) => row.textContent?.includes("QM-Zeta"));
    const zetaCells = within(zeta as HTMLElement).getAllByRole("cell");
    expect(zetaCells[1].textContent).toBe("90.0%");
    expect(zetaCells[2].textContent).toBe("4");
    expect(zetaCells[3].textContent).toBe("1");
    // Unavailable stays unavailable with its backend reason, never zero.
    expect(
      within(table).getByText("Unavailable — empty-eligible-population"),
    ).toBeInTheDocument();
    expect(within(table).queryByText("0.0%")).not.toBeInTheDocument();
    expect(table.textContent).toMatch(/association, not causation|Associated/);
    expect(table.textContent).not.toMatch(
      /root cause|driver|best|worst|because/i,
    );
  });

  it("numbers ranks by display order with unavailable unranked", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByRole("table", {
      name: "Associated groups ordered by observed late-shipment rate",
    });
    const table = shipmentTable();
    expect(
      within(table).getByRole("columnheader", { name: "Rank" }),
    ).toBeInTheDocument();
    // Display order Zeta, Alpha, Beta, Gamma, Void: ranks 1-4 then unranked.
    const ranks = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("cell")[3].textContent);
    expect(ranks).toEqual(["1", "2", "3", "4", "—"]);
    // Rank is display order only: no winner language anywhere in the table.
    expect(table.textContent).not.toMatch(/winner|medal|best|worst|grade/i);
  });

  it("keeps the association caveat in the normal reading flow", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByText("O-11");
    expect(
      screen.getByText(/observed association only — never/i),
    ).toBeInTheDocument();
  });

  it("orders commercial loss rates with unavailable last", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByRole("table", {
      name: "Associated groups ordered by observed loss-making-order rate",
    });
    expect(rowKeys(commercialTable())).toEqual(["D-One", "D-Two", "D-Gone"]);
    expect(within(commercialTable()).getByText("60.0%")).toBeInTheDocument();
    const commercial = screen.getByLabelText("Rank by", {
      selector: "#diagnostics-commercial-dimension",
    }) as HTMLSelectElement;
    expect(
      Array.from(commercial.options).map((option) => option.value),
    ).toEqual([
      "department_name",
      "category_name",
      "product_name",
      "destination_market",
      "destination_region",
      "customer_segment",
    ]);
  });

  it("discloses the category population distinction for category rankings", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByRole("table", {
      name: "Associated groups ordered by observed late-shipment rate",
    });
    expect(
      screen.queryByText(/cannot be compared directly/i),
    ).not.toBeInTheDocument();
    fireEvent.change(
      screen.getByLabelText("Rank by", {
        selector: "#diagnostics-shipment-dimension",
      }),
      { target: { value: "category_name" } },
    );
    expect(
      await screen.findByText(/single-merchandise orders/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/cannot be compared directly/i),
    ).toBeInTheDocument();
    fireEvent.change(
      screen.getByLabelText("Rank by", {
        selector: "#diagnostics-commercial-dimension",
      }),
      { target: { value: "category_name" } },
    );
    expect(
      await screen.findByText(/whole-order recorded profit/i),
    ).toBeInTheDocument();
  });

  it("renders an unavailable zero-eligible shipment state, never 0%", async () => {
    route = (url: string) => {
      if (url.includes("/kpis/delivery")) {
        return ok({
          data: {
            groups: [],
            eligibleOrders: 0,
            exclusions: "2 shipping-cancelled orders excluded",
          },
          meta: {},
          error: null,
        });
      }
      return defaultRoute(url);
    };
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    expect(
      await screen.findByText(/no shipment-eligible orders/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    // The drilldown follows a different population and stays usable.
    expect(await screen.findByText("O-11")).toBeInTheDocument();
  });
});

describe("Phase-15B sanitized order drilldown", () => {
  it("shows sanitized records with matching total and no personal fields", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByText("O-11");
    expect(screen.getByText(/3 matching orders/)).toBeInTheDocument();
    expect(screen.getByText("O-9")).toBeInTheDocument();
    expect(screen.getByText("SUSPECTED_FRAUD")).toBeInTheDocument();
    // O-7 sits on the second page: the first page is bounded, and the
    // producer total still counts it.
    expect(screen.queryByText("O-7")).not.toBeInTheDocument();
    const body = document.body.textContent ?? "";
    for (const forbidden of [
      "customer_id",
      "postal",
      "first_name",
      "last_name",
      "email",
      "password",
      "street",
    ]) {
      expect(body).not.toContain(forbidden);
    }
  });

  it("loads more records with the opaque cursor and restarts on filter change", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByText("O-11");
    fireEvent.click(
      screen.getByRole("button", { name: "Load more matching orders" }),
    );
    await screen.findByText("O-7");
    expect(screen.getByText("-50.00")).toBeInTheDocument();
    expect(
      fetchCalls().some(
        (url) => url.includes("/orders") && url.includes("cursor="),
      ),
    ).toBe(true);
    // Changing any filter discards the accumulated pages and restarts.
    fireEvent.change(screen.getByLabelText("Market"), {
      target: { value: "M1" },
    });
    await waitFor(() => {
      expect(screen.queryByText("O-7")).not.toBeInTheDocument();
    });
    expect(screen.getByText("O-11")).toBeInTheDocument();
  });

  it("renders cancelled null lateness honestly and keeps fraud distinct", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByText("O-9");
    const rows = within(
      screen.getByRole("table", { name: "Filtered sanitized order records" }),
    ).getAllByRole("row");
    const cancelled = rows.find(
      (row) => row.textContent?.includes("O-9") ?? false,
    );
    expect(cancelled).toBeDefined();
    fireEvent.click(within(cancelled as HTMLElement).getByText("Details"));
    expect(
      within(cancelled as HTMLElement).getByText(
        "No value (shipping cancelled or unclassifiable)",
      ),
    ).toBeInTheDocument();
    expect(
      within(cancelled as HTMLElement).queryByText("false"),
    ).not.toBeInTheDocument();
  });

  it("renders a normal empty state with a reset path", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByText("O-11");
    fireEvent.change(screen.getByLabelText("Category"), {
      target: { value: "Beta" },
    });
    expect(
      await screen.findByText("No orders match the current filters"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Reset filters to see records" }),
    );
    await screen.findByText("O-11");
  });

  it("discloses the cross-grain limitation only under merchandise filters", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByText("O-11");
    expect(
      screen.queryByText(/governed grain behavior, not a data error/i),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Category"), {
      target: { value: "Alpha" },
    });
    expect(
      await screen.findByText(/governed grain behavior, not a data error/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not guaranteed to equal sums/i),
    ).toBeInTheDocument();
  });

  it("ignores a stale filtered response that resolves after the current one", async () => {
    let resolveStale!: (outcome: RouteOutcome) => void;
    const staleGate = new Promise<RouteOutcome>((resolve) => {
      resolveStale = resolve;
    });
    route = (url: string) => {
      if (url.includes("/orders") && url.includes("market=M1")) {
        return staleGate;
      }
      return defaultRoute(url);
    };
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByText("O-11");
    fireEvent.change(screen.getByLabelText("Market"), {
      target: { value: "M1" },
    });
    fireEvent.change(screen.getByLabelText("Market"), {
      target: { value: "M2" },
    });
    await waitFor(() => {
      expect(
        fetchCalls().some(
          (url) => url.includes("/orders") && url.includes("market=M2"),
        ),
      ).toBe(true);
    });
    // The stale M1 response resolves after M2 landed: it must not render.
    resolveStale(
      ok({
        data: {
          rows: [orderRow({ order_id: "O-STALE" })],
          page: { nextCursor: null, total: 1 },
        },
        meta: {},
        error: null,
      }),
    );
    await waitFor(() => {
      expect(screen.getByText("O-11")).toBeInTheDocument();
    });
    expect(screen.queryByText("O-STALE")).not.toBeInTheDocument();
  });

  it("preserves every governed drilldown column without adding PII", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByText("O-11");
    const table = screen.getByRole("table", {
      name: "Filtered sanitized order records",
    });
    for (const header of [
      "Order ID",
      "Order date",
      "Status",
      "Shipping mode",
      "Market / Region",
      "Shipment outcome",
      "Scheduled days",
      "Actual days",
      "Recorded net order value",
      "Recorded profit",
    ]) {
      expect(
        within(table).getByRole("columnheader", { name: header }),
      ).toBeInTheDocument();
    }
  });

  it("reports no axe violations on the loaded diagnostics view", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    goToDiagnostics();
    await screen.findByText("O-11");
    await screen.findByRole("table", {
      name: "Associated groups ordered by observed late-shipment rate",
    });
    const section = screen
      .getByRole("heading", { name: "Diagnostics" })
      .closest("section");
    expect(section).not.toBeNull();
    expect(await axe(section as HTMLElement)).toHaveNoViolations();
  });
});
