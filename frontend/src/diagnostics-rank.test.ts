import { describe, expect, it } from "vitest";
import type { KpiGroup } from "./lib/ingestion-contracts";
import {
  metricDenominator,
  metricNumber,
  rankGroups,
} from "./lib/diagnostics-rank";

const LATE = "kpi.ship.late_rate";

function group(
  key: string,
  value: string | null,
  denominator: number | null,
  status?: string,
): KpiGroup {
  return {
    key,
    kpis: [
      {
        id: LATE,
        label: "Late-shipment rate",
        value,
        status: status ?? (value === null ? "unavailable" : "ok"),
        numerator: null,
        denominator,
        population: "Eligible test orders.",
        exclusions: "None.",
        reason: value === null ? "empty-eligible-population" : null,
        missingDataCount: 0,
      },
    ],
  };
}

describe("Phase-15B presentation ranking", () => {
  it("sorts backend values descending even when source order differs", () => {
    const groups = [
      group("Gamma", "0.1000", 10),
      group("Alpha", "0.7500", 4),
      group("Beta", "0.5000", 8),
    ];
    expect(rankGroups(groups, LATE).map((entry) => entry.key)).toEqual([
      "Alpha",
      "Beta",
      "Gamma",
    ]);
  });

  it("breaks ties deterministically by group key ascending", () => {
    const groups = [group("Zulu", "0.5", 6), group("Mike", "0.5", 6)];
    expect(rankGroups(groups, LATE).map((entry) => entry.key)).toEqual([
      "Mike",
      "Zulu",
    ]);
  });

  it("places unavailable metrics after available values, never as zero", () => {
    const groups = [
      group("Empty", null, null),
      group("Zero", "0.0000", 5),
      group("High", "0.9000", 5),
    ];
    const ranked = rankGroups(groups, LATE);
    expect(ranked.map((entry) => entry.key)).toEqual(["High", "Zero", "Empty"]);
    // The unavailable group keeps its backend status: sorting never
    // rewrites it to a numeric zero.
    expect(metricNumber(ranked[2], LATE)).toBeNull();
  });

  it("reads denominators from the producer without recomputation", () => {
    const groups = [group("Solo", "0.2500", 12)];
    expect(metricDenominator(groups[0], LATE)).toBe(12);
    expect(metricDenominator(group("Bare", "0.25", null), LATE)).toBeNull();
    expect(metricDenominator(group("Gone", null, null), LATE)).toBeNull();
  });

  it("treats non-numeric backend text as unavailable for ordering", () => {
    const groups = [group("Odd", "not-a-number", 3), group("Fine", "0.1", 3)];
    expect(rankGroups(groups, LATE).map((entry) => entry.key)).toEqual([
      "Fine",
      "Odd",
    ]);
  });
});
