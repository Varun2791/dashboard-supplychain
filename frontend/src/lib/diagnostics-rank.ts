import type { KpiGroup, KpiResult } from "@/lib/api";

export function findKpi(kpis: KpiResult[], id: string): KpiResult | null {
  return kpis.find((kpi) => kpi.id === id) ?? null;
}

/**
 * Numeric backend metric value for presentation ordering only. Returns null
 * for unavailable metrics (missing entry, non-ok status, null value, or
 * non-numeric text). This parses a display value for sorting — it derives
 * no rate, share, margin, or population.
 */
export function metricNumber(group: KpiGroup, metricId: string): number | null {
  const kpi = findKpi(group.kpis, metricId);
  if (kpi === null || kpi.status !== "ok" || kpi.value === null) {
    return null;
  }
  const numeric = typeof kpi.value === "number" ? kpi.value : Number(kpi.value);
  return Number.isFinite(numeric) ? numeric : null;
}

/**
 * Backend-provided denominator for one group (never computed). Rates carry
 * their eligible/order population here; a non-numeric denominator means the
 * producer did not supply a population for this group.
 */
export function metricDenominator(
  group: KpiGroup,
  metricId: string,
): number | null {
  const kpi = findKpi(group.kpis, metricId);
  if (kpi === null || kpi.status !== "ok") {
    return null;
  }
  return typeof kpi.denominator === "number" ? kpi.denominator : null;
}

/**
 * Presentation-only stable ordering for the two governed diagnostic
 * rankings (ADR-039): available metric values first in descending order,
 * deterministic group-key ascending tie-break, unavailable metrics after
 * available values (never ranked as zero). No KPI recomputation, no
 * thresholds, no best/worst classification.
 */
export function rankGroups(groups: KpiGroup[], metricId: string): KpiGroup[] {
  const available: Array<{ group: KpiGroup; value: number }> = [];
  const unavailable: KpiGroup[] = [];
  for (const group of groups) {
    const value = metricNumber(group, metricId);
    if (value === null) {
      unavailable.push(group);
    } else {
      available.push({ group, value });
    }
  }
  available.sort((left, right) => {
    if (right.value !== left.value) {
      return right.value - left.value;
    }
    if (left.group.key === right.group.key) {
      return 0;
    }
    return left.group.key < right.group.key ? -1 : 1;
  });
  unavailable.sort((left, right) => {
    if (left.key === right.key) {
      return 0;
    }
    return left.key < right.key ? -1 : 1;
  });
  return [...available.map((entry) => entry.group), ...unavailable];
}
