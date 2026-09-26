import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  ApiRequestError,
  fetchCleaningReport,
  fetchDataQuality,
  fetchProfile,
  fetchSchemaReport,
} from "@/lib/api";
import type {
  CleaningReportData,
  DataQualityData,
  ProfileData,
  SchemaReportData,
} from "@/lib/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useSession } from "@/lib/session";
import { VIEWS } from "@/lib/view-registry";

interface Reports {
  schema: SchemaReportData;
  profile: ProfileData;
  quality: DataQualityData;
  cleaning: CleaningReportData;
}

interface Failure {
  message: string;
  code: string | null;
  gone: boolean;
}

function isPending(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 409;
}

function toFailure(error: unknown): Failure {
  if (error instanceof ApiRequestError) {
    return {
      message: error.message,
      code: error.code,
      gone: error.status === 404 || error.status === 410,
    };
  }
  return {
    message: "Something went wrong. Please try again.",
    code: null,
    gone: false,
  };
}

function plural(count: number, one: string, many: string): string {
  return count === 1 ? one : many;
}

function ScrollTable({
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

function SchemaCoverage({ schema }: { schema: SchemaReportData }) {
  const required = schema.mapping.filter(
    (entry) => entry.fieldClass === "required",
  );
  const requiredMapped = required.filter(
    (entry) => entry.canonical !== null,
  ).length;
  const optionalMapped = schema.mapping.filter(
    (entry) => entry.fieldClass === "optional" && entry.canonical !== null,
  ).length;
  const redundant = schema.mapping.filter(
    (entry) => entry.fieldClass === "redundant",
  );
  const excluded = schema.mapping.filter(
    (entry) => entry.fieldClass === "excluded",
  );
  const unknown = schema.mapping.filter(
    (entry) => entry.fieldClass === "unknown",
  );
  return (
    <section aria-labelledby="dq-coverage-heading">
      <h3 id="dq-coverage-heading" className="text-base font-semibold">
        Required and optional field coverage
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        {requiredMapped} of {required.length} required fields mapped;{" "}
        {optionalMapped} optional fields mapped.
      </p>
      {schema.missingCritical.length > 0 ? (
        <div
          role="alert"
          className="mt-2 rounded-lg border border-destructive/40 p-3 text-sm"
        >
          <p className="font-medium">
            Missing critical columns gate canonicalization and KPI analysis.
          </p>
          <ul className="mt-1 list-disc pl-5">
            {schema.missingCritical.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
          <p className="mt-1 text-muted-foreground">
            Gated stages stay gated until the input is fixed or replaced. There
            is no override.
          </p>
        </div>
      ) : (
        <p className="mt-1 text-sm text-muted-foreground">
          No critical columns are missing.
        </p>
      )}
      <div className="mt-3 flex flex-col gap-2 text-sm">
        <details className="rounded-lg border px-3 py-2">
          <summary className="cursor-pointer font-medium">
            Excluded columns ({excluded.length}): privacy and governed
            exclusions
          </summary>
          <p className="mt-1 text-muted-foreground">
            Excluded columns never enter canonical outputs, API payloads, or
            exports. Direct personal fields stay out by construction.
          </p>
          {excluded.length > 0 ? (
            <ul className="mt-1 list-disc pl-5">
              {excluded.map((entry) => (
                <li key={entry.source}>{entry.source}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-muted-foreground">
              No columns were excluded.
            </p>
          )}
        </details>
        <details className="rounded-lg border px-3 py-2">
          <summary className="cursor-pointer font-medium">
            Redundant copies ({redundant.length}): recognized, never mapped
          </summary>
          <p className="mt-1 text-muted-foreground">
            Redundant copies stay in the raw file only; canonical fields never
            read them.
          </p>
          {redundant.length > 0 ? (
            <ul className="mt-1 list-disc pl-5">
              {redundant.map((entry) => (
                <li key={entry.source}>{entry.source}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-muted-foreground">
              No redundant copies were found.
            </p>
          )}
        </details>
        <details className="rounded-lg border px-3 py-2">
          <summary className="cursor-pointer font-medium">
            Unknown columns ({unknown.length}): quarantined
          </summary>
          <p className="mt-1 text-muted-foreground">
            Unknown columns are retained in the raw file only and never mapped
            to canonical fields.
          </p>
          {unknown.length > 0 ? (
            <ul className="mt-1 list-disc pl-5">
              {unknown.map((entry) => (
                <li key={entry.source}>{entry.source}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-muted-foreground">
              No unknown columns were found.
            </p>
          )}
        </details>
      </div>
    </section>
  );
}

function SourceProfile({ profile }: { profile: ProfileData }) {
  return (
    <section aria-labelledby="dq-profile-heading">
      <h3 id="dq-profile-heading" className="text-base font-semibold">
        Source dimensions and grain
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        {profile.rows} order-item {plural(profile.rows, "line", "lines")}{" "}
        assessed across {profile.columns} mapped{" "}
        {plural(profile.columns, "field", "fields")}. Grain: {profile.grain}.
      </p>
      <ul className="mt-2 list-disc pl-5 text-sm">
        <li>
          Exact duplicate rows beyond first occurrence:{" "}
          {profile.duplicates.exact}
        </li>
        <li>
          Rows sharing a duplicate Order Item Id: {profile.duplicates.keyDupes}
        </li>
        <li>
          Orders checked for invariance:{" "}
          {profile.invarianceConflicts.ordersChecked}; conflicting orders:{" "}
          {profile.invarianceConflicts.conflictingOrders}
        </li>
        <li>
          Product keys checked: {profile.productInvarianceConflicts.keysChecked}
          ; conflicting keys:{" "}
          {profile.productInvarianceConflicts.conflictingKeys}
        </li>
        <li>
          Customer keys checked:{" "}
          {profile.customerInvarianceConflicts.keysChecked}; conflicting keys:{" "}
          {profile.customerInvarianceConflicts.conflictingKeys}
        </li>
      </ul>
      {profile.invarianceConflicts.byField.length > 0 ? (
        <div className="mt-3">
          <h4 className="text-sm font-medium">
            Order-invariance conflicts by field
          </h4>
          <div className="mt-1">
            <ScrollTable label="Order-invariance conflicts by field">
              <thead>
                <tr className="border-b text-left">
                  <th scope="col" className="px-3 py-2 font-medium">
                    Field
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Conflicting orders (count)
                  </th>
                </tr>
              </thead>
              <tbody>
                {profile.invarianceConflicts.byField.map((entry) => (
                  <tr key={entry.field} className="border-b last:border-0">
                    <td className="px-3 py-2">{entry.field}</td>
                    <td className="px-3 py-2">{entry.conflictingOrders}</td>
                  </tr>
                ))}
              </tbody>
            </ScrollTable>
          </div>
        </div>
      ) : null}
      <div className="mt-3">
        <h4 className="text-sm font-medium">Field-level missingness</h4>
        {profile.missingness.length > 0 ? (
          <div className="mt-1">
            <ScrollTable label="Field-level missingness">
              <thead>
                <tr className="border-b text-left">
                  <th scope="col" className="px-3 py-2 font-medium">
                    Field
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Source column
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Missing (count)
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Of total (count)
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Parse failures (count)
                  </th>
                </tr>
              </thead>
              <tbody>
                {profile.missingness.map((entry) => (
                  <tr key={entry.field} className="border-b last:border-0">
                    <td className="px-3 py-2">{entry.field}</td>
                    <td className="px-3 py-2">{entry.source}</td>
                    <td className="px-3 py-2">{entry.missing}</td>
                    <td className="px-3 py-2">{entry.total}</td>
                    <td className="px-3 py-2">{entry.parseFailures}</td>
                  </tr>
                ))}
              </tbody>
            </ScrollTable>
          </div>
        ) : (
          <p className="mt-1 text-sm text-muted-foreground">
            No missingness was recorded.
          </p>
        )}
      </div>
      <div className="mt-3">
        <h4 className="text-sm font-medium">Field-level cardinality</h4>
        {profile.cardinality.length > 0 ? (
          <div className="mt-1">
            <ScrollTable label="Field-level cardinality">
              <thead>
                <tr className="border-b text-left">
                  <th scope="col" className="px-3 py-2 font-medium">
                    Field
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Source column
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Distinct values (count)
                  </th>
                </tr>
              </thead>
              <tbody>
                {profile.cardinality.map((entry) => (
                  <tr key={entry.field} className="border-b last:border-0">
                    <td className="px-3 py-2">{entry.field}</td>
                    <td className="px-3 py-2">{entry.source}</td>
                    <td className="px-3 py-2">{entry.distinct}</td>
                  </tr>
                ))}
              </tbody>
            </ScrollTable>
          </div>
        ) : (
          <p className="mt-1 text-sm text-muted-foreground">
            No cardinality was recorded.
          </p>
        )}
      </div>
    </section>
  );
}

const SEVERITIES = ["ERROR", "WARNING", "INFO"] as const;

function IssuesBySeverity({ quality }: { quality: DataQualityData }) {
  const { summary } = quality;
  return (
    <section aria-labelledby="dq-issues-heading">
      <h3 id="dq-issues-heading" className="text-base font-semibold">
        Issues by severity and treatment
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        {summary.rulesTriggered} of {summary.rulesEvaluated} rules triggered:{" "}
        {summary.errors} {plural(summary.errors, "error", "errors")},{" "}
        {summary.warnings} {plural(summary.warnings, "warning", "warnings")},{" "}
        {summary.infos} informational {plural(summary.infos, "note", "notes")}.
      </p>
      {summary.blockingIssues > 0 ? (
        <p className="mt-1 text-sm text-muted-foreground">
          {summary.blockingIssues}{" "}
          {plural(summary.blockingIssues, "issue gates", "issues gate")} a
          downstream stage (see Blocked stage). Gated stages stay gated until
          the input is fixed or replaced; there is no override.
        </p>
      ) : (
        <p className="mt-1 text-sm text-muted-foreground">
          No issue gates a downstream stage.
        </p>
      )}
      {SEVERITIES.map((severity) => {
        const issues = quality.issues.filter(
          (issue) => issue.severity === severity,
        );
        return (
          <div key={severity} className="mt-3">
            <h4 className="text-sm font-medium">
              {severity} ({issues.length})
            </h4>
            {issues.length > 0 ? (
              <div className="mt-1">
                <ScrollTable label={`${severity} data-quality issues`}>
                  <thead>
                    <tr className="border-b text-left">
                      <th scope="col" className="px-3 py-2 font-medium">
                        Rule ID
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Affected (count)
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Treatment
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Blocked stage
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {issues.map((issue) => (
                      <tr key={issue.ruleId} className="border-b last:border-0">
                        <td className="px-3 py-2 font-mono text-[13px]">
                          {issue.ruleId}
                        </td>
                        <td className="px-3 py-2">{issue.count}</td>
                        <td className="px-3 py-2">{issue.treatment}</td>
                        <td className="px-3 py-2">
                          {issue.blockedStage === null ? (
                            <span className="text-muted-foreground">
                              None — recorded only
                            </span>
                          ) : (
                            <>
                              {issue.blockedStage}{" "}
                              <span className="text-muted-foreground">
                                (gates work; recoverable, not terminal)
                              </span>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </ScrollTable>
              </div>
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">
                No {severity} issues.
              </p>
            )}
          </div>
        );
      })}
    </section>
  );
}

function CleaningAudit({ cleaning }: { cleaning: CleaningReportData }) {
  const totals = cleaning.steps.reduce(
    (acc, step) => ({
      detected: acc.detected + step.detected,
      fixed: acc.fixed + step.fixed,
      flagged: acc.flagged + step.flagged,
      excluded: acc.excluded + step.excluded,
      unchanged: acc.unchanged + step.unchanged,
    }),
    { detected: 0, fixed: 0, flagged: 0, excluded: 0, unchanged: 0 },
  );
  return (
    <section aria-labelledby="dq-cleaning-heading">
      <h3 id="dq-cleaning-heading" className="text-base font-semibold">
        Cleaning audit log
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Totals below are presentational sums of the audited steps:{" "}
        {totals.detected} detected — {totals.fixed} fixed, {totals.flagged}{" "}
        flagged, {totals.excluded} excluded, {totals.unchanged} unchanged.
        Detected is not the same as fixed.
      </p>
      {cleaning.steps.length > 0 ? (
        <div className="mt-2">
          <ScrollTable label="Cleaning audit log">
            <thead>
              <tr className="border-b text-left">
                <th scope="col" className="px-3 py-2 font-medium">
                  Rule ID
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Field
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Detected (count)
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Fixed (count)
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Flagged (count)
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Excluded (count)
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Unchanged (count)
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Reason
                </th>
              </tr>
            </thead>
            <tbody>
              {cleaning.steps.map((step) => (
                <tr
                  key={`${step.ruleId}:${step.field}`}
                  className="border-b last:border-0"
                >
                  <td className="px-3 py-2 font-mono text-[13px]">
                    {step.ruleId}
                  </td>
                  <td className="px-3 py-2">
                    {step.field === "" ? (
                      <span className="text-muted-foreground">—</span>
                    ) : (
                      step.field
                    )}
                  </td>
                  <td className="px-3 py-2">{step.detected}</td>
                  <td className="px-3 py-2">{step.fixed}</td>
                  <td className="px-3 py-2">{step.flagged}</td>
                  <td className="px-3 py-2">{step.excluded}</td>
                  <td className="px-3 py-2">{step.unchanged}</td>
                  <td className="px-3 py-2">{step.reason}</td>
                </tr>
              ))}
            </tbody>
          </ScrollTable>
        </div>
      ) : (
        <p className="mt-1 text-sm text-muted-foreground">
          No cleaning steps were recorded.
        </p>
      )}
    </section>
  );
}

/**
 * Phase-11 Data Quality view: profile, schema coverage, issues by
 * severity/treatment, and the cleaning audit log for the active session.
 * Renders backend-provided counts only; it recomputes no rule logic.
 */
export default function DataQualityView() {
  const { session, sessionState } = useSession();
  // Cache is keyed by session id: reset (session null) or terminal FAILED
  // hides it through the render guard below, never through synchronous
  // state writes. Reports are immutable per session, so a loaded report is
  // never refetched; hard errors retry when the session state advances.
  const [cache, setCache] = useState<{
    sessionId: string;
    reports: Reports | null;
    failure: Failure | null;
    failedAtState: string | null;
  } | null>(null);

  const sessionId = session?.sessionId ?? null;
  const terminal = sessionState === "FAILED";
  const visible =
    cache !== null && cache.sessionId === sessionId && !terminal ? cache : null;
  const reports = visible?.reports ?? null;
  const failure = visible?.failure ?? null;

  // Contract-driven fetching: the reports themselves are the authority on
  // readiness (200 ready, 409 NOT_READY pending). Stale responses are
  // ignored via the effect guard so an old session can never overwrite a
  // new one.
  useEffect(() => {
    if (sessionId === null || terminal) {
      return;
    }
    if (cache?.sessionId === sessionId && cache.reports !== null) {
      return;
    }
    if (
      cache?.sessionId === sessionId &&
      cache.failure !== null &&
      cache.failedAtState === sessionState
    ) {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const [schema, profile, quality, cleaning] = await Promise.all([
          fetchSchemaReport(sessionId),
          fetchProfile(sessionId),
          fetchDataQuality(sessionId),
          fetchCleaningReport(sessionId),
        ]);
        if (cancelled) {
          return;
        }
        setCache({
          sessionId,
          reports: { schema, profile, quality, cleaning },
          failure: null,
          failedAtState: null,
        });
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (isPending(error)) {
          // A stage has not completed yet; the next session-state advance
          // retries automatically.
          return;
        }
        setCache({
          sessionId,
          reports: null,
          failure: toFailure(error),
          failedAtState: sessionState,
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, terminal, sessionState, cache]);

  const meta = VIEWS.find((entry) => entry.id === "data-quality");

  if (session === null) {
    return (
      <section aria-labelledby="data-quality-heading">
        <h2
          id="data-quality-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Data Quality
        </h2>
        {meta !== undefined ? (
          <p className="mt-1 text-sm text-muted-foreground">{meta.question}</p>
        ) : null}
        <div className="mt-4">
          <EmptyState
            title="No dataset loaded"
            body="Upload a CSV on the Upload view first. The data-quality report appears here once the session has a report to show."
          />
        </div>
      </section>
    );
  }

  if (terminal) {
    return (
      <section aria-labelledby="data-quality-heading">
        <h2
          id="data-quality-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Data Quality
        </h2>
        <div className="mt-4">
          <ErrorState
            title="This session ended in FAILED"
            message="The session failed before reports could complete, so there is no data-quality report to show. This is a terminal session state, not a gated stage."
            guidance="Open the Upload view for the failing stage, code, and next steps — or remove the session and upload a fixed file."
          />
        </div>
      </section>
    );
  }

  if (failure !== null) {
    return (
      <section aria-labelledby="data-quality-heading">
        <h2
          id="data-quality-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Data Quality
        </h2>
        <div className="mt-4">
          <ErrorState
            title="The data-quality report could not be loaded"
            message={failure.message}
            guidance={[
              failure.code !== null ? `Code: ${failure.code}.` : null,
              failure.gone
                ? "This session is gone from the server. Upload the file again to start a new session."
                : "No report data is shown; nothing stale is displayed.",
            ]
              .filter((part) => part !== null)
              .join(" ")}
          />
        </div>
      </section>
    );
  }

  if (reports === null) {
    return (
      <section aria-labelledby="data-quality-heading">
        <h2
          id="data-quality-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Data Quality
        </h2>
        <div className="mt-4 flex flex-col gap-2">
          <LoadingState label="Loading the data-quality report…" />
          <p className="text-sm text-muted-foreground">
            Session {session.sessionId.slice(0, 8)} is{" "}
            {sessionState ?? "starting"}. Reports appear automatically when each
            stage completes; waiting for the next stage now.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section
      aria-labelledby="data-quality-heading"
      className="flex w-full flex-col gap-6"
    >
      <div>
        <h2
          id="data-quality-heading"
          className="text-xl font-semibold tracking-tight"
        >
          Data Quality
        </h2>
        {meta !== undefined ? (
          <p className="mt-1 text-sm text-muted-foreground">{meta.question}</p>
        ) : null}
        <p className="mt-1 text-sm text-muted-foreground" role="status">
          Session {session.sessionId.slice(0, 8)} · {sessionState ?? "starting"}
        </p>
      </div>
      <SourceProfile profile={reports.profile} />
      <SchemaCoverage schema={reports.schema} />
      <IssuesBySeverity quality={reports.quality} />
      <CleaningAudit cleaning={reports.cleaning} />
      <section aria-labelledby="dq-export-heading">
        <h3 id="dq-export-heading" className="text-base font-semibold">
          Exports
        </h3>
        <div className="mt-2">
          <EmptyState
            title="Exports arrive in Phase 16"
            body="Approved kinds for this evidence are the data-quality report, the cleaning report, and the sanitized cleaned items. Raw data is never exportable."
          />
        </div>
      </section>
    </section>
  );
}
