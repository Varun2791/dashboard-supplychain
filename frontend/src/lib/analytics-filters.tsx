import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { ApiRequestError, fetchFilterOptions } from "@/lib/api";
import type { FilterOptionsData, FilterQuery } from "@/lib/api";
import { useSession } from "@/lib/session";

/**
 * One authoritative Phase-15 analytics-filter state (ADR-038), owned above
 * the analytics views so filters persist across Overview / Delivery /
 * Commercial / Diagnostics navigation. Data Quality never consumes it.
 *
 * Single-select only: each categorical dimension holds one governed value
 * or null ("All"); dates hold ISO `YYYY-MM-DD` or null. No `department`,
 * `product`, `customer_segment`, `customer_id`, postal, or threshold
 * filters exist here — unless already covered by the governed
 * shipment-outcome/status controls.
 */
export interface AnalyticsFilters {
  from: string | null;
  to: string | null;
  market: string | null;
  region: string | null;
  category: string | null;
  shipping_mode: string | null;
  order_status: string | null;
  shipment_outcome: string | null;
}

export const DEFAULT_FILTERS: AnalyticsFilters = {
  from: null,
  to: null,
  market: null,
  region: null,
  category: null,
  shipping_mode: null,
  order_status: null,
  shipment_outcome: null,
};

/** Governed V1 shipping-mode options (canonical-schema §7; ADR-038 clarification). */
export const SHIPPING_MODE_OPTIONS: ReadonlyArray<{
  value: string;
  label: string;
}> = [
  { value: "STANDARD_CLASS", label: "Standard Class" },
  { value: "SECOND_CLASS", label: "Second Class" },
  { value: "FIRST_CLASS", label: "First Class" },
  { value: "SAME_DAY", label: "Same Day" },
];

/** Governed order-status vocabulary (canonical-schema §7). */
export const ORDER_STATUS_OPTIONS: ReadonlyArray<{
  value: string;
  label: string;
}> = [
  { value: "COMPLETE", label: "Complete" },
  { value: "CLOSED", label: "Closed" },
  { value: "PENDING", label: "Pending" },
  { value: "PROCESSING", label: "Processing" },
  { value: "ON_HOLD", label: "On hold" },
  { value: "CANCELED", label: "Canceled" },
  { value: "PAYMENT_REVIEW", label: "Payment review" },
  { value: "SUSPECTED_FRAUD", label: "Suspected fraud" },
];

/** Governed shipment-outcome vocabulary (canonical-schema §7). */
export const SHIPMENT_OUTCOME_OPTIONS: ReadonlyArray<{
  value: string;
  label: string;
}> = [
  { value: "LATE", label: "Late" },
  { value: "EARLY", label: "Early" },
  { value: "ON_SCHEDULE", label: "Exactly on schedule" },
  { value: "SHIPPING_CANCELED", label: "Shipping cancelled" },
];

/** Active filters as the shared backend query (inactive/All omitted). */
export function toFilterQuery(filters: AnalyticsFilters): FilterQuery {
  const query: FilterQuery = {};
  if (filters.from !== null && filters.from !== "") {
    query.from = filters.from;
  }
  if (filters.to !== null && filters.to !== "") {
    query.to = filters.to;
  }
  if (filters.market !== null) {
    query.market = filters.market;
  }
  if (filters.region !== null) {
    query.region = filters.region;
  }
  if (filters.category !== null) {
    query.category = filters.category;
  }
  if (filters.shipping_mode !== null) {
    query.shipping_mode = filters.shipping_mode;
  }
  if (filters.order_status !== null) {
    query.order_status = filters.order_status;
  }
  if (filters.shipment_outcome !== null) {
    query.shipment_outcome = filters.shipment_outcome;
  }
  return query;
}

export function isFiltered(filters: AnalyticsFilters): boolean {
  return Object.values(filters).some((value) => value !== null && value !== "");
}

interface AnalyticsFilterContextValue {
  filters: AnalyticsFilters;
  setFilter: (name: keyof AnalyticsFilters, value: string | null) => void;
  resetFilters: () => void;
  /** Shared backend query for the active filters (same for every surface). */
  query: FilterQuery;
  /** Stable key for refetching/filter-change resets. */
  filterKey: string;
  options: FilterOptionsData | null;
  optionsLoading: boolean;
  optionsError: string | null;
}

const AnalyticsFilterContext =
  createContext<AnalyticsFilterContextValue | null>(null);

export function AnalyticsFilterProvider({ children }: { children: ReactNode }) {
  const { session, sessionState } = useSession();
  const sessionId = session?.sessionId ?? null;
  // Filter and option caches are keyed by session: a replacement or reset
  // session simply misses the key, so a new session never inherits the
  // previous session's filter values and no reset effect is needed.
  const [filterCache, setFilterCache] = useState<{
    sessionId: string;
    filters: AnalyticsFilters;
  } | null>(null);
  const [optionsCache, setOptionsCache] = useState<{
    sessionId: string;
    options: FilterOptionsData;
  } | null>(null);
  const [optionsFailure, setOptionsFailure] = useState<{
    sessionId: string;
    message: string;
    failedAtState: string | null;
  } | null>(null);

  const filters =
    filterCache !== null && filterCache.sessionId === sessionId
      ? filterCache.filters
      : DEFAULT_FILTERS;
  const options =
    optionsCache !== null && optionsCache.sessionId === sessionId
      ? optionsCache.options
      : null;
  const optionsError =
    optionsFailure !== null && optionsFailure.sessionId === sessionId
      ? optionsFailure.message
      : null;
  // Pending while a usable session has neither options nor a terminal
  // options failure recorded for the current state.
  const optionsLoading =
    sessionId !== null &&
    sessionState !== "FAILED" &&
    options === null &&
    !(
      optionsFailure !== null &&
      optionsFailure.sessionId === sessionId &&
      optionsFailure.failedAtState === sessionState
    );

  // Filter domains come from the real producer (READY-gated like
  // analytics). A 409 NOT_READY is expected lifecycle timing, not a
  // terminal failure: the next session-state advance retries.
  // Terminal sessions never fetch: there is no domain to read.
  useEffect(() => {
    if (sessionId === null || sessionState === "FAILED") {
      return;
    }
    if (optionsCache?.sessionId === sessionId) {
      return;
    }
    if (
      optionsFailure?.sessionId === sessionId &&
      optionsFailure.failedAtState === sessionState
    ) {
      return;
    }
    let cancelled = false;
    const requestSession = sessionId;
    const requestState = sessionState;
    void (async () => {
      try {
        const data = await fetchFilterOptions(requestSession);
        if (cancelled) {
          return;
        }
        setOptionsCache({ sessionId: requestSession, options: data });
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (error instanceof ApiRequestError && error.status === 409) {
          return;
        }
        setOptionsFailure({
          sessionId: requestSession,
          message:
            error instanceof ApiRequestError
              ? error.message
              : "Could not read the filter options.",
          failedAtState: requestState,
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, sessionState, optionsCache, optionsFailure]);

  const setFilter = useCallback(
    (name: keyof AnalyticsFilters, value: string | null) => {
      if (sessionId === null) {
        return;
      }
      const current =
        filterCache !== null && filterCache.sessionId === sessionId
          ? filterCache.filters
          : DEFAULT_FILTERS;
      setFilterCache({ sessionId, filters: { ...current, [name]: value } });
    },
    [sessionId, filterCache],
  );

  const resetFilters = useCallback(() => {
    if (sessionId === null) {
      return;
    }
    setFilterCache({ sessionId, filters: DEFAULT_FILTERS });
  }, [sessionId]);

  const value = useMemo<AnalyticsFilterContextValue>(() => {
    const query = toFilterQuery(filters);
    const filterKey = JSON.stringify(query);
    return {
      filters,
      setFilter,
      resetFilters,
      query,
      filterKey,
      options,
      optionsLoading,
      optionsError,
    };
  }, [filters, setFilter, resetFilters, options, optionsLoading, optionsError]);

  return (
    <AnalyticsFilterContext.Provider value={value}>
      {children}
    </AnalyticsFilterContext.Provider>
  );
}

export function useAnalyticsFilters(): AnalyticsFilterContextValue {
  const context = useContext(AnalyticsFilterContext);
  if (context === null) {
    throw new Error(
      "useAnalyticsFilters must be used inside AnalyticsFilterProvider.",
    );
  }
  return context;
}
