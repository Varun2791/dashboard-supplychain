import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AppShell from "./components/AppShell";
import { SessionProvider } from "./lib/session-context";
import { useSession } from "./lib/session";
import type { SessionSnapshot } from "./lib/session";

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

function kpi(id: string, label: string, value: number | string | null) {
  return {
    id,
    label,
    value,
    status: value === null ? "unavailable" : "ok",
    numerator: value,
    denominator: null,
    population: `Population for ${id}.`,
    exclusions: `Exclusions for ${id}.`,
    reason: value === null ? "empty-eligible-population" : null,
    missingDataCount: 0,
  };
}

/** Small arbitrary values — never DataCo reference controls. */
function overviewBody() {
  return {
    data: {
      kpis: [
        kpi("kpi.value.net", "Recorded net order value", "1234.56"),
        kpi("kpi.profit.recorded", "Recorded profit", "-45.67"),
        kpi("kpi.margin.profit", "Profit margin", null),
        kpi("kpi.ship.late_rate", "Late-shipment rate", "0.5"),
        kpi("kpi.ship.on_schedule_rate", "On-schedule shipment rate", "0.5"),
        kpi("kpi.orders.count", "Orders", 10),
        kpi(
          "kpi.orders.shipment_eligible_count",
          "Shipment-eligible orders",
          8,
        ),
        kpi("kpi.units.total", "Units", 25),
        kpi("kpi.ship.late_count", "Late orders", 4),
        kpi("kpi.ship.early_count", "Early orders", 2),
        kpi("kpi.ship.exact_count", "Exactly on-schedule orders", 2),
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

function deliveryBody(by: string | null) {
  return {
    data: {
      groups: [],
      eligibleOrders: 8,
      exclusions: by === null ? "0 shipping-cancelled orders excluded" : "",
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
      weightedRates: { profitMargin: null, discountRate: null },
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

function ordersBody() {
  return {
    data: { rows: [], page: { nextCursor: null, total: 0 } },
    meta: {},
    error: null,
  };
}

function dqBody() {
  return {
    data: {
      summary: {
        rulesEvaluated: 3,
        rulesTriggered: 1,
        errors: 0,
        warnings: 1,
        infos: 0,
        blockingIssues: 0,
      },
      issues: [],
    },
    meta: {},
    error: null,
  };
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: unknown) => {
      const url = String(input);
      let body: unknown;
      if (url.includes("/filter-options")) {
        body = filterOptionsBody();
      } else if (url.includes("/kpis/overview")) {
        body = overviewBody();
      } else if (url.includes("/kpis/delivery")) {
        const match = url.match(/by=([a-z_]+)/);
        body = deliveryBody(match === null ? null : match[1]);
      } else if (url.includes("/kpis/commercial")) {
        body = commercialBody();
      } else if (url.includes("/sessions/") && url.includes("/orders")) {
        body = ordersBody();
      } else if (url.includes("/data-quality")) {
        body = dqBody();
      } else if (url.includes("/profile")) {
        body = {
          data: {
            rows: 12,
            columns: 4,
            grain: "order item",
            missingness: [],
            cardinality: [],
            duplicates: { exact: 0, keyDupes: 0 },
            invarianceConflicts: {
              ordersChecked: 10,
              conflictingOrders: 0,
              byField: [],
            },
            productInvarianceConflicts: {
              keysChecked: 5,
              conflictingKeys: 0,
              byField: [],
            },
            customerInvarianceConflicts: {
              keysChecked: 6,
              conflictingKeys: 0,
              byField: [],
            },
          },
          meta: {},
          error: null,
        };
      } else if (url.includes("/schema")) {
        body = {
          data: { sourceColumns: [], mapping: [], missingCritical: [] },
          meta: {},
          error: null,
        };
      } else if (url.includes("/cleaning-report")) {
        body = { data: { steps: [] }, meta: {}, error: null };
      } else {
        body = { data: null, meta: {}, error: null };
      }
      return new Response(JSON.stringify(body), {
        status: 200,
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

async function openOverview(): Promise<void> {
  goTo("Overview");
  await screen.findAllByText("Recorded net order value");
}

describe("Phase-15B shared analytics filters", () => {
  it("defaults every filter to All/inactive with reset disabled", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await openOverview();
    expect(
      screen.getByRole("button", { name: "Reset filters" }),
    ).toBeDisabled();
    for (const label of [
      "Market",
      "Region",
      "Category",
      "Shipping mode",
      "Order status",
      "Shipment outcome",
    ]) {
      expect(screen.getByLabelText(label)).toHaveValue("");
    }
    expect(screen.getByLabelText("From (order date)")).toHaveValue("");
    expect(screen.getByLabelText("To (order date)")).toHaveValue("");
  });

  it("loads open domains from the producer with date bounds", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await openOverview();
    const market = screen.getByLabelText("Market") as HTMLSelectElement;
    expect(market).toBeEnabled();
    expect(Array.from(market.options).map((option) => option.value)).toEqual([
      "",
      "M1",
      "M2",
    ]);
    expect(
      screen.getByText("Available order dates: 2021-03-10 to 2021-03-20."),
    ).toBeInTheDocument();
  });

  it("exposes only the governed closed vocabularies, never UNKNOWN", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await openOverview();
    const shipping = Array.from(
      (screen.getByLabelText("Shipping mode") as HTMLSelectElement).options,
    ).map((option) => option.value);
    expect(shipping).toEqual([
      "",
      "STANDARD_CLASS",
      "SECOND_CLASS",
      "FIRST_CLASS",
      "SAME_DAY",
    ]);
    const status = Array.from(
      (screen.getByLabelText("Order status") as HTMLSelectElement).options,
    ).map((option) => option.value);
    expect(status).toEqual([
      "",
      "COMPLETE",
      "CLOSED",
      "PENDING",
      "PROCESSING",
      "ON_HOLD",
      "CANCELED",
      "PAYMENT_REVIEW",
      "SUSPECTED_FRAUD",
    ]);
    const outcome = Array.from(
      (screen.getByLabelText("Shipment outcome") as HTMLSelectElement).options,
    ).map((option) => option.value);
    expect(outcome).toEqual([
      "",
      "LATE",
      "EARLY",
      "ON_SCHEDULE",
      "SHIPPING_CANCELED",
    ]);
    for (const select of [shipping, status, outcome]) {
      expect(select).not.toContain("UNKNOWN_FLAGGED");
    }
    expect(document.body.textContent ?? "").not.toContain("UNKNOWN_FLAGGED");
  });

  it("keeps category domains session-wide when a market is selected", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await openOverview();
    fireEvent.change(screen.getByLabelText("Market"), {
      target: { value: "M1" },
    });
    const category = screen.getByLabelText("Category") as HTMLSelectElement;
    expect(Array.from(category.options).map((option) => option.value)).toEqual([
      "",
      "Alpha",
      "Beta",
    ]);
  });

  it("carries the same governed values to every analytics surface", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await openOverview();
    fireEvent.change(screen.getByLabelText("Market"), {
      target: { value: "M2" },
    });
    fireEvent.change(screen.getByLabelText("Category"), {
      target: { value: "Beta" },
    });
    fireEvent.change(screen.getByLabelText("Shipping mode"), {
      target: { value: "SAME_DAY" },
    });
    await waitFor(() => {
      expect(
        fetchCalls().some(
          (url) =>
            url.includes("/kpis/overview") &&
            url.includes("market=M2") &&
            url.includes("category=Beta") &&
            url.includes("shipping_mode=SAME_DAY"),
        ),
      ).toBe(true);
    });
    goTo("Delivery");
    await waitFor(() => {
      expect(
        fetchCalls().some(
          (url) =>
            url.includes("/kpis/delivery") &&
            url.includes("market=M2") &&
            url.includes("category=Beta") &&
            url.includes("shipping_mode=SAME_DAY"),
        ),
      ).toBe(true);
    });
    goTo("Commercial");
    await waitFor(() => {
      expect(
        fetchCalls().some(
          (url) =>
            url.includes("/kpis/commercial") &&
            url.includes("market=M2") &&
            url.includes("category=Beta") &&
            url.includes("shipping_mode=SAME_DAY"),
        ),
      ).toBe(true);
    });
    goTo("Diagnostics");
    await waitFor(() => {
      expect(
        fetchCalls().some(
          (url) =>
            url.includes("/orders") &&
            url.includes("market=M2") &&
            url.includes("category=Beta") &&
            url.includes("shipping_mode=SAME_DAY"),
        ),
      ).toBe(true);
    });
    // Inactive filters are omitted; backend-only dims are never sent.
    const orderCalls = fetchCalls().filter((url) => url.includes("/orders"));
    expect(orderCalls.length).toBeGreaterThan(0);
    for (const url of orderCalls) {
      expect(url).not.toContain("department");
      expect(url).not.toContain("customer_segment");
      expect(url).not.toContain("All");
    }
  });

  it("persists filters across analytics views without resetting", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await openOverview();
    fireEvent.change(screen.getByLabelText("Region"), {
      target: { value: "R2" },
    });
    expect(screen.getByRole("button", { name: "Reset filters" })).toBeEnabled();
    for (const view of ["Delivery", "Commercial", "Diagnostics"]) {
      goTo(view);
      await waitFor(() => {
        expect(screen.getByLabelText("Region")).toHaveValue("R2");
      });
    }
    goTo("Overview");
    await waitFor(() => {
      expect(screen.getByLabelText("Region")).toHaveValue("R2");
    });
  });

  it("resets every filter to All without touching the session", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await openOverview();
    fireEvent.change(screen.getByLabelText("Market"), {
      target: { value: "M1" },
    });
    // Let the filtered results land first: resetting back to the
    // initially-cached unfiltered combination needs no refetch, so the
    // reset-after-filtered flow is what proves the unfiltered request.
    await waitFor(() => {
      expect(
        fetchCalls().some(
          (url) => url.includes("/kpis/overview") && url.includes("market=M1"),
        ),
      ).toBe(true);
    });
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getByLabelText("Market")).toHaveValue("");
    expect(
      screen.getByRole("button", { name: "Reset filters" }),
    ).toBeDisabled();
    await waitFor(() => {
      const overviews = fetchCalls().filter((url) =>
        url.includes("/kpis/overview"),
      );
      expect(overviews.length).toBeGreaterThan(2);
      const latest = overviews[overviews.length - 1];
      expect(latest).not.toContain("market=");
    });
    // The session itself is untouched: headline content still renders.
    expect(
      screen.getAllByText("Recorded net order value").length,
    ).toBeGreaterThan(0);
  });

  it("leaves Data Quality unaffected by analytics filters", async () => {
    renderSeeded(snapshotFor(SESSION_A, "READY"));
    await openOverview();
    fireEvent.change(screen.getByLabelText("Market"), {
      target: { value: "M1" },
    });
    goTo("Data Quality");
    await waitFor(() => {
      expect(fetchCalls().some((url) => url.includes("/data-quality"))).toBe(
        true,
      );
    });
    expect(screen.queryByLabelText("Market")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reset filters" }),
    ).not.toBeInTheDocument();
    for (const url of fetchCalls().filter((call) =>
      call.includes("/data-quality"),
    )) {
      expect(url).not.toContain("?");
    }
    goTo("Overview");
    await waitFor(() => {
      expect(screen.getByLabelText("Market")).toHaveValue("M1");
    });
  });

  it("clears filters when the session is replaced", async () => {
    const { rerender } = renderSeeded(snapshotFor(SESSION_A, "READY"));
    await openOverview();
    fireEvent.change(screen.getByLabelText("Market"), {
      target: { value: "M1" },
    });
    expect(screen.getByLabelText("Market")).toHaveValue("M1");
    rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(SESSION_B, "READY")} />
      </SessionProvider>,
    );
    await waitFor(() => {
      expect(screen.getByLabelText("Market")).toHaveValue("");
    });
    expect(
      screen.getByRole("button", { name: "Reset filters" }),
    ).toBeDisabled();
  });

  it("clears filters when the session is reset", async () => {
    const { rerender } = renderSeeded(snapshotFor(SESSION_A, "READY"));
    await openOverview();
    fireEvent.change(screen.getByLabelText("Market"), {
      target: { value: "M1" },
    });
    rerender(
      <SessionProvider>
        <SeedHost snapshot={snapshotFor(null, null)} />
      </SessionProvider>,
    );
    expect(screen.getByText("No dataset loaded")).toBeInTheDocument();
    goTo("Overview");
    expect(screen.getByText("No dataset loaded")).toBeInTheDocument();
  });
});
