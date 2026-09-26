import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ApiRequestError,
  fetchKpisCommercial,
  fetchKpisDelivery,
  fetchKpisOverview,
} from "@/lib/api";
import type {
  KpiCommercialData,
  KpiDeliveryData,
  KpiOverviewData,
  KpiResult,
} from "@/lib/api";
import {
  chartMargins,
  chartPalette,
  chartTickFontSize,
} from "@/lib/chart-theme";
import {
  CARD_MEANINGS,
  OVERVIEW_CARD_IDS,
  formatKpiValue,
} from "@/lib/kpi-format";
import { KpiDefinition } from "@/components/patterns";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useSession } from "@/lib/session";
import { VIEWS } from "@/lib/view-registry";

interface OverviewReports {
  overview: KpiOverviewData;
  delivery: KpiDeliveryData;
  trend: KpiCommercialData;
  region: KpiCommercialData;
}

interface Failure {
  message: string;
  code: string | null;
  gone: boolean;
}

function isPending(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 409;
}

function toFailure(error: unknown): Failure {
  if (error instanceof ApiRequestError) {
    return {
      message: error.message,
      code: error.code,
      gone: error.status === 404 || error.status === 410,
    };
  }
  return {
    message: "Something went wrong. Please try again.",
    code: null,
    gone: false,
  };
}

/** Presentational parse for chart axes only (unavailable → null gap). */
function toPlottable(value: number | string | null): number | null {
  if (value === null) {
    return null;
  }
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function findKpi(kpis: KpiResult[], id: string): KpiResult | null {
  return kpis.find((kpi) => kpi.id === id) ?? null;
}

function KpiCard({ kpi }: { kpi: KpiResult }) {
  const unavailable = kpi.status !== "ok" || kpi.value === null;
  const value: number | string | null = kpi.value;
  return (
    <div className="flex flex-col gap-1 rounded-lg border p-4">
      <p className="text-sm font-medium">{kpi.label}</p>
      {unavailable || value === null ? (
        <p className="text-sm text-muted-foreground" role="status">
          Unavailable
          {kpi.reason !== null && kpi.reason !== "" ? ` — ${kpi.reason}` : ""}
          {kpi.missingDataCount > 0
            ? ` (${kpi.missingDataCount} rows excluded for missing fields)`
            : ""}
        </p>
      ) : (
        <p className="text-2xl font-semibold tracking-tight">
          {formatKpiValue(kpi.id, value)}
        </p>
      )}
      <KpiDefinition
        term={kpi.label}
        meaning={CARD_MEANINGS[kpi.id] ?? "Governed headline KPI."}
        population={kpi.population}
        exclusions={kpi.exclusions}
      />
    </div>
  );
}

function ScrollTable({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table aria-label={label} className="w-full text-sm">
        {children}
      </table>
    </div>
  );
}

function TrendChart({ trend }: { trend: KpiCommercialData }) {
  const rows = trend.groups.map((group) => {
    const net = findKpi(group.kpis, "kpi.value.net");
    const profit = findKpi(group.kpis, "kpi.profit.recorded");
    return {
      month: group.key,
      net: net !== null && net.status === "ok" ? toPlottable(net.value) : null,
      profit:
        profit !== null && profit.status === "ok"
          ? toPlottable(profit.value)
          : null,
    };
  });
  const months = rows.length;
  const withData = rows.filter(
    (row) => row.net !== null || row.profit !== null,
  ).length;
  return (
    <section aria-labelledby="overview-trend-heading">
      <h3 id="overview-trend-heading" className="text-base font-semibold">
        Recorded net order value and profit by order month
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Monthly buckets on order date; values come from the commercial endpoint
        under identical formulas. {withData} of {months} months have plottable
        values; unavailable months leave gaps, never zeros.
      </p>
      {withData === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground" role="status">
          No monthly values are available.
        </p>
      ) : (
        <figure className="mt-2">
          <div
            role="img"
            aria-label={`Monthly recorded net order value and profit across ${months} months`}
          >
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={rows} margin={{ ...chartMargins, left: 48 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="month"
                  tick={{ fontSize: chartTickFontSize }}
                  interval="preserveStartEnd"
                />
                <YAxis tick={{ fontSize: chartTickFontSize }} width={56} />
                <Tooltip />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="net"
                  name="Recorded net order value"
                  stroke={chartPalette[0]}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="profit"
                  name="Recorded profit"
                  stroke={chartPalette[1]}
                  strokeDasharray="5 3"
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <figcaption className="mt-1 text-sm text-muted-foreground">
            Monthly recorded net order value (solid) and recorded profit
            (dashed) in neutral units. Amounts carry no currency.
          </figcaption>
        </figure>
      )}
      <details className="mt-2 rounded-lg border px-3 py-2 text-sm">
        <summary className="cursor-pointer font-medium">
          Monthly values as a table
        </summary>
        <div className="mt-2">
          <ScrollTable label="Monthly net order value and profit">
            <thead>
              <tr className="border-b text-left">
                <th scope="col" className="px-3 py-2 font-medium">
                  Order month
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Recorded net order value
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Recorded profit
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.month} className="border-b last:border-0">
                  <td className="px-3 py-2">{row.month}</td>
                  <td className="px-3 py-2">
                    {row.net === null
                      ? "Unavailable"
                      : row.net.toLocaleString("en-US", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}
                  </td>
                  <td className="px-3 py-2">
                    {row.profit === null
                      ? "Unavailable"
                      : row.profit.toLocaleString("en-US", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}
                  </td>
                </tr>
              ))}
            </tbody>
          </ScrollTable>
        </div>
      </details>
    </section>
  );
}

function OutcomeDistribution({
  overview,
  delivery,
}: {
  overview: KpiOverviewData;
  delivery: KpiDeliveryData;
}) {
  const late = findKpi(overview.kpis, "kpi.ship.late_count");
  const early = findKpi(overview.kpis, "kpi.ship.early_count");
  const exact = findKpi(overview.kpis, "kpi.ship.exact_count");
  const rows = [
    { outcome: "Late", count: toPlottable(late?.value ?? null) },
    { outcome: "Early", count: toPlottable(early?.value ?? null) },
    {
      outcome: "Exactly on schedule",
      count: toPlottable(exact?.value ?? null),
    },
  ];
  const withData = rows.filter((row) => row.count !== null).length;
  return (
    <section aria-labelledby="overview-outcome-heading">
      <h3 id="overview-outcome-heading" className="text-base font-semibold">
        Shipment outcome distribution
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        {delivery.eligibleOrders.toLocaleString("en-US")} shipment-eligible
        orders. {delivery.exclusions}
      </p>
      {withData === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground" role="status">
          No outcome counts are available.
        </p>
      ) : (
        <figure className="mt-2">
          <div
            role="img"
            aria-label="Late, early, and exactly on-schedule order counts"
          >
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={rows} margin={{ ...chartMargins, left: 48 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="outcome"
                  tick={{ fontSize: chartTickFontSize }}
                />
                <YAxis
                  tick={{ fontSize: chartTickFontSize }}
                  width={56}
                  allowDecimals={false}
                />
                <Tooltip />
                <Bar
                  dataKey="count"
                  name="Orders (count)"
                  fill={chartPalette[2]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <figcaption className="mt-1 text-sm text-muted-foreground">
            Late, early, and exactly on-schedule orders within the eligible
            population. Shipping-cancelled orders are excluded, never counted as
            non-late.
          </figcaption>
        </figure>
      )}
    </section>
  );
}

function RegionPerformance({ region }: { region: KpiCommercialData }) {
  const rows = region.groups.map((group) => {
    const net = findKpi(group.kpis, "kpi.value.net");
    return {
      region: group.key,
      net:
        net !== null && net.status === "ok"
          ? formatKpiValue(net.id, net.value ?? "")
          : "Unavailable",
    };
  });
  return (
    <section aria-labelledby="overview-region-heading">
      <h3 id="overview-region-heading" className="text-base font-semibold">
        Recorded net order value by destination region
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Regional split under identical commercial formulas; coarse destination
        geography only.
      </p>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground" role="status">
          No regional values are available.
        </p>
      ) : (
        <div className="mt-2">
          <ScrollTable label="Recorded net order value by destination region">
            <thead>
              <tr className="border-b text-left">
                <th scope="col" className="px-3 py-2 font-medium">
                  Destination region
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Recorded net order value
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.region} className="border-b last:border-0">
                  <td className="px-3 py-2">{row.region}</td>
                  <td className="px-3 py-2">{row.net}</td>
                </tr>
              ))}
            </tbody>
          </ScrollTable>
        </div>
      )}
    </section>
  );
}

/**
 * Phase-12 Executive Overview: headline KPI cards, monthly commercial
 * trend, shipment outcome distribution, and regional performance for the
 * active session. Renders backend-computed values only; it calculates no
 * KPI, rate, margin, or eligibility.
 */
export default function OverviewView() {
  const { session, sessionState } = useSession();
  // Reports are immutable per session: an id-keyed cache plus the render
  // guard below keeps reset (null) and FAILED from showing stale KPIs.
  const [cache, setCache] = useState<{
    sessionId: string;
    reports: OverviewReports | null;
    failure: Failure | null;
    failedAtState: string | null;
  } | null>(null);

  const sessionId = session?.sessionId ?? null;
  const terminal = sessionState === "FAILED";
  const visible =
    cache !== null && cache.sessionId === sessionId && !terminal ? cache : null;
  const reports = visible?.reports ?? null;
  const failure = visible?.failure ?? null;

  // KPI endpoints require READY; anything earlier 409s and retries when the
  // session state advances. Stale completions are ignored so session A can
  // never populate session B.
  useEffect(() => {
    if (sessionId === null || terminal) {
      return;
    }
    if (cache?.sessionId === sessionId && cache.reports !== null) {
      return;
    }
    if (
      cache?.sessionId === sessionId &&
      cache.failure !== null &&
      cache.failedAtState === sessionState
    ) {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const [overview, delivery, trend, region] = await Promise.all([
          fetchKpisOverview(sessionId),
          fetchKpisDelivery(sessionId, null),
          fetchKpisCommercial(sessionId, "order_month"),
          fetchKpisCommercial(sessionId, "destination_region"),
        ]);
        if (cancelled) {
          return;
        }
        setCache({
          sessionId,
          reports: { overview, delivery, trend, region },
          failure: null,
          failedAtState: null,
        });
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (isPending(error)) {
          // KPI analysis has not completed yet; the next session-state
          // advance retries automatically.
          return;
        }
        setCache({
          sessionId,
          reports: null,
          failure: toFailure(error),
          failedAtState: sessionState,
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, terminal, sessionState, cache]);

  const meta = VIEWS.find((entry) => entry.id === "overview");

  if (session === null) {
    return (
      <section aria-labelledby="overview-heading">
        <h2
          id="overview-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Overview
        </h2>
        {meta !== undefined ? (
          <p className="mt-1 text-sm text-muted-foreground">{meta.question}</p>
        ) : null}
        <div className="mt-4">
          <EmptyState
            title="No dataset loaded"
            body="Upload a CSV on the Upload view first. Headline commercial and shipment results appear here once KPI analysis completes."
          />
        </div>
      </section>
    );
  }

  if (terminal) {
    return (
      <section aria-labelledby="overview-heading">
        <h2
          id="overview-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Overview
        </h2>
        <div className="mt-4">
          <ErrorState
            title="This session ended in FAILED"
            message="The session failed before KPI analysis could complete, so there are no headline results to show. This is a terminal session state, not a gated stage."
            guidance="Open the Upload view for the failing stage, code, and next steps — or remove the session and upload a fixed file."
          />
        </div>
      </section>
    );
  }

  if (failure !== null) {
    return (
      <section aria-labelledby="overview-heading">
        <h2
          id="overview-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Overview
        </h2>
        <div className="mt-4">
          <ErrorState
            title="The headline results could not be loaded"
            message={failure.message}
            guidance={[
              failure.code !== null ? `Code: ${failure.code}.` : null,
              failure.gone
                ? "This session is gone from the server. Upload the file again to start a new session."
                : "No KPI data is shown; nothing stale is displayed.",
            ]
              .filter((part) => part !== null)
              .join(" ")}
          />
        </div>
      </section>
    );
  }

  if (reports === null) {
    const gated =
      sessionState === "CANONICALIZING" || sessionState === "ANALYZING";
    return (
      <section aria-labelledby="overview-heading">
        <h2
          id="overview-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Overview
        </h2>
        <div className="mt-4 flex flex-col gap-2">
          <LoadingState label="Loading the headline results…" />
          <p className="text-sm text-muted-foreground">
            Session {session.sessionId.slice(0, 8)} is{" "}
            {sessionState ?? "starting"}. Headline results appear automatically
            once KPI analysis completes.
            {gated
              ? " If a data-quality gate holds the session, analytics stay unavailable until the input is fixed or replaced — this is not a terminal failure."
              : ""}
          </p>
        </div>
      </section>
    );
  }

  const cards = OVERVIEW_CARD_IDS.map((id) =>
    findKpi(reports.overview.kpis, id),
  ).filter((kpi): kpi is KpiResult => kpi !== null);

  return (
    <section
      aria-labelledby="overview-heading"
      className="flex w-full flex-col gap-6"
    >
      <div>
        <h2
          id="overview-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Overview
        </h2>
        {meta !== undefined ? (
          <p className="mt-1 text-sm text-muted-foreground">{meta.question}</p>
        ) : null}
        <p className="mt-1 text-sm text-muted-foreground" role="status">
          Session {session.sessionId.slice(0, 8)} · {sessionState ?? "starting"}{" "}
          · {reports.overview.totals.items.toLocaleString("en-US")} order-item
          lines · {reports.overview.totals.orders.toLocaleString("en-US")}{" "}
          orders · {reports.delivery.eligibleOrders.toLocaleString("en-US")}{" "}
          shipment-eligible
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Commercial scope: {reports.region.statusScope}. Shipment scope:{" "}
          {reports.delivery.exclusions}
        </p>
      </div>
      <section aria-labelledby="overview-cards-heading">
        <h3 id="overview-cards-heading" className="text-base font-semibold">
          Headline results
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Amounts are neutral units; currency is unspecified. Rates show one
          decimal.
        </p>
        <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {cards.map((kpi) => (
            <KpiCard key={kpi.id} kpi={kpi} />
          ))}
        </div>
      </section>
      <TrendChart trend={reports.trend} />
      <OutcomeDistribution
        overview={reports.overview}
        delivery={reports.delivery}
      />
      <RegionPerformance region={reports.region} />
      <p className="text-xs text-muted-foreground">
        Findings describe the uploaded file — a synthetic demo dataset, not a
        real company. Shipment adherence describes schedule outcomes, not
        customer delivery performance.
      </p>
    </section>
  );
}
