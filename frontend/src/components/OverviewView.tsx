import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
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
  chartAxisLine,
  chartBarCursor,
  chartBarProps,
  chartGridProps,
  chartIsAnimationActive,
  chartLegendProps,
  chartLineCursor,
  chartMargins,
  chartNumericTick,
  chartSeries,
  chartTick,
  chartTooltipProps,
  chartXAxisProps,
} from "@/lib/chart-theme";
import { OVERVIEW_CARD_IDS, formatKpiValue } from "@/lib/kpi-format";
import { KpiStrip, KpiStripDefinitions } from "@/components/KpiStrip";
import { AnalyticalTable } from "@/components/AnalyticalTable";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import FilterBar from "@/components/FilterBar";
import { useAnalyticsFilters } from "@/lib/analytics-filters";
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
                <CartesianGrid {...chartGridProps} />
                <XAxis
                  dataKey="month"
                  tick={chartTick}
                  tickLine={false}
                  axisLine={chartAxisLine}
                  {...chartXAxisProps}
                />
                <YAxis
                  tick={chartNumericTick}
                  tickLine={false}
                  axisLine={chartAxisLine}
                  width={56}
                />
                <Tooltip {...chartTooltipProps} cursor={chartLineCursor} />
                <Legend {...chartLegendProps} />
                <ReferenceLine y={0} stroke="var(--border)" />
                <Line
                  type="monotone"
                  dataKey="net"
                  name="Recorded net order value"
                  stroke={chartSeries.primary}
                  dot={false}
                  isAnimationActive={chartIsAnimationActive}
                />
                <Line
                  type="monotone"
                  dataKey="profit"
                  name="Recorded profit"
                  stroke={chartSeries.secondary}
                  strokeDasharray="5 3"
                  dot={false}
                  isAnimationActive={chartIsAnimationActive}
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
          <AnalyticalTable label="Monthly net order value and profit">
            <thead>
              <tr>
                <th scope="col">Order month</th>
                <th scope="col">Recorded net order value</th>
                <th scope="col">Recorded profit</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.month}>
                  <td>{row.month}</td>
                  <td>
                    {row.net === null
                      ? "Unavailable"
                      : row.net.toLocaleString("en-US", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}
                  </td>
                  <td>
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
          </AnalyticalTable>
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
                <CartesianGrid {...chartGridProps} />
                <XAxis
                  dataKey="outcome"
                  tick={chartTick}
                  tickLine={false}
                  axisLine={chartAxisLine}
                  {...chartXAxisProps}
                />
                <YAxis
                  tick={chartNumericTick}
                  tickLine={false}
                  axisLine={chartAxisLine}
                  width={56}
                  allowDecimals={false}
                />
                <Tooltip {...chartTooltipProps} cursor={chartBarCursor} />
                <Bar
                  dataKey="count"
                  name="Orders (count)"
                  fill={chartSeries.primary}
                  isAnimationActive={chartIsAnimationActive}
                  {...chartBarProps}
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
          <AnalyticalTable label="Recorded net order value by destination region">
            <thead>
              <tr>
                <th scope="col">Destination region</th>
                <th scope="col">Recorded net order value</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.region}>
                  <td>{row.region}</td>
                  <td>{row.net}</td>
                </tr>
              ))}
            </tbody>
          </AnalyticalTable>
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
  const { query, filterKey } = useAnalyticsFilters();
  // Reports are immutable per session and filter combination: an id-keyed
  // cache plus the render guard below keeps reset (null) and FAILED from
  // showing stale KPIs. Changing any shared filter refetches under the new
  // key; stale completions are ignored so an old filter state can never
  // populate the current view.
  const [cache, setCache] = useState<{
    key: string;
    reports: OverviewReports | null;
    failure: Failure | null;
    failedAtState: string | null;
  } | null>(null);

  const sessionId = session?.sessionId ?? null;
  const terminal = sessionState === "FAILED";
  const key = sessionId === null ? null : `${sessionId}|${filterKey}`;
  const visible =
    cache !== null && key !== null && cache.key === key && !terminal
      ? cache
      : null;
  const reports = visible?.reports ?? null;
  const failure = visible?.failure ?? null;

  // KPI endpoints require READY; anything earlier 409s and retries when the
  // session state advances. Stale completions are ignored so session A can
  // never populate session B.
  useEffect(() => {
    if (sessionId === null || terminal || key === null) {
      return;
    }
    if (cache?.key === key && cache.reports !== null) {
      return;
    }
    if (
      cache?.key === key &&
      cache.failure !== null &&
      cache.failedAtState === sessionState
    ) {
      return;
    }
    let cancelled = false;
    const requestKey = key;
    const requestQuery = query;
    void (async () => {
      try {
        const [overview, delivery, trend, region] = await Promise.all([
          fetchKpisOverview(sessionId, requestQuery),
          fetchKpisDelivery(sessionId, null, requestQuery),
          fetchKpisCommercial(sessionId, "order_month", requestQuery),
          fetchKpisCommercial(sessionId, "destination_region", requestQuery),
        ]);
        if (cancelled) {
          return;
        }
        setCache({
          key: requestKey,
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
          key: requestKey,
          reports: null,
          failure: toFailure(error),
          failedAtState: sessionState,
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, terminal, sessionState, cache, key, query]);

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
        <div className="mt-4 flex flex-col gap-4">
          <FilterBar idPrefix="overview" />
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
        <div className="mt-4 flex flex-col gap-4">
          <FilterBar idPrefix="overview" />
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
      <FilterBar idPrefix="overview" />
      <section aria-labelledby="overview-cards-heading">
        <h3 id="overview-cards-heading" className="text-base font-semibold">
          Headline results
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Amounts are neutral units; currency is unspecified. Rates show one
          decimal.
        </p>
        <div className="mt-2">
          <KpiStrip kpis={cards} label="Headline results" />
          <KpiStripDefinitions
            kpis={cards}
            summary="Definitions & populations for these headline results"
          />
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
