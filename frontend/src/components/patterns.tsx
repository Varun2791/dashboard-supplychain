/**
 * Accessible filter and KPI-definition patterns (Phase 10 design system).
 *
 * Presentational only: these components collect user intent and disclose
 * governed definitions. They perform no fetching, no filtering, and no KPI
 * mathematics — later phases wire `onChange` to the backend API.
 */

export interface FilterOption {
  value: string;
  label: string;
}

interface FilterSelectProps {
  id: string;
  label: string;
  options: FilterOption[];
  value: string | null;
  onChange: (value: string | null) => void;
  disabled?: boolean;
}

/** Labeled single-value filter with an explicit clear action. */
export function FilterSelect({
  id,
  label,
  options,
  value,
  onChange,
  disabled = false,
}: FilterSelectProps) {
  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="flex flex-col gap-1">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <select
          id={id}
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={value ?? ""}
          disabled={disabled}
          onChange={(event) => {
            const next = event.target.value;
            onChange(next === "" ? null : next);
          }}
        >
          <option value="">All</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      {value !== null && value !== "" ? (
        <button
          type="button"
          className="rounded-md border px-2 py-1 text-sm"
          disabled={disabled}
          onClick={() => onChange(null)}
          aria-label={`Clear ${label} filter`}
        >
          Clear
        </button>
      ) : null}
    </div>
  );
}

interface KpiDefinitionProps {
  term: string;
  meaning: string;
  population: string;
  exclusions: string;
}

/**
 * Governed KPI-definition disclosure. All copy arrives as props from the
 * backend-approved contract — this component never defines a KPI itself.
 * Native disclosure semantics give keyboard support without extra ARIA.
 */
export function KpiDefinition({
  term,
  meaning,
  population,
  exclusions,
}: KpiDefinitionProps) {
  return (
    <details className="rounded-lg border px-3 py-2 text-sm">
      <summary className="cursor-pointer font-medium">
        What does “{term}” mean?
      </summary>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-muted-foreground">Meaning</dt>
        <dd>{meaning}</dd>
        <dt className="text-muted-foreground">Population</dt>
        <dd>{population}</dd>
        <dt className="text-muted-foreground">Exclusions</dt>
        <dd>{exclusions}</dd>
      </dl>
    </details>
  );
}
