import { FilterSelect } from "@/components/patterns";
import type { FilterOption } from "@/components/patterns";
import {
  ORDER_STATUS_OPTIONS,
  SHIPMENT_OUTCOME_OPTIONS,
  SHIPPING_MODE_OPTIONS,
  isFiltered,
  useAnalyticsFilters,
} from "@/lib/analytics-filters";

function toOptions(values: string[]): FilterOption[] {
  return values.map((value) => ({ value, label: value }));
}

/**
 * Shared Phase-15 analytics filter bar (ADR-038). One control set bound to
 * the single shared filter state: changing any filter refreshes every
 * analytics surface that consumes it, restarts order pagination, and never
 * touches Data Quality or the session-wide filter-option domains.
 */
export default function FilterBar({ idPrefix }: { idPrefix: string }) {
  const {
    filters,
    setFilter,
    resetFilters,
    options,
    optionsLoading,
    optionsError,
  } = useAnalyticsFilters();

  const openDisabled = options === null;
  const openNote =
    optionsError !== null
      ? "Market, region, and category options could not be loaded; other filters remain available."
      : optionsLoading
        ? "Loading market, region, and category options…"
        : null;
  const rangeInvalid =
    filters.from !== null &&
    filters.from !== "" &&
    filters.to !== null &&
    filters.to !== "" &&
    filters.from > filters.to;

  return (
    <section aria-label="Analytics filters" className="rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Analytics filters</h3>
        <button
          type="button"
          onClick={resetFilters}
          disabled={!isFiltered(filters)}
          className="rounded-md border px-2 py-1 text-sm disabled:opacity-50"
        >
          Reset filters
        </button>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        Filters apply to Overview, Delivery, Commercial, and Diagnostics. Data
        Quality always describes the whole session.
      </p>
      {openNote !== null ? (
        <p className="mt-1 text-sm text-muted-foreground" role="status">
          {openNote}
        </p>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-3">
        <div className="flex flex-col gap-1">
          <label htmlFor={`${idPrefix}-from`} className="text-sm font-medium">
            From (order date)
          </label>
          <input
            id={`${idPrefix}-from`}
            type="date"
            className="rounded-md border bg-background px-2 py-1 text-sm"
            value={filters.from ?? ""}
            min={options?.dateRange.minOrderDate ?? undefined}
            max={options?.dateRange.maxOrderDate ?? undefined}
            onChange={(event) => {
              const next = event.target.value;
              setFilter("from", next === "" ? null : next);
            }}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={`${idPrefix}-to`} className="text-sm font-medium">
            To (order date)
          </label>
          <input
            id={`${idPrefix}-to`}
            type="date"
            className="rounded-md border bg-background px-2 py-1 text-sm"
            value={filters.to ?? ""}
            min={options?.dateRange.minOrderDate ?? undefined}
            max={options?.dateRange.maxOrderDate ?? undefined}
            onChange={(event) => {
              const next = event.target.value;
              setFilter("to", next === "" ? null : next);
            }}
          />
        </div>
        <FilterSelect
          id={`${idPrefix}-market`}
          label="Market"
          options={options !== null ? toOptions(options.markets) : []}
          value={filters.market}
          disabled={openDisabled}
          onChange={(value) => setFilter("market", value)}
        />
        <FilterSelect
          id={`${idPrefix}-region`}
          label="Region"
          options={options !== null ? toOptions(options.regions) : []}
          value={filters.region}
          disabled={openDisabled}
          onChange={(value) => setFilter("region", value)}
        />
        <FilterSelect
          id={`${idPrefix}-category`}
          label="Category"
          options={options !== null ? toOptions(options.categories) : []}
          value={filters.category}
          disabled={openDisabled}
          onChange={(value) => setFilter("category", value)}
        />
        <FilterSelect
          id={`${idPrefix}-shipping-mode`}
          label="Shipping mode"
          options={[...SHIPPING_MODE_OPTIONS]}
          value={filters.shipping_mode}
          onChange={(value) => setFilter("shipping_mode", value)}
        />
        <FilterSelect
          id={`${idPrefix}-order-status`}
          label="Order status"
          options={[...ORDER_STATUS_OPTIONS]}
          value={filters.order_status}
          onChange={(value) => setFilter("order_status", value)}
        />
        <FilterSelect
          id={`${idPrefix}-shipment-outcome`}
          label="Shipment outcome"
          options={[...SHIPMENT_OUTCOME_OPTIONS]}
          value={filters.shipment_outcome}
          onChange={(value) => setFilter("shipment_outcome", value)}
        />
      </div>
      {options?.dateRange.minOrderDate != null ||
      options?.dateRange.maxOrderDate != null ? (
        <p className="mt-2 text-sm text-muted-foreground">
          Available order dates: {options?.dateRange.minOrderDate ?? "—"} to{" "}
          {options?.dateRange.maxOrderDate ?? "—"}.
        </p>
      ) : null}
      {rangeInvalid ? (
        <p className="mt-1 text-sm text-muted-foreground" role="status">
          The start date is after the end date, so matching results may be
          empty. The range is sent unchanged.
        </p>
      ) : null}
    </section>
  );
}
