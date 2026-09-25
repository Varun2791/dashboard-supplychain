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

/** Shared Recharts layout so every breakdown reserves identical geometry. */
export const chartMargins = {
  top: 8,
  right: 8,
  bottom: 8,
  left: 8,
} as const;

/** Axis tick styling: small factual labels, never the only encoding. */
export const chartTickFontSize = 12;

/**
 * Series shape per index for non-color-only distinction (later phases map
 * these to per-series patterns/labels alongside `chartPalette` order).
 */
export function seriesShape(index: number): "solid" | "outlined" | "hatched" {
  const shapes = ["solid", "outlined", "hatched"] as const;
  return shapes[index % shapes.length];
}
