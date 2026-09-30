import type { ReactNode } from "react";

/**
 * Thin shared analytical table shell (slice 3, DESIGN.md §10).
 *
 * Presentation only: overflow container, surface, header/row/numeric
 * styling hooks. It owns no column definitions, data mapping, sorting,
 * pagination, filtering, formatting, ranking, API calls, or view semantics
 * — views render their own thead/tbody. Numeric alignment is structural:
 * every migrated grouped table leads with its dimension label, so all
 * non-first columns right-align as mono/tabular numerics via CSS.
 */
export function AnalyticalTable({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="analytical-table overflow-x-auto rounded-lg border bg-card">
      <table aria-label={label} className="w-full text-sm">
        {children}
      </table>
    </div>
  );
}

/**
 * Plain internal-scroll wrapper (Slice C thin-shell consolidation,
 * DESIGN.md §10). For tables whose non-first columns are NOT all numeric
 * (mixed text columns such as DQ field tables or the order drilldown),
 * the AnalyticalTable numeric-alignment rule would misalign text — those
 * tables keep this neutral wrapper and own their own cell alignment.
 * It owns no columns, sorting, or semantics either; it only guarantees
 * the table scrolls inside its owned region instead of overflowing the
 * page. Views render their own thead/tbody.
 */
export function ScrollTable({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table aria-label={label} className="w-full text-sm">
        {children}
      </table>
    </div>
  );
}
