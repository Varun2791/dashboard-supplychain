import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  fetchKpisCommercial,
  fetchKpisDelivery,
  fetchOrders,
} from "@/lib/api";
import type {
  FilterQuery,
  KpiCommercialData,
  KpiDeliveryData,
  KpiGroup,
  OrderRow,
} from "@/lib/api";
import { useAnalyticsFilters } from "@/lib/analytics-filters";
import { findKpi, metricDenominator, rankGroups } from "@/lib/diagnostics-rank";
import { formatKpiValue } from "@/lib/kpi-format";
import { AnalyticalTable, ScrollTable } from "@/components/AnalyticalTable";
import { useSession } from "@/lib/session";
import { VIEWS } from "@/lib/view-registry";
import FilterBar from "@/components/FilterBar";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

const LATE_RATE_ID = "kpi.ship.late_rate";
const LOSS_RATE_ID = "kpi.orders.loss_making_rate";

/** ADR-039 shipment ranking dimensions (only these four are selectable). */
const SHIPMENT_DIMENSIONS: ReadonlyArray<{ by: string; label: string }> = [
  { by: "shipping_mode", label: "Shipping mode" },
  { by: "destination_market", label: "Destination market" },
  { by: "destination_region", label: "Destination region" },
  { by: "category_name", label: "Product category" },
];

/** ADR-039 commercial ranking dimensions (only these six are selectable). */
const COMMERCIAL_DIMENSIONS: ReadonlyArray<{ by: string; label: string }> = [
  { by: "department_name", label: "Department" },
  { by: "category_name", label: "Product category" },
  { by: "product_name", label: "Product" },
  { by: "destination_market", label: "Destination market" },
  { by: "destination_region", label: "Destination region" },
  { by: "customer_segment", label: "Customer segment" },
];

function isPending(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 409;
}

function failureMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiRequestError) {
    return error.message;
  }
  return fallback;
}

function rateText(group: KpiGroup, metricId: string): string {
  const kpi = findKpi(group.kpis, metricId);
  if (kpi === null || kpi.status !== "ok" || kpi.value === null) {
    const reason =
      kpi?.reason !== null && kpi?.reason !== undefined && kpi.reason !== ""
        ? ` — ${kpi.reason}`
        : "";
    return `Unavailable${reason}`;
  }
  return formatKpiValue(metricId, kpi.value);
}

/**
 * One governed diagnostic ranking table. Groups arrive from the existing
 * grouped backend responses and are only presentation-sorted here:
 * available metric values first (descending), deterministic group-key
 * ascending tie-break, unavailable after available (never ranked as zero).
 * Every ranked rate shows its backend denominator beside it. Rank numbers
 * reflect display order only: rank 1 means highest on the shown metric,
 * never a root cause, opportunity, or grade.
 */
function RankingTable({
  caption,
  groups,
  metricId,
  metricLabel,
  populationLabel,
}: {
  caption: string;
  groups: KpiGroup[];
  metricId: string;
  metricLabel: string;
  populationLabel: string;
}) {
  const ranked = rankGroups(groups, metricId);
  return (
    <AnalyticalTable label={caption}>
      <thead>
        <tr>
          <th scope="col">Associated group</th>
          <th scope="col">{metricLabel}</th>
          <th scope="col">{populationLabel}</th>
          <th scope="col">Rank</th>
        </tr>
      </thead>
      <tbody>
        {/* rankGroups places every available metric before any unavailable
            one, so the display index is the rank; unavailable rows show an
            em dash, never a rank and never zero. */}
        {ranked.map((group, index) => {
          const denominator = metricDenominator(group, metricId);
          const kpi = findKpi(group.kpis, metricId);
          const available =
            kpi !== null && kpi.status === "ok" && kpi.value !== null;
          return (
            <tr key={group.key}>
              <td>{group.key}</td>
              <td>{rateText(group, metricId)}</td>
              <td>
                {denominator === null
                  ? "Unavailable"
                  : denominator.toLocaleString("en-US")}
              </td>
              <td>{available ? index + 1 : "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </AnalyticalTable>
  );
}

function DimensionSelect({
  id,
  label,
  dimensions,
  value,
  onChange,
}: {
  id: string;
  label: string;
  dimensions: ReadonlyArray<{ by: string; label: string }>;
  value: string;
  onChange: (by: string) => void;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <label
        htmlFor={id}
        className="font-analytical text-[11px] font-medium tracking-wide text-muted-foreground uppercase"
      >
        {label}
      </label>
      <select
        id={id}
        className="max-w-56 truncate rounded-md border border-border bg-background px-2 py-1 text-[13px]"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {dimensions.map((dimension) => (
          <option key={dimension.by} value={dimension.by}>
            {dimension.label}
          </option>
        ))}
      </select>
    </div>
  );
}

interface RankingFetch<T> {
  data: T | null;
  failure: string | null;
  loading: boolean;
}

function useRanking<T>(
  sessionId: string | null,
  sessionState: string | null,
  filterKey: string,
  dimension: string,
  fetchGroups: (
    sessionId: string,
    by: string,
    query: FilterQuery,
  ) => Promise<T>,
  query: FilterQuery,
): RankingFetch<T> {
  // Ranking results are immutable per session, filter, and dimension: a
  // keyed cache keeps stale responses from overwriting the current view,
  // and loading is derived (no synchronous state reset inside effects).
  const [cache, setCache] = useState<{
    key: string;
    data: T | null;
    failure: string | null;
    failedAtState: string | null;
  } | null>(null);
  const generation = useRef(0);

  const key =
    sessionId === null ? null : `${sessionId}|${filterKey}|${dimension}`;
  const visible =
    cache !== null && key !== null && cache.key === key ? cache : null;

  useEffect(() => {
    if (sessionId === null || key === null) {
      return;
    }
    if (
      cache?.key === key &&
      (cache.data !== null || cache.failedAtState === sessionState)
    ) {
      return;
    }
    const requestId = generation.current + 1;
    generation.current = requestId;
    const requestKey = key;
    const requestQuery = query;
    const requestDimension = dimension;
    let cancelled = false;
    void (async () => {
      try {
        const data = await fetchGroups(
          sessionId,
          requestDimension,
          requestQuery,
        );
        if (cancelled || generation.current !== requestId) {
          return;
        }
        setCache({ key: requestKey, data, failure: null, failedAtState: null });
      } catch (error) {
        if (cancelled || generation.current !== requestId) {
          return;
        }
        if (isPending(error)) {
          // KPI analysis has not completed yet; the next session-state
          // advance retries automatically.
          return;
        }
        setCache({
          key: requestKey,
          data: null,
          failure: failureMessage(error, "The ranking could not be loaded."),
          failedAtState: sessionState,
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, sessionState, key, cache, dimension, fetchGroups, query]);

  if (visible?.data !== null && visible?.data !== undefined) {
    return { data: visible.data, failure: null, loading: false };
  }
  if (visible?.failure !== null && visible?.failure !== undefined) {
    return { data: null, failure: visible.failure, loading: false };
  }
  return { data: null, failure: null, loading: sessionId !== null };
}

function ShipmentRanking({
  sessionId,
  sessionState,
  filterKey,
  query,
}: {
  sessionId: string;
  sessionState: string | null;
  filterKey: string;
  query: FilterQuery;
}) {
  const [dimension, setDimension] = useState("shipping_mode");
  const { data, failure, loading } = useRanking<KpiDeliveryData>(
    sessionId,
    sessionState,
    filterKey,
    dimension,
    fetchKpisDelivery,
    query,
  );

  return (
    <section aria-labelledby="diagnostics-shipment-heading">
      <h3 id="diagnostics-shipment-heading" className="text-base font-semibold">
        Late-rate ranking
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Groups ordered by observed late-shipment rate. Values describe
        association, not causation.
      </p>
      <div className="mt-2">
        <DimensionSelect
          id="diagnostics-shipment-dimension"
          label="Rank by"
          dimensions={SHIPMENT_DIMENSIONS}
          value={dimension}
          onChange={setDimension}
        />
      </div>
      {dimension === "category_name" ? (
        <p className="mt-2 text-sm text-muted-foreground">
          Product-category groups cover single-merchandise orders with a
          governed category only; orders spanning multiple categories form no
          group. This population differs from the commercial category ranking
          below, so the two cannot be compared directly.
        </p>
      ) : null}
      <div className="mt-2">
        {loading ? (
          <LoadingState label="Loading the late-rate ranking…" />
        ) : failure !== null ? (
          <ErrorState
            title="The late-rate ranking could not be loaded"
            message={failure}
            guidance="No ranking is shown; nothing stale is displayed."
          />
        ) : data === null ? (
          <LoadingState label="Loading the late-rate ranking…" />
        ) : data.eligibleOrders === 0 ? (
          <p className="text-sm text-muted-foreground" role="status">
            Unavailable — no shipment-eligible orders under the current filters.
            Order records below may still list orders, such as cancelled ones,
            because they follow a different population.
          </p>
        ) : data.groups.length === 0 ? (
          <p className="text-sm text-muted-foreground" role="status">
            No groups are available under the current filters.
          </p>
        ) : (
          <>
            <RankingTable
              caption="Associated groups ordered by observed late-shipment rate"
              groups={data.groups}
              metricId={LATE_RATE_ID}
              metricLabel="Late-shipment rate"
              populationLabel="Eligible orders"
            />
            <p className="mt-1 text-sm text-muted-foreground">
              {data.eligibleOrders.toLocaleString("en-US")} shipment-eligible
              orders. {data.exclusions}
            </p>
          </>
        )}
      </div>
    </section>
  );
}

function CommercialRanking({
  sessionId,
  sessionState,
  filterKey,
  query,
}: {
  sessionId: string;
  sessionState: string | null;
  filterKey: string;
  query: FilterQuery;
}) {
  const [dimension, setDimension] = useState("department_name");
  const { data, failure, loading } = useRanking<KpiCommercialData>(
    sessionId,
    sessionState,
    filterKey,
    dimension,
    fetchKpisCommercial,
    query,
  );

  return (
    <section aria-labelledby="diagnostics-commercial-heading">
      <h3
        id="diagnostics-commercial-heading"
        className="text-base font-semibold"
      >
        Loss-making-order-rate ranking
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Groups ordered by observed loss-making-order rate. Values describe
        association, not causation.
      </p>
      <div className="mt-2">
        <DimensionSelect
          id="diagnostics-commercial-dimension"
          label="Rank by"
          dimensions={COMMERCIAL_DIMENSIONS}
          value={dimension}
          onChange={setDimension}
        />
      </div>
      {dimension === "category_name" ? (
        <p className="mt-2 text-sm text-muted-foreground">
          Product-category groups originate from item contribution, and
          contributing orders are evaluated on whole-order recorded profit. This
          population differs from the shipment category ranking above, so the
          two cannot be compared directly.
        </p>
      ) : null}
      <div className="mt-2">
        {loading ? (
          <LoadingState label="Loading the loss-making-order-rate ranking…" />
        ) : failure !== null ? (
          <ErrorState
            title="The loss-making-order-rate ranking could not be loaded"
            message={failure}
            guidance="No ranking is shown; nothing stale is displayed."
          />
        ) : data === null ? (
          <LoadingState label="Loading the loss-making-order-rate ranking…" />
        ) : data.groups.length === 0 ? (
          <p className="text-sm text-muted-foreground" role="status">
            No groups are available under the current filters.
          </p>
        ) : (
          <>
            <RankingTable
              caption="Associated groups ordered by observed loss-making-order rate"
              groups={data.groups}
              metricId={LOSS_RATE_ID}
              metricLabel="Loss-making-order rate"
              populationLabel="Orders"
            />
            <p className="mt-1 text-sm text-muted-foreground">
              Commercial scope: {data.statusScope}. Group margins and discount
              rates are backend amount-weighted ratios, never averages.
            </p>
          </>
        )}
      </div>
    </section>
  );
}

function lateText(value: boolean | null): string {
  if (value === true) {
    return "Late";
  }
  if (value === false) {
    return "On schedule";
  }
  return "No value (shipping cancelled or unclassifiable)";
}

/**
 * Sanitized order drilldown (ADR-038). Forward-only keyset traversal with a
 * "load more" accumulator: the producer cursor is passed back verbatim and
 * never decoded, and any filter change discards the accumulated pages and
 * restarts from the first page.
 */
function OrderDrilldown({
  sessionId,
  sessionState,
  filterKey,
  query,
}: {
  sessionId: string;
  sessionState: string | null;
  filterKey: string;
  query: FilterQuery;
}) {
  const { filters, resetFilters } = useAnalyticsFilters();
  // Accumulated pages are immutable per session and filter combination: a
  // keyed cache restarts pagination from the first page on any filter
  // change, and loading is derived (no synchronous reset inside effects).
  const [cache, setCache] = useState<{
    key: string;
    rows: OrderRow[];
    total: number | null;
    nextCursor: string | null;
    failure: string | null;
    failedAtState: string | null;
  } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const generation = useRef(0);

  const key = `${sessionId}|${filterKey}`;
  const visible = cache !== null && cache.key === key ? cache : null;
  const rows = visible?.rows ?? [];
  const total = visible?.total ?? null;
  const nextCursor = visible?.nextCursor ?? null;
  const failure = visible?.failure ?? null;
  const loading = visible === null;

  useEffect(() => {
    if (
      cache?.key === key &&
      (cache.total !== null || cache.failedAtState === sessionState)
    ) {
      return;
    }
    const requestId = generation.current + 1;
    generation.current = requestId;
    const requestKey = key;
    const requestQuery = query;
    let cancelled = false;
    void (async () => {
      try {
        const data = await fetchOrders(sessionId, { ...requestQuery });
        if (cancelled || generation.current !== requestId) {
          return;
        }
        setCache({
          key: requestKey,
          rows: data.rows,
          total: data.page.total,
          nextCursor: data.page.nextCursor,
          failure: null,
          failedAtState: null,
        });
      } catch (error) {
        if (cancelled || generation.current !== requestId) {
          return;
        }
        if (isPending(error)) {
          // KPI analysis has not completed yet; the next session-state
          // advance retries automatically.
          return;
        }
        setCache({
          key: requestKey,
          rows: [],
          total: null,
          nextCursor: null,
          failure: failureMessage(
            error,
            "The order records could not be loaded.",
          ),
          failedAtState: sessionState,
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, sessionState, key, cache, query]);

  async function loadMore(): Promise<void> {
    if (nextCursor === null || loadingMore || visible === null) {
      return;
    }
    const requestId = generation.current;
    const pageKey = visible.key;
    const pageCursor = nextCursor;
    const pageQuery = query;
    setLoadingMore(true);
    try {
      const data = await fetchOrders(sessionId, {
        ...pageQuery,
        cursor: pageCursor,
      });
      if (generation.current !== requestId) {
        return;
      }
      setCache((current) => {
        if (current === null || current.key !== pageKey) {
          return current;
        }
        return {
          ...current,
          rows: [...current.rows, ...data.rows],
          total:
            current.total !== null && data.page.total !== current.total
              ? data.page.total
              : current.total,
          nextCursor: data.page.nextCursor,
        };
      });
    } catch (error) {
      if (generation.current !== requestId) {
        return;
      }
      if (!isPending(error)) {
        const message = failureMessage(
          error,
          "The next order records could not be loaded.",
        );
        setCache((current) => {
          if (current === null || current.key !== pageKey) {
            return current;
          }
          return { ...current, failure: message };
        });
      }
    } finally {
      if (generation.current === requestId) {
        setLoadingMore(false);
      }
    }
  }

  const totalLabel =
    total === null
      ? `${rows.length.toLocaleString("en-US")} matching orders`
      : rows.length < total
        ? `${total.toLocaleString("en-US")} matching orders · showing ${rows.length.toLocaleString("en-US")}`
        : `${total.toLocaleString("en-US")} matching orders`;

  return (
    <section aria-labelledby="diagnostics-orders-heading">
      <h3 id="diagnostics-orders-heading" className="text-base font-semibold">
        Filtered order records
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Sanitized one-row-per-order records behind the filtered population.
        Order identifiers are operational row keys, not customer identities.
      </p>
      {filters.category !== null ? (
        <p className="mt-1 text-sm text-muted-foreground">
          Commercial item-level totals can include matching lines from
          multi-merchandise orders, while these records follow order-level
          merchandise semantics and can exclude those orders. Commercial
          headline sums are therefore not guaranteed to equal sums of the
          visible order aggregates. This is governed grain behavior, not a data
          error.
        </p>
      ) : null}
      <div className="mt-2">
        {loading ? (
          <LoadingState label="Loading the order records…" />
        ) : failure !== null && rows.length === 0 ? (
          <ErrorState
            title="The order records could not be loaded"
            message={failure}
            guidance="No records are shown; nothing stale is displayed."
          />
        ) : total === 0 ? (
          <EmptyState
            title="No orders match the current filters"
            body="Change a filter or reset all filters to see records again. This is a valid empty result, not an error."
            action={
              <button
                type="button"
                onClick={resetFilters}
                className="rounded-md border px-2 py-1 text-sm"
              >
                Reset filters to see records
              </button>
            }
          />
        ) : (
          <>
            <p
              className="font-analytical text-sm text-muted-foreground tabular-nums"
              role="status"
            >
              {totalLabel}
            </p>
            <div className="mt-2">
              <ScrollTable label="Filtered sanitized order records">
                <thead>
                  <tr className="border-b text-left">
                    <th scope="col" className="px-3 py-2 font-medium">
                      Order ID
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Order date
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Status
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Shipping mode
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Market / Region
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Shipment outcome
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Scheduled days
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Actual days
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Recorded net order value
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Recorded profit
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      <span className="sr-only">Row details</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.order_id} className="border-b last:border-0">
                      <td className="px-3 py-2 font-analytical">
                        {row.order_id}
                      </td>
                      <td className="px-3 py-2">
                        {row.order_timestamp ?? "—"}
                      </td>
                      <td className="px-3 py-2">{row.order_status ?? "—"}</td>
                      <td className="px-3 py-2">{row.shipping_mode ?? "—"}</td>
                      <td className="px-3 py-2">
                        {[row.destination_market, row.destination_region]
                          .filter((part) => part !== null && part !== "")
                          .join(" / ") || "—"}
                      </td>
                      <td className="px-3 py-2">
                        {row.shipment_outcome ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-analytical tabular-nums">
                        {row.scheduled_shipping_days ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-analytical tabular-nums">
                        {row.actual_shipping_days ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-analytical tabular-nums">
                        {row.net_value}
                      </td>
                      <td className="px-3 py-2 text-right font-analytical tabular-nums">
                        {row.profit_total}
                      </td>
                      <td className="px-3 py-2">
                        <details>
                          <summary className="cursor-pointer">Details</summary>
                          <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                            <dt className="text-muted-foreground">Segment</dt>
                            <dd>{row.customer_segment ?? "—"}</dd>
                            <dt className="text-muted-foreground">Country</dt>
                            <dd>{row.destination_country ?? "—"}</dd>
                            <dt className="text-muted-foreground">Lateness</dt>
                            <dd>{lateText(row.is_late)}</dd>
                            <dt className="text-muted-foreground">Lines</dt>
                            <dd>{row.line_count}</dd>
                            <dt className="text-muted-foreground">Units</dt>
                            <dd>{row.total_units}</dd>
                            <dt className="text-muted-foreground">Gross</dt>
                            <dd>{row.gross_value}</dd>
                            <dt className="text-muted-foreground">Discount</dt>
                            <dd>{row.discount_total}</dd>
                          </dl>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </ScrollTable>
            </div>
            {failure !== null ? (
              <p className="mt-2 text-sm text-muted-foreground" role="alert">
                {failure}
              </p>
            ) : null}
            {nextCursor !== null ? (
              <button
                type="button"
                onClick={() => void loadMore()}
                disabled={loadingMore}
                className="font-analytical mt-2 rounded-md border border-border px-3 py-1.5 text-[13px] disabled:opacity-50"
              >
                {loadingMore
                  ? "Loading more orders…"
                  : "Load more matching orders"}
              </button>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}

/**
 * Phase-15 Diagnostics: which combinations are associated with the poor KPI,
 * and which sanitized orders sit behind the selected filtered population.
 * Rankings reorder backend group results (presentation only); the drilldown
 * reads the real `/orders` producer. Association-only language throughout:
 * no causes, drivers, or impacts are claimed.
 */
export default function DiagnosticsView() {
  const { session, sessionState } = useSession();
  const { query, filterKey } = useAnalyticsFilters();

  const meta = VIEWS.find((entry) => entry.id === "diagnostics");

  if (session === null) {
    return (
      <section aria-labelledby="diagnostics-heading">
        <h2
          id="diagnostics-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Diagnostics
        </h2>
        {meta !== undefined ? (
          <p className="mt-1 text-sm text-muted-foreground">{meta.question}</p>
        ) : null}
        <div className="mt-4">
          <EmptyState
            title="No dataset loaded"
            body="Upload a CSV on the Upload view first. Associated-group rankings and sanitized order records appear here once KPI analysis completes."
          />
        </div>
      </section>
    );
  }

  if (sessionState === "FAILED") {
    return (
      <section aria-labelledby="diagnostics-heading">
        <h2
          id="diagnostics-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Diagnostics
        </h2>
        <div className="mt-4">
          <ErrorState
            title="This session ended in FAILED"
            message="The session failed before KPI analysis could complete, so there are no diagnostic results to show. This is a terminal session state, not a gated stage."
            guidance="Open the Upload view for the failing stage, code, and next steps — or remove the session and upload a fixed file."
          />
        </div>
      </section>
    );
  }

  const sessionId = session.sessionId;
  const gated =
    sessionState === "CANONICALIZING" || sessionState === "ANALYZING";

  return (
    <section
      aria-labelledby="diagnostics-heading"
      className="flex w-full flex-col gap-6"
    >
      <div>
        <h2
          id="diagnostics-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Diagnostics
        </h2>
        {meta !== undefined ? (
          <p className="mt-1 text-sm text-muted-foreground">{meta.question}</p>
        ) : null}
        <p className="mt-1 text-sm text-muted-foreground" role="status">
          Session {session.sessionId.slice(0, 8)} · {sessionState ?? "starting"}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Rankings describe observed association only — never causes, drivers,
          or root causes. Start from a headline signal, compare grouped
          associations, then inspect order-level evidence below.
        </p>
        {gated ? (
          <p className="mt-1 text-sm text-muted-foreground">
            KPI analysis has not completed yet; rankings and records appear
            automatically once it does. If a data-quality gate holds the
            session, analytics stay unavailable until the input is fixed or
            replaced — this is not a terminal failure.
          </p>
        ) : null}
      </div>
      <FilterBar idPrefix="diagnostics" />
      <ShipmentRanking
        sessionId={sessionId}
        sessionState={sessionState}
        filterKey={filterKey}
        query={query}
      />
      <CommercialRanking
        sessionId={sessionId}
        sessionState={sessionState}
        filterKey={filterKey}
        query={query}
      />
      <OrderDrilldown
        sessionId={sessionId}
        sessionState={sessionState}
        filterKey={filterKey}
        query={query}
      />
      <p className="text-xs text-muted-foreground">
        Findings describe the uploaded file — a synthetic demo dataset, not a
        real company. Rankings show observed association only; commercial
        figures are recorded order values, not recognized revenue, and currency
        is unspecified.
      </p>
    </section>
  );
}
