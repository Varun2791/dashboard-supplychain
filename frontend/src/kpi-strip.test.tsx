import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KpiStrip, KpiStripDefinitions } from "./components/KpiStrip";
import type { KpiResult } from "./lib/api";

function kpi(overrides: Partial<KpiResult> & { id: string }): KpiResult {
  return {
    label: overrides.id,
    value: 10,
    status: "ok",
    numerator: 10,
    denominator: null,
    population: "Population.",
    exclusions: "Exclusions.",
    reason: null,
    missingDataCount: 0,
    ...overrides,
  };
}

const KPIS: KpiResult[] = [
  kpi({
    id: "kpi.value.net",
    label: "Recorded net order value",
    value: "1234.56",
    population: "2 order-item lines, all-status scope",
    exclusions: "None.",
  }),
  kpi({
    id: "kpi.profit.recorded",
    label: "Recorded profit",
    value: "-45.67",
    population: "2 order-item lines; negatives retained",
    exclusions: "None.",
  }),
  kpi({
    id: "kpi.margin.profit",
    label: "Profit margin",
    value: null,
    status: "unavailable",
    reason: "empty-eligible-population",
    population: "0 lines with recorded profit and net",
    exclusions: "None.",
  }),
];

describe("Slice B: KPI strip presentation contract", () => {
  it("renders one shared strip with list semantics, not floating cards", () => {
    const { container } = render(
      <KpiStrip kpis={KPIS} label="Headline results" />,
    );
    const list = screen.getByRole("list", { name: "Headline results" });
    expect(list).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    // Single shared structural frame + single-edge dividers: no per-item
    // divide utilities that double-draw joints.
    expect(list.className).not.toMatch(/divide-x|divide-y/);
    expect(container.innerHTML).not.toContain("divide-x");
  });

  it("keeps governed labels and populations verbatim: normal case, wrapping", () => {
    render(<KpiStrip kpis={KPIS} label="Headline results" />);
    const label = screen.getByText("Recorded net order value");
    expect(label.textContent).toBe("Recorded net order value");
    expect(label.className).not.toMatch(/uppercase|truncate/);
    const population = screen.getByText("2 order-item lines, all-status scope");
    expect(population.className).not.toMatch(/uppercase|truncate/);
  });

  it("keeps unavailable visibly unavailable, never zero", () => {
    render(<KpiStrip kpis={KPIS} label="Headline results" />);
    const status = screen.getByText(/Unavailable/);
    expect(status).toHaveTextContent("empty-eligible-population");
    expect(status.textContent).not.toMatch(/^0(\.0+)?%?$/);
  });

  it("renders negative recorded profit as ordinary data, not an error", () => {
    render(<KpiStrip kpis={KPIS} label="Headline results" />);
    const negative = screen.getByText("-45.67");
    expect(negative).toBeInTheDocument();
    expect(negative.className).not.toMatch(
      /destructive|status-error|text-red|error/,
    );
  });

  it("keeps one native definitions disclosure with governed detail", () => {
    render(
      <KpiStripDefinitions
        kpis={KPIS}
        summary="Definitions & populations for these headline results"
      />,
    );
    const disclosure = document.querySelector("details");
    expect(disclosure).not.toBeNull();
    const summary = screen.getByText(
      "Definitions & populations for these headline results",
    );
    expect(summary.tagName).toBe("SUMMARY");
    expect(
      screen.getByText("2 order-item lines, all-status scope"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("None.").length).toBeGreaterThan(0);
  });
});
