import { useState } from "react";
import { useSession } from "@/lib/session";
import { AnalyticsFilterProvider } from "@/lib/analytics-filters";
import { ActiveView } from "@/components/views";
import { VIEWS } from "@/lib/view-registry";
import type { DashboardView } from "@/lib/view-registry";
import type { SessionSnapshot } from "@/lib/session";

/**
 * Presentation-only tone for the session marker. State names, lifecycle
 * semantics, and reset behavior are unchanged; color never replaces text.
 */
function sessionTone(state: string | null): string {
  if (state === "READY") return "ok";
  if (state === "FAILED" || state === "EXPIRED") return "error";
  return "pending";
}

function SessionBadge() {
  const { session, sessionState } = useSession();
  if (session === null) {
    return (
      <p
        role="status"
        className="font-analytical flex items-center gap-2 text-xs text-muted-foreground"
      >
        <span aria-hidden="true" className="session-dot" data-tone="idle" />
        No session
      </p>
    );
  }
  return (
    <p
      role="status"
      className="font-analytical flex items-center gap-2 text-xs text-muted-foreground"
    >
      <span
        aria-hidden="true"
        className="session-dot"
        data-tone={sessionTone(sessionState)}
      />
      Session {session.sessionId.slice(0, 8)} · {sessionState ?? "starting"}
    </p>
  );
}

/**
 * Phase-10 application shell: header with global session context,
 * keyboard-operable view navigation, and a responsive content region.
 * Views own their data; the shell never fetches or computes analytics.
 */
export default function AppShell({
  onSessionChange,
}: {
  onSessionChange: (snapshot: SessionSnapshot) => void;
}) {
  const [view, setView] = useState<DashboardView>("upload");
  return (
    <div className="bg-background text-foreground flex min-h-svh flex-col">
      <header className="bg-card border-b border-border">
        <div className="mx-auto flex w-full max-w-[80rem] flex-wrap items-center justify-between gap-2 px-4 py-3 sm:px-6">
          <div>
            <h1 className="text-base font-semibold tracking-tight">
              Supply Chain Analytics Dashboard
            </h1>
            <p className="font-analytical text-analytical-muted text-[11px]">
              Local-first · nothing leaves this machine
            </p>
          </div>
          <SessionBadge />
        </div>
        <nav
          aria-label="Dashboard views"
          className="mx-auto w-full max-w-[80rem] overflow-x-auto px-4 sm:px-6"
        >
          <ul className="flex gap-1 py-2">
            {VIEWS.map((entry) => {
              const active = entry.id === view;
              return (
                <li key={entry.id}>
                  <button
                    type="button"
                    aria-current={active ? "page" : undefined}
                    data-active={active}
                    onClick={() => setView(entry.id)}
                    className="nav-item px-3 py-1.5 text-[13px] text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    {entry.label}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      </header>
      <main className="mx-auto w-full max-w-[80rem] flex-1 px-4 py-6 sm:px-6">
        <AnalyticsFilterProvider>
          <ActiveView view={view} onSessionChange={onSessionChange} />
        </AnalyticsFilterProvider>
      </main>
      <footer className="border-t border-border">
        <p className="mx-auto w-full max-w-[80rem] px-4 py-3 text-xs text-muted-foreground sm:px-6">
          Demo analytics over your uploaded file only. Findings describe the
          uploaded dataset, not a real company.
        </p>
      </footer>
    </div>
  );
}
