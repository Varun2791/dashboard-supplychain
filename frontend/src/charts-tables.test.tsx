/// <reference types="node" />
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnalyticalTable, ScrollTable } from "./components/AnalyticalTable";
import {
  chartBarProps,
  chartGridProps,
  chartIsAnimationActive,
  chartLegendProps,
  chartSeries,
  chartTooltipProps,
  chartXAxisProps,
} from "./lib/chart-theme";

const frontendRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const css = readFileSync(join(frontendRoot, "src/index.css"), "utf8");

function sourceOf(relative: string): string {
  return readFileSync(join(frontendRoot, relative), "utf8");
}

describe("slice C: shared chart presentation owns quiet analytics", () => {
  it("keeps Recharts animation disabled everywhere", () => {
    expect(chartIsAnimationActive).toBe(false);
  });

  it("keeps the grid subordinate: horizontal-only dashed hairlines", () => {
    expect(chartGridProps.vertical).toBe(false);
    expect(chartGridProps.stroke).toBe("var(--chart-grid)");
    expect(chartGridProps.strokeDasharray).toBe("3 3");
  });

  it("keeps the tooltip a restrained technical readout", () => {
    const content = chartTooltipProps.contentStyle as Record<string, string>;
    expect(content["border"]).toBe("1px solid var(--border-strong)");
    expect(content["borderRadius"]).toBe("6px");
    expect(content["backgroundColor"]).toBe("var(--popover)");
    const item = chartTooltipProps.itemStyle as Record<string, string>;
    expect(item["fontFamily"]).toBe("var(--font-mono)");
  });

  it("keeps analytical color semantics: blue emphasis, slate comparison", () => {
    expect(chartSeries.primary).toBe("var(--accent-blue)");
    expect(chartSeries.secondary).toBe("var(--chart-secondary)");
  });

  it("caps bar marks and shares the crowded-axis label policy", () => {
    expect(chartBarProps.maxBarSize).toBeGreaterThan(0);
    expect(chartXAxisProps.interval).toBe("preserveStartEnd");
  });

  it("keeps legends compact for the multi-series trend only", () => {
    expect(
      (chartLegendProps.wrapperStyle as Record<string, string>)["fontSize"],
    ).toBe("12px");
    // Single-series bar charts carry no legend chrome; the two-series
    // trend chart keeps its disambiguating legend.
    expect(sourceOf("src/components/DeliveryView.tsx")).not.toContain("Legend");
    expect(sourceOf("src/components/CommercialView.tsx")).not.toContain(
      "Legend",
    );
    expect(sourceOf("src/components/OverviewView.tsx")).toContain("<Legend");
  });
});

describe("slice C: thin table-shell contract", () => {
  it("draws the header rule on the structural edge token", () => {
    expect(css).toMatch(
      /\.analytical-table th\s*{[^}]*border-bottom:\s*2px solid var\(--border-strong\)/,
    );
  });

  it("right-aligns non-first columns as mono/tabular numerics", () => {
    expect(css).toContain(".analytical-table td:not(:first-child)");
    expect(css).toMatch(
      /\.analytical-table td:not\(:first-child\)[\s\S]*?font-variant-numeric:\s*tabular-nums/,
    );
  });

  it("keeps sticky strictly opt-in and enabled nowhere by default", () => {
    expect(css).toContain(".analytical-table--sticky-head");
    expect(css).toContain(".analytical-table--sticky-first-col");
    // The base header rule carries no positioning: sticky appears only
    // under the opt-in modifiers above.
    const baseHeader = css.match(/\.analytical-table th\s*{[^}]*}/);
    expect(baseHeader).not.toBeNull();
    expect(baseHeader?.[0]).not.toContain("sticky");
  });

  it("renders the analytical shell as a labelled table in its own scroll region", () => {
    render(
      <AnalyticalTable label="Slice C probe table">
        <thead>
          <tr>
            <th scope="col">Dimension</th>
            <th scope="col">Net value</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>East</td>
            <td>12.50</td>
          </tr>
        </tbody>
      </AnalyticalTable>,
    );
    const table = screen.getByRole("table", { name: "Slice C probe table" });
    expect(table).toBeInTheDocument();
    expect(withinScrollRegion(table as HTMLElement)).not.toBeNull();
    expect(
      screen.getByRole("columnheader", { name: "Dimension" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Net value" }),
    ).toBeInTheDocument();
  });

  it("shares one neutral scroll wrapper instead of duplicated locals", () => {
    // Both mixed-text tables import the shared wrapper; neither defines
    // its own, so DQ restyling (Slice D) has a single place to evolve.
    for (const view of [
      "src/components/DataQualityView.tsx",
      "src/components/DiagnosticsView.tsx",
    ]) {
      const source = sourceOf(view);
      expect(source).toContain("ScrollTable");
      expect(source).not.toContain("function ScrollTable");
      expect(source).toMatch(/from "@\/components\/AnalyticalTable"/);
    }
    render(
      <ScrollTable label="Slice C scroll probe">
        <tbody>
          <tr>
            <td>text stays left-owned by the view</td>
          </tr>
        </tbody>
      </ScrollTable>,
    );
    const table = screen.getByRole("table", { name: "Slice C scroll probe" });
    expect(table).toBeInTheDocument();
    expect(withinScrollRegion(table as HTMLElement)).not.toBeNull();
  });
});

function withinScrollRegion(element: HTMLElement): HTMLElement | null {
  let node: HTMLElement | null = element.parentElement;
  while (node !== null) {
    if (node.classList.contains("overflow-x-auto")) {
      return node;
    }
    node = node.parentElement;
  }
  return null;
}
