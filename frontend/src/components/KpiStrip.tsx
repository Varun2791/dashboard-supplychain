import type { KpiResult } from "@/lib/api";
import { CARD_MEANINGS, formatKpiValue } from "@/lib/kpi-format";

/**
 * Thin shared KPI visual primitive (analytical slice 2, DESIGN.md §8).
 *
 * Presentation only: layout, typography, surface treatment, unavailable
 * presentation, and the consolidated definitions disclosure live here. This
 * module owns no KPI selection, business rules, API requests, filtering, or
 * arithmetic — views select backend-computed `KpiResult` rows by ID and pass
 * them in. Values render with the backend-owned `formatKpiValue` display
 * formatter; unavailable stays unavailable with its backend reason; negative
 * recorded profit is valid data and receives no error treatment.
 */
function missingNote(kpi: KpiResult): string | null {
  return kpi.missingDataCount > 0
    ? `${kpi.missingDataCount} rows excluded for missing fields`
    : null;
}

function KpiStripItem({ kpi }: { kpi: KpiResult }) {
  const unavailable = kpi.status !== "ok" || kpi.value === null;
  const note = missingNote(kpi);
  return (
    <div className="flex min-w-0 flex-col gap-0.5 px-3 py-2">
      {/* Governed KPI labels keep normal case and wrap (DESIGN.md §8):
          never uppercase, never truncate; break-words contains unbroken
          strings without ellipsis. */}
      <p className="text-[12px] font-medium break-words text-muted-foreground">
        {kpi.label}
      </p>
      {unavailable || kpi.value === null ? (
        <p
          className="font-analytical text-sm text-muted-foreground tabular-nums"
          role="status"
        >
          Unavailable
          {kpi.reason !== null && kpi.reason !== "" ? ` — ${kpi.reason}` : ""}
          {note !== null ? ` (${note})` : ""}
        </p>
      ) : (
        <p className="font-analytical text-lg leading-snug font-semibold tracking-tight tabular-nums">
          {formatKpiValue(kpi.id, kpi.value)}
        </p>
      )}
      {!unavailable && note !== null ? (
        <p className="text-[11px] text-muted-foreground">({note})</p>
      ) : null}
      {/* Governed population strings wrap like labels: never truncate. */}
      <p className="text-[11px] break-words text-muted-foreground">
        {kpi.population}
      </p>
    </div>
  );
}

/**
 * One analytical unit: the KPI collection reads as a single bordered strip
 * with internal dividers rather than unrelated floating cards. Available and
 * unavailable items share geometry so status changes cause no layout shift.
 *
 * Dividers are a 1px grid gap painted by the container background, so cell
 * joints render one hairline at every column count — never the doubled seams
 * `divide-x` + `divide-y` draws where cells meet. The outer edge is the
 * shared structural strip frame; cells carry the card surface.
 */
export function KpiStrip({
  kpis,
  label,
}: {
  kpis: KpiResult[];
  label: string;
}) {
  return (
    <div
      role="list"
      aria-label={label}
      className="strip-frame grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-3 lg:grid-cols-4"
    >
      {kpis.map((kpi) => (
        <div key={kpi.id} role="listitem" className="min-w-0 bg-card">
          <KpiStripItem kpi={kpi} />
        </div>
      ))}
    </div>
  );
}

/**
 * One accessible "Definitions & populations" disclosure per KPI collection.
 * Every explanatory string is preserved: the backend verbatim
 * population/exclusions plus the contract-traceable short meaning. Native
 * details/summary keeps keyboard access with no tooltip dependency.
 */
export function KpiStripDefinitions({
  kpis,
  summary,
}: {
  kpis: KpiResult[];
  summary: string;
}) {
  return (
    <details className="mt-3 border-t border-border pt-2 text-sm">
      <summary className="cursor-pointer font-medium text-muted-foreground">
        {summary}
      </summary>
      <dl className="mt-2 flex flex-col gap-3">
        {kpis.map((kpi) => (
          <div key={kpi.id}>
            <dt className="font-medium">{kpi.label}</dt>
            <dd className="mt-0.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
              <span className="text-muted-foreground">Meaning</span>
              <span>{CARD_MEANINGS[kpi.id] ?? "Governed headline KPI."}</span>
              <span className="text-muted-foreground">Population</span>
              <span>{kpi.population}</span>
              <span className="text-muted-foreground">Exclusions</span>
              <span>{kpi.exclusions}</span>
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
