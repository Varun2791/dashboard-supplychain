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
    <section
      aria-label="Analytics filters"
      className="rounded-lg border border-border bg-card px-3 py-2.5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-analytical text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
          Analytics filters
          {isFiltered(filters) ? (
            <span className="text-foreground"> · filtered</span>
          ) : (
            <span> · all</span>
          )}
        </h3>
        <button
          type="button"
          onClick={resetFilters}
          disabled={!isFiltered(filters)}
          className="font-analytical rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          Reset filters
        </button>
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">
        Filters apply to Overview, Delivery, Commercial, and Diagnostics. Data
        Quality always describes the whole session.
      </p>
      {openNote !== null ? (
        <p className="mt-1 text-sm text-muted-foreground" role="status">
          {openNote}
        </p>
      ) : null}
      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-3 lg:grid-cols-4">
        <div
          className="filter-field flex min-w-0 items-end gap-1.5"
          data-active={filters.from != null && filters.from !== ""}
        >
          <div className="flex min-w-0 flex-col gap-0.5">
            <label
              htmlFor={`${idPrefix}-from`}
              className="font-analytical text-[11px] font-medium tracking-wide text-muted-foreground uppercase"
            >
              From (order date)
            </label>
            <input
              id={`${idPrefix}-from`}
              type="date"
              className="filter-control rounded-md border border-border bg-background px-2 py-1 text-[13px]"
              value={filters.from ?? ""}
              min={options?.dateRange.minOrderDate ?? undefined}
              max={options?.dateRange.maxOrderDate ?? undefined}
              onChange={(event) => {
                const next = event.target.value;
                setFilter("from", next === "" ? null : next);
              }}
            />
          </div>
        </div>
        <div
          className="filter-field flex min-w-0 items-end gap-1.5"
          data-active={filters.to != null && filters.to !== ""}
        >
          <div className="flex min-w-0 flex-col gap-0.5">
            <label
              htmlFor={`${idPrefix}-to`}
              className="font-analytical text-[11px] font-medium tracking-wide text-muted-foreground uppercase"
            >
              To (order date)
            </label>
            <input
              id={`${idPrefix}-to`}
              type="date"
              className="filter-control rounded-md border border-border bg-background px-2 py-1 text-[13px]"
              value={filters.to ?? ""}
              min={options?.dateRange.minOrderDate ?? undefined}
              max={options?.dateRange.maxOrderDate ?? undefined}
              onChange={(event) => {
                const next = event.target.value;
                setFilter("to", next === "" ? null : next);
              }}
            />
          </div>
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
