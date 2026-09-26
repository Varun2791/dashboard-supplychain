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
  fetchKpisCommercial,
  fetchKpisOverview,
} from "@/lib/api";
import type {
  KpiCommercialData,
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

interface CommercialReports {
  overview: KpiOverviewData;
  scope: KpiCommercialData;
  byDepartment: KpiCommercialData;
  byCategory: KpiCommercialData;
  byProduct: KpiCommercialData;
  byMarket: KpiCommercialData;
  byRegion: KpiCommercialData;
  bySegment: KpiCommercialData;
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

/** Headline commercial cards (labels always come from the API). */
const HEADLINE_IDS: readonly string[] = [
  "kpi.value.gross",
  "kpi.value.discount",
  "kpi.value.net",
  "kpi.profit.recorded",
  "kpi.margin.profit",
  "kpi.rate.discount",
  "kpi.value.aov",
  "kpi.units.per_order",
  "kpi.lines.per_order",
  "kpi.orders.loss_making_rate",
];

/** Late-associated value context (association only; never lost sales). */
const ASSOCIATION_IDS: readonly string[] = [
  "kpi.value.net_associated_with_late",
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
      <ScrollTable label={`Commercial value by ${dimension}`}>
        <thead>
          <tr className="border-b text-left">
            <th scope="col" className="px-3 py-2 font-medium">
              {dimension}
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Net value
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Recorded profit
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Profit margin
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Discounts
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Discount rate
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Loss-making-order rate
            </th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <tr key={group.key} className="border-b last:border-0">
              <td className="px-3 py-2">{group.key}</td>
              <td className="px-3 py-2">
                {cellText(findKpi(group.kpis, "kpi.value.net"))}
              </td>
              <td className="px-3 py-2">
                {cellText(findKpi(group.kpis, "kpi.profit.recorded"))}
              </td>
              <td className="px-3 py-2">
                {cellText(findKpi(group.kpis, "kpi.margin.profit"))}
              </td>
              <td className="px-3 py-2">
                {cellText(findKpi(group.kpis, "kpi.value.discount"))}
              </td>
              <td className="px-3 py-2">
                {cellText(findKpi(group.kpis, "kpi.rate.discount"))}
              </td>
              <td className="px-3 py-2">
                {cellText(findKpi(group.kpis, "kpi.orders.loss_making_rate"))}
              </td>
            </tr>
          ))}
        </tbody>
      </ScrollTable>
    </div>
  );
}

/**
 * Recorded-net bar chart for one dimension. Money values are a display-only
 * mapping of backend totals; the table below carries the same values
 * textually so color is never the only encoding.
 */
function NetValueChart({
  dimension,
  groups,
}: {
  dimension: string;
  groups: KpiGroup[];
}) {
  const rows = groups.map((group) => {
    const net = findKpi(group.kpis, "kpi.value.net");
    return {
      group: group.key,
      net: net !== null && net.status === "ok" ? toPlottable(net.value) : null,
    };
  });
  const withData = rows.filter((row) => row.net !== null).length;
  if (withData === 0) {
    return (
      <p className="mt-2 text-sm text-muted-foreground" role="status">
        No recorded net values are available by {dimension}.
      </p>
    );
  }
  return (
    <figure className="mt-2">
      <div role="img" aria-label={`Recorded net order value by ${dimension}`}>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={rows} margin={{ ...chartMargins, left: 48 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="group" tick={{ fontSize: chartTickFontSize }} />
            <YAxis tick={{ fontSize: chartTickFontSize }} width={56} />
            <Tooltip />
            <Legend />
            <Bar
              dataKey="net"
              name="Recorded net order value"
              fill={chartPalette[0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-1 text-sm text-muted-foreground">
        Recorded net order value by {dimension}, in neutral currency units.
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
            <NetValueChart dimension={dimension} groups={groups} />
          ) : null}
          <GroupTable dimension={dimension} groups={groups} />
        </>
      )}
    </section>
  );
}

/**
 * Phase-14 Commercial analytics: headline recorded value/profit/margin/
 * discount/unit KPIs, late-associated value context, and backend-grouped
 * splits by department, category, product, market, region, and customer
 * segment. Renders backend-computed values only; it derives no net value,
 * averages no margin, and calculates no rate or share.
 */
export default function CommercialView() {
  const { session, sessionState } = useSession();
  // Reports are immutable per session: an id-keyed cache plus the render
  // guard below keeps reset (null) and FAILED from showing stale results.
  const [cache, setCache] = useState<{
    sessionId: string;
    reports: CommercialReports | null;
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
          scope,
          byDepartment,
          byCategory,
          byProduct,
          byMarket,
          byRegion,
          bySegment,
        ] = await Promise.all([
          fetchKpisOverview(sessionId),
          fetchKpisCommercial(sessionId, null),
          fetchKpisCommercial(sessionId, "department_name"),
          fetchKpisCommercial(sessionId, "category_name"),
          fetchKpisCommercial(sessionId, "product_name"),
          fetchKpisCommercial(sessionId, "destination_market"),
          fetchKpisCommercial(sessionId, "destination_region"),
          fetchKpisCommercial(sessionId, "customer_segment"),
        ]);
        if (cancelled) {
          return;
        }
        setCache({
          sessionId,
          reports: {
            overview,
            scope,
            byDepartment,
            byCategory,
            byProduct,
            byMarket,
            byRegion,
            bySegment,
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

  const meta = VIEWS.find((entry) => entry.id === "commercial");

  if (session === null) {
    return (
      <section aria-labelledby="commercial-heading">
        <h2
          id="commercial-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Commercial
        </h2>
        {meta !== undefined ? (
          <p className="mt-1 text-sm text-muted-foreground">{meta.question}</p>
        ) : null}
        <div className="mt-4">
          <EmptyState
            title="No dataset loaded"
            body="Upload a CSV on the Upload view first. Commercial value results appear here once KPI analysis completes."
          />
        </div>
      </section>
    );
  }

  if (terminal) {
    return (
      <section aria-labelledby="commercial-heading">
        <h2
          id="commercial-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Commercial
        </h2>
        <div className="mt-4">
          <ErrorState
            title="This session ended in FAILED"
            message="The session failed before KPI analysis could complete, so there are no commercial results to show. This is a terminal session state, not a gated stage."
            guidance="Open the Upload view for the failing stage, code, and next steps — or remove the session and upload a fixed file."
          />
        </div>
      </section>
    );
  }

  if (failure !== null) {
    return (
      <section aria-labelledby="commercial-heading">
        <h2
          id="commercial-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Commercial
        </h2>
        <div className="mt-4">
          <ErrorState
            title="The commercial results could not be loaded"
            message={failure.message}
            guidance={[
              failure.code !== null ? `Code: ${failure.code}.` : null,
              failure.gone
                ? "This session is gone from the server. Upload the file again to start a new session."
                : "No commercial data is shown; nothing stale is displayed.",
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
      <section aria-labelledby="commercial-heading">
        <h2
          id="commercial-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Commercial
        </h2>
        <div className="mt-4 flex flex-col gap-2">
          <LoadingState label="Loading the commercial results…" />
          <p className="text-sm text-muted-foreground">
            Session {session.sessionId.slice(0, 8)} is{" "}
            {sessionState ?? "starting"}. Commercial results appear
            automatically once KPI analysis completes.
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
  const association = ASSOCIATION_IDS.map((id) =>
    findKpi(reports.overview.kpis, id),
  ).filter((kpi): kpi is KpiResult => kpi !== null);

  return (
    <section
      aria-labelledby="commercial-heading"
      className="flex w-full flex-col gap-6"
    >
      <div>
        <h2
          id="commercial-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Commercial
        </h2>
        {meta !== undefined ? (
          <p className="mt-1 text-sm text-muted-foreground">{meta.question}</p>
        ) : null}
        <p className="mt-1 text-sm text-muted-foreground" role="status">
          Session {session.sessionId.slice(0, 8)} · {sessionState ?? "starting"}{" "}
          · {reports.overview.totals.orders.toLocaleString("en-US")} orders ·{" "}
          {reports.overview.totals.items.toLocaleString("en-US")} order-item
          lines
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Order-status scope: {reports.scope.statusScope}. Commercial amounts
          originate at order-item grain; per-order means divide by distinct
          orders. Shared interactive filters belong to Phase 15 diagnostics, so
          no filter controls are wired here.
        </p>
      </div>
      <section aria-labelledby="commercial-headline-heading">
        <h3
          id="commercial-headline-heading"
          className="text-base font-semibold"
        >
          Recorded commercial value
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Recorded net order value is the authoritative commercial total; gross
          minus discount is a tolerance-checked reconciliation, never a
          recalculation. Amounts show two decimals with no currency; rates show
          one decimal. Negative recorded profit is retained, never clipped.
        </p>
        <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {headlines.map((kpi) => (
            <KpiCard key={kpi.id} kpi={kpi} />
          ))}
        </div>
      </section>
      <section aria-labelledby="commercial-association-heading">
        <h3
          id="commercial-association-heading"
          className="text-base font-semibold"
        >
          Late-associated value context
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Net order value on late-shipment orders describes association only —
          it is never lost sales, and lateness never explains profit.
        </p>
        <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {association.map((kpi) => (
            <KpiCard key={kpi.id} kpi={kpi} />
          ))}
        </div>
      </section>
      <BreakdownSection
        id="commercial-department-heading"
        title="Value, profit, and discount by department"
        intro="Descriptive comparison across departments (department, not category or product). Group margins and discount rates are backend amount-weighted ratios, never averages."
        dimension="Department"
        groups={reports.byDepartment.groups}
        chart={false}
      />
      <BreakdownSection
        id="commercial-category-heading"
        title="Value, profit, and discount by product category"
        intro="Descriptive comparison across product categories (category, not department or individual products)."
        dimension="Product category"
        groups={reports.byCategory.groups}
        chart
      />
      <BreakdownSection
        id="commercial-product-heading"
        title="Value, profit, and discount by product"
        intro="Descriptive comparison across individual governed products. No reference price is used anywhere."
        dimension="Product"
        groups={reports.byProduct.groups}
        chart={false}
      />
      <BreakdownSection
        id="commercial-market-heading"
        title="Value, profit, and discount by destination market"
        intro="Descriptive comparison across destination markets (order geography, not customer geography)."
        dimension="Destination market"
        groups={reports.byMarket.groups}
        chart
      />
      <BreakdownSection
        id="commercial-region-heading"
        title="Value, profit, and discount by destination region"
        intro="Descriptive comparison across coarse destination regions (order geography, not customer geography)."
        dimension="Destination region"
        groups={reports.byRegion.groups}
        chart={false}
      />
      <BreakdownSection
        id="commercial-segment-heading"
        title="Value, profit, and discount by customer segment"
        intro="Descriptive comparison across supplied customer segments (a business category, not a demographic inference). No personal fields are used."
        dimension="Customer segment"
        groups={reports.bySegment.groups}
        chart={false}
      />
      <p className="text-xs text-muted-foreground">
        Findings describe the uploaded file — a synthetic demo dataset, not a
        real company. Commercial figures are recorded order values, not
        recognized revenue, and currency is unspecified.
      </p>
    </section>
  );
}
