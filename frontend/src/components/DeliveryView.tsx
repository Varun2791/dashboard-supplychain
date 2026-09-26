import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ApiRequestError,
  fetchKpisDelivery,
  fetchKpisOverview,
} from "@/lib/api";
import type {
  KpiDeliveryData,
  KpiGroup,
  KpiOverviewData,
  KpiResult,
} from "@/lib/api";
import {
  chartMargins,
  chartPalette,
  chartTickFontSize,
} from "@/lib/chart-theme";
import { formatKpiValue } from "@/lib/kpi-format";
import { KpiCard } from "@/components/OverviewView";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useSession } from "@/lib/session";
import { VIEWS } from "@/lib/view-registry";

interface DeliveryReports {
  overview: KpiOverviewData;
  delivery: KpiDeliveryData;
  byMode: KpiDeliveryData;
  byRegion: KpiDeliveryData;
  byMarket: KpiDeliveryData;
  byCategory: KpiDeliveryData;
  byMonth: KpiDeliveryData;
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

/** Headline delivery cards (labels always come from the API). */
const HEADLINE_IDS: readonly string[] = [
  "kpi.ship.late_rate",
  "kpi.ship.on_schedule_rate",
  "kpi.ship.early_rate",
  "kpi.ship.exact_rate",
  "kpi.ship.avg_actual_days",
  "kpi.ship.avg_scheduled_days",
  "kpi.ship.variance_days",
];

/** Cancellation/fraud context (kept separate per contract; never merged). */
const CONTEXT_IDS: readonly string[] = [
  "kpi.orders.strict_cancel_rate",
  "kpi.orders.fraud_rate",
  "kpi.orders.blocked_rate",
];

function findKpi(kpis: KpiResult[], id: string): KpiResult | null {
  return kpis.find((kpi) => kpi.id === id) ?? null;
}

/** Presentational parse for chart axes only (unavailable → null gap). */
function toPlottable(value: number | string | null): number | null {
  if (value === null) {
    return null;
  }
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

/** Backend-provided eligible order count for one group (never computed). */
function groupEligible(group: KpiGroup): number | null {
  const late = findKpi(group.kpis, "kpi.ship.late_rate");
  if (late === null || late.status !== "ok") {
    return null;
  }
  return typeof late.denominator === "number" ? late.denominator : null;
}

function cellText(kpi: KpiResult | null): string {
  if (kpi === null || kpi.status !== "ok" || kpi.value === null) {
    return "Unavailable";
  }
  return formatKpiValue(kpi.id, kpi.value);
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

function GroupTable({
  dimension,
  groups,
}: {
  dimension: string;
  groups: KpiGroup[];
}) {
  return (
    <div className="mt-2">
      <ScrollTable label={`Late-shipment rate by ${dimension}`}>
        <thead>
          <tr className="border-b text-left">
            <th scope="col" className="px-3 py-2 font-medium">
              {dimension}
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Late-shipment rate
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Late (count)
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Early (count)
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Exactly on schedule (count)
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Eligible (count)
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Avg actual (days)
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Avg scheduled (days)
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Variance (days)
            </th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const eligible = groupEligible(group);
            return (
              <tr key={group.key} className="border-b last:border-0">
                <td className="px-3 py-2">{group.key}</td>
                <td className="px-3 py-2">
                  {cellText(findKpi(group.kpis, "kpi.ship.late_rate"))}
                </td>
                <td className="px-3 py-2">
                  {cellText(findKpi(group.kpis, "kpi.ship.late_count"))}
                </td>
                <td className="px-3 py-2">
                  {cellText(findKpi(group.kpis, "kpi.ship.early_count"))}
                </td>
                <td className="px-3 py-2">
                  {cellText(findKpi(group.kpis, "kpi.ship.exact_count"))}
                </td>
                <td className="px-3 py-2">
                  {eligible === null
                    ? "Unavailable"
                    : eligible.toLocaleString("en-US")}
                </td>
                <td className="px-3 py-2">
                  {cellText(findKpi(group.kpis, "kpi.ship.avg_actual_days"))}
                </td>
                <td className="px-3 py-2">
                  {cellText(findKpi(group.kpis, "kpi.ship.avg_scheduled_days"))}
                </td>
                <td className="px-3 py-2">
                  {cellText(findKpi(group.kpis, "kpi.ship.variance_days"))}
                </td>
              </tr>
            );
          })}
        </tbody>
      </ScrollTable>
    </div>
  );
}

/**
 * Late-rate bar chart for one dimension. Percentages are a display-only
 * conversion of backend fraction values; the table below carries the same
 * values textually so color is never the only encoding.
 */
function LateRateChart({
  dimension,
  groups,
}: {
  dimension: string;
  groups: KpiGroup[];
}) {
  const rows = groups.map((group) => {
    const late = findKpi(group.kpis, "kpi.ship.late_rate");
    const fraction =
      late !== null && late.status === "ok" ? toPlottable(late.value) : null;
    return {
      group: group.key,
      rate: fraction === null ? null : fraction * 100,
    };
  });
  const withData = rows.filter((row) => row.rate !== null).length;
  if (withData === 0) {
    return (
      <p className="mt-2 text-sm text-muted-foreground" role="status">
        No late-shipment rates are available by {dimension}.
      </p>
    );
  }
  return (
    <figure className="mt-2">
      <div
        role="img"
        aria-label={`Late-shipment rate in percent by ${dimension}`}
      >
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={rows} margin={{ ...chartMargins, left: 32 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="group" tick={{ fontSize: chartTickFontSize }} />
            <YAxis
              tick={{ fontSize: chartTickFontSize }}
              width={48}
              tickFormatter={(value: number) => `${value}%`}
            />
            <Tooltip formatter={(value) => `${value}%`} />
            <Legend />
            <Bar
              dataKey="rate"
              name="Late-shipment rate (%)"
              fill={chartPalette[3]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-1 text-sm text-muted-foreground">
        Late-shipment rate by {dimension}, in percent of eligible orders.
        Descriptive comparison only; values describe association, not causation.
      </figcaption>
    </figure>
  );
}

function BreakdownSection({
  id,
  title,
  intro,
  dimension,
  groups,
  chart,
}: {
  id: string;
  title: string;
  intro: string;
  dimension: string;
  groups: KpiGroup[];
  chart: boolean;
}) {
  return (
    <section aria-labelledby={id}>
      <h3 id={id} className="text-base font-semibold">
        {title}
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">{intro}</p>
      {groups.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground" role="status">
          No {dimension} groups are available.
        </p>
      ) : (
        <>
          {chart ? (
            <LateRateChart dimension={dimension} groups={groups} />
          ) : null}
          <GroupTable dimension={dimension} groups={groups} />
        </>
      )}
    </section>
  );
}

/**
 * Phase-13 Delivery analytics: headline shipment KPIs, late/on-schedule
 * outcomes by shipping mode, region, market, category, and order month,
 * plus actual/scheduled day averages and separately-kept cancellation and
 * fraud context. Renders backend-computed values only; it classifies no
 * shipment, derives no eligibility, and calculates no rate.
 */
export default function DeliveryView() {
  const { session, sessionState } = useSession();
  // Reports are immutable per session: an id-keyed cache plus the render
  // guard below keeps reset (null) and FAILED from showing stale results.
  const [cache, setCache] = useState<{
    sessionId: string;
    reports: DeliveryReports | null;
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
        const [
          overview,
          delivery,
          byMode,
          byRegion,
          byMarket,
          byCategory,
          byMonth,
        ] = await Promise.all([
          fetchKpisOverview(sessionId),
          fetchKpisDelivery(sessionId, null),
          fetchKpisDelivery(sessionId, "shipping_mode"),
          fetchKpisDelivery(sessionId, "destination_region"),
          fetchKpisDelivery(sessionId, "destination_market"),
          fetchKpisDelivery(sessionId, "category_name"),
          fetchKpisDelivery(sessionId, "order_month"),
        ]);
        if (cancelled) {
          return;
        }
        setCache({
          sessionId,
          reports: {
            overview,
            delivery,
            byMode,
            byRegion,
            byMarket,
            byCategory,
            byMonth,
          },
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

  const meta = VIEWS.find((entry) => entry.id === "delivery");

  if (session === null) {
    return (
      <section aria-labelledby="delivery-heading">
        <h2
          id="delivery-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Delivery
        </h2>
        {meta !== undefined ? (
          <p className="mt-1 text-sm text-muted-foreground">{meta.question}</p>
        ) : null}
        <div className="mt-4">
          <EmptyState
            title="No dataset loaded"
            body="Upload a CSV on the Upload view first. Shipment schedule results appear here once KPI analysis completes."
          />
        </div>
      </section>
    );
  }

  if (terminal) {
    return (
      <section aria-labelledby="delivery-heading">
        <h2
          id="delivery-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Delivery
        </h2>
        <div className="mt-4">
          <ErrorState
            title="This session ended in FAILED"
            message="The session failed before KPI analysis could complete, so there are no shipment results to show. This is a terminal session state, not a gated stage."
            guidance="Open the Upload view for the failing stage, code, and next steps — or remove the session and upload a fixed file."
          />
        </div>
      </section>
    );
  }

  if (failure !== null) {
    return (
      <section aria-labelledby="delivery-heading">
        <h2
          id="delivery-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Delivery
        </h2>
        <div className="mt-4">
          <ErrorState
            title="The shipment results could not be loaded"
            message={failure.message}
            guidance={[
              failure.code !== null ? `Code: ${failure.code}.` : null,
              failure.gone
                ? "This session is gone from the server. Upload the file again to start a new session."
                : "No shipment data is shown; nothing stale is displayed.",
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
      <section aria-labelledby="delivery-heading">
        <h2
          id="delivery-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Delivery
        </h2>
        <div className="mt-4 flex flex-col gap-2">
          <LoadingState label="Loading the shipment results…" />
          <p className="text-sm text-muted-foreground">
            Session {session.sessionId.slice(0, 8)} is{" "}
            {sessionState ?? "starting"}. Shipment results appear automatically
            once KPI analysis completes.
            {gated
              ? " If a data-quality gate holds the session, analytics stay unavailable until the input is fixed or replaced — this is not a terminal failure."
              : ""}
          </p>
        </div>
      </section>
    );
  }

  const headlines = HEADLINE_IDS.map((id) =>
    findKpi(reports.overview.kpis, id),
  ).filter((kpi): kpi is KpiResult => kpi !== null);
  const context = CONTEXT_IDS.map((id) =>
    findKpi(reports.overview.kpis, id),
  ).filter((kpi): kpi is KpiResult => kpi !== null);

  return (
    <section
      aria-labelledby="delivery-heading"
      className="flex w-full flex-col gap-6"
    >
      <div>
        <h2
          id="delivery-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Delivery
        </h2>
        {meta !== undefined ? (
          <p className="mt-1 text-sm text-muted-foreground">{meta.question}</p>
        ) : null}
        <p className="mt-1 text-sm text-muted-foreground" role="status">
          Session {session.sessionId.slice(0, 8)} · {sessionState ?? "starting"}{" "}
          · {reports.delivery.eligibleOrders.toLocaleString("en-US")}{" "}
          shipment-eligible orders
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Shipment scope: {reports.delivery.exclusions}. Shipping-cancelled
          orders carry no lateness value and never count as non-late. Per-group
          counts reconcile to the headline eligible total; order-level row
          drilldown belongs to Phase 15 diagnostics.
        </p>
      </div>
      <section aria-labelledby="delivery-headline-heading">
        <h3 id="delivery-headline-heading" className="text-base font-semibold">
          Shipment schedule adherence
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Outcomes come from authoritative shipping-day fields. Rates show one
          decimal; day averages show two.
        </p>
        <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {headlines.map((kpi) => (
            <KpiCard key={kpi.id} kpi={kpi} />
          ))}
        </div>
      </section>
      <section aria-labelledby="delivery-context-heading">
        <h3 id="delivery-context-heading" className="text-base font-semibold">
          Cancellation and suspected-fraud context
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Strict cancellations and suspected fraud stay separate from schedule
          adherence and from each other; lateness never implies fraud.
        </p>
        <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {context.map((kpi) => (
            <KpiCard key={kpi.id} kpi={kpi} />
          ))}
        </div>
      </section>
      <BreakdownSection
        id="delivery-mode-heading"
        title="Late-shipment rate by shipping mode"
        intro="Descriptive comparison across governed shipping modes. Values describe association, not causation."
        dimension="Shipping mode"
        groups={reports.byMode.groups}
        chart
      />
      <BreakdownSection
        id="delivery-region-heading"
        title="Late-shipment rate by destination region"
        intro="Descriptive comparison across coarse destination regions (order geography, not customer geography)."
        dimension="Destination region"
        groups={reports.byRegion.groups}
        chart
      />
      <BreakdownSection
        id="delivery-market-heading"
        title="Late-shipment rate by destination market"
        intro="Descriptive comparison across destination markets."
        dimension="Destination market"
        groups={reports.byMarket.groups}
        chart={false}
      />
      <BreakdownSection
        id="delivery-category-heading"
        title="Late-shipment rate by product category"
        intro="Descriptive comparison across product categories (category, not individual products)."
        dimension="Product category"
        groups={reports.byCategory.groups}
        chart={false}
      />
      <BreakdownSection
        id="delivery-month-heading"
        title="Late-shipment rate by order month"
        intro="Monthly buckets on order date. Unavailable months show as unavailable, never zero."
        dimension="Order month"
        groups={reports.byMonth.groups}
        chart={false}
      />
      <p className="text-xs text-muted-foreground">
        Findings describe the uploaded file — a synthetic demo dataset, not a
        real company. Shipment adherence describes schedule outcomes, not
        customer delivery performance.
      </p>
    </section>
  );
}
