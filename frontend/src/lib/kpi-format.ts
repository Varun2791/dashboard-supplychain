/**
 * Display-only KPI value formatting (Phase 12 executive overview).
 *
 * Counts render as integers, money as 2-dp neutral units (no currency
 * symbol, ADR-010), rates as 1-dp percentages, other backend decimals
 * verbatim. ID sets mirror `docs/kpi-contracts.md` value shapes; no
 * business arithmetic happens here — the backend owns every formula.
 */

/** Headline KPIs shown as Overview cards (labels always come from the API). */
export const OVERVIEW_CARD_IDS: readonly string[] = [
  "kpi.value.net",
  "kpi.profit.recorded",
  "kpi.margin.profit",
  "kpi.ship.late_rate",
  "kpi.ship.on_schedule_rate",
  "kpi.orders.count",
  "kpi.orders.shipment_eligible_count",
  "kpi.units.total",
];

/** Money values: 2-dp neutral-unit strings (contract §6; never currency). */
const MONEY_IDS: ReadonlySet<string> = new Set([
  "kpi.value.gross",
  "kpi.value.discount",
  "kpi.value.net",
  "kpi.profit.recorded",
  "kpi.value.aov",
  "kpi.value.net_associated_with_late",
]);

/** Rate values: 4-dp fraction strings rendered as 1-dp UI percentages. */
const RATE_IDS: ReadonlySet<string> = new Set([
  "kpi.margin.profit",
  "kpi.rate.discount",
  "kpi.ship.late_rate",
  "kpi.ship.on_schedule_rate",
  "kpi.ship.early_rate",
  "kpi.ship.exact_rate",
  "kpi.orders.loss_making_rate",
  "kpi.orders.strict_cancel_rate",
  "kpi.orders.fraud_rate",
  "kpi.orders.blocked_rate",
]);

/**
 * Short methodology phrases traceable to `docs/kpi-contracts.md` rows
 * (populations and exclusions arrive verbatim from the API per card).
 */
export const CARD_MEANINGS: Record<string, string> = {
  "kpi.value.net": "Authoritative commercial total across order-item lines.",
  "kpi.profit.recorded":
    "Recorded line profit; negative values are retained, never clipped.",
  "kpi.margin.profit":
    "Amount-weighted share: total profit divided by total net.",
  "kpi.value.gross":
    "Pre-discount recorded value summed across order-item lines.",
  "kpi.value.discount": "Recorded discounts summed across order-item lines.",
  "kpi.rate.discount":
    "Amount-weighted share: total discount divided by total gross.",
  "kpi.value.aov": "Mean recorded net per order; unavailable when no orders.",
  "kpi.units.per_order": "Mean units per order; unavailable when no orders.",
  "kpi.lines.per_order":
    "Mean order-item lines per order; unavailable when no orders.",
  "kpi.orders.loss_making_rate":
    "Share of orders with negative total recorded profit.",
  "kpi.value.net_associated_with_late":
    "Recorded net on late-shipment orders; association only, never lost sales.",
  "kpi.ship.late_rate":
    "Share of shipment-eligible orders arriving after schedule.",
  "kpi.ship.on_schedule_rate":
    "Share of shipment-eligible orders early or exactly on schedule.",
  "kpi.ship.early_rate":
    "Share of shipment-eligible orders arriving before schedule.",
  "kpi.ship.exact_rate":
    "Share of shipment-eligible orders arriving exactly on schedule.",
  "kpi.ship.avg_actual_days":
    "Mean actual shipping days across eligible orders with recorded days.",
  "kpi.ship.avg_scheduled_days":
    "Mean scheduled shipping days across eligible orders.",
  "kpi.ship.variance_days":
    "Mean schedule variance in days; negative means ahead of schedule.",
  "kpi.orders.strict_cancel_rate":
    "Share of orders with order status strictly cancelled.",
  "kpi.orders.fraud_rate": "Share of orders flagged as suspected fraud.",
  "kpi.orders.blocked_rate":
    "Share of orders with the shipping-blocked/cancelled shipment outcome.",
  "kpi.orders.count": "Distinct orders in scope.",
  "kpi.orders.shipment_eligible_count":
    "Orders usable for shipment adherence; shipping-cancelled excluded.",
  "kpi.units.total": "Total units across order-item lines in scope.",
};

export function formatKpiValue(id: string, value: number | string): string {
  if (typeof value === "number") {
    return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
  }
  const numeric = Number(value);
  if (RATE_IDS.has(id)) {
    if (!Number.isFinite(numeric)) {
      return value;
    }
    return `${(numeric * 100).toFixed(1)}%`;
  }
  if (MONEY_IDS.has(id)) {
    if (!Number.isFinite(numeric)) {
      return value;
    }
    return numeric.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  return value;
}
