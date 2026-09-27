/**
 * Chart foundation conventions (Phase 10 design system; ADR-022 Recharts).
 *
 * No charts are rendered in Phase 10 — this module fixes the visual
 * conventions later views must follow so breakdowns stay consistent:
 * a restrained sequential palette drawn from the governed `--chart-*`
 * tokens, non-color-only series distinction, and shared layout constants.
 * All plotted values will come from backend endpoint responses.
 */

/** Sequential series palette: `--chart-1` … `--chart-5`, light to dark. */
export const chartPalette: readonly string[] = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

/**
 * Analytical series colors (slice 3, DESIGN.md §9). The primary analytical
 * series is light-blue solid; the secondary/comparison series is a
 * restrained slate-blue, always paired with a dash distinction — never
 * color-alone encoding. No rainbow palette. Semantic loss/error hues are
 * never used for series identity: negative recorded profit is valid data,
 * distinguished by position relative to zero, not by error coloring.
 */
export const chartSeries = {
  primary: "var(--accent-blue)",
  secondary: "var(--chart-secondary)",
} as const;

/** Shared Recharts layout so every breakdown reserves identical geometry. */
export const chartMargins = {
  top: 8,
  right: 8,
  bottom: 8,
  left: 8,
} as const;

/** Axis tick styling: small factual labels, never the only encoding. */
export const chartTickFontSize = 12;

/** Base tick: small muted labels on every axis. */
export const chartTick = {
  fontSize: chartTickFontSize,
  fill: "var(--text-muted)",
} as const;

/**
 * Numeric tick: mono/tabular figures for Y-axis values so magnitudes scan
 * vertically. Category (X-axis) labels stay on the prose face.
 */
export const chartNumericTick = {
  ...chartTick,
  fontFamily: "var(--font-mono)",
} as const;

/** Grid: dashed hairlines on the governed grid token. */
export const chartGridProps = {
  stroke: "var(--chart-grid)",
  strokeDasharray: "3 3",
} as const;

/** Axis lines on the restrained border token; tick marks off. */
export const chartAxisLine = {
  stroke: "var(--border)",
} as const;

/**
 * Dark elevated tooltip (slice 3, DESIGN.md §9): popover surface,
 * restrained border, mono/tabular values. Tooltips annotate; the
 * table-under-chart fallback remains the accessible record.
 */
export const chartTooltipProps = {
  contentStyle: {
    backgroundColor: "var(--popover)",
    border: "1px solid var(--border)",
    borderRadius: "8px",
    fontSize: "12px",
    color: "var(--popover-foreground)",
  },
  labelStyle: {
    color: "var(--popover-foreground)",
    fontWeight: 600,
  },
  itemStyle: {
    fontFamily: "var(--font-mono)",
    color: "var(--popover-foreground)",
  },
} as const;

/** Hover cursor treatments per chart geometry. */
export const chartLineCursor = {
  stroke: "var(--border)",
} as const;

export const chartBarCursor = {
  fill: "var(--chart-grid)",
} as const;

/** Compact legends that wrap on narrow layouts. */
export const chartLegendProps = {
  wrapperStyle: { fontSize: "12px" },
} as const;

/**
 * Recharts JS animation is disabled everywhere. Rationale (slice 3, §10):
 * Recharts animates via requestAnimationFrame, so the CSS
 * `prefers-reduced-motion` foundation does not cover it; animation also
 * replays on every filter-driven data change, briefly interpolating
 * through values the backend never reported. One shared constant keeps
 * the decision in a single place.
 */
export const chartIsAnimationActive = false as const;

/**
 * Series shape per index for non-color-only distinction (later phases map
 * these to per-series patterns/labels alongside `chartPalette` order).
 */
export function seriesShape(index: number): "solid" | "outlined" | "hatched" {
  const shapes = ["solid", "outlined", "hatched"] as const;
  return shapes[index % shapes.length];
}
