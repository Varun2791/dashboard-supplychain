import { useState } from "react";
import { useSession } from "@/lib/session";
import { ActiveView } from "@/components/views";
import { VIEWS } from "@/lib/view-registry";
import type { DashboardView } from "@/lib/view-registry";
import type { SessionSnapshot } from "@/lib/session";

function SessionBadge() {
  const { session, sessionState } = useSession();
  if (session === null) {
    return (
      <p className="text-sm text-muted-foreground" role="status">
        No session
      </p>
    );
  }
  return (
    <p className="text-sm text-muted-foreground" role="status">
      <span aria-hidden="true">● </span>
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
    <div className="flex min-h-svh flex-col">
      <header className="border-b">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-3 sm:px-6">
          <div>
            <h1 className="text-base font-semibold tracking-tight">
              Supply Chain Analytics Dashboard
            </h1>
            <p className="text-xs text-muted-foreground">
              Local-first · nothing leaves this machine
            </p>
          </div>
          <SessionBadge />
        </div>
        <nav
          aria-label="Dashboard views"
          className="mx-auto w-full max-w-6xl overflow-x-auto px-4 sm:px-6"
        >
          <ul className="flex gap-1 py-2">
            {VIEWS.map((entry) => {
              const active = entry.id === view;
              return (
                <li key={entry.id}>
                  <button
                    type="button"
                    aria-current={active ? "page" : undefined}
                    onClick={() => setView(entry.id)}
                    className={
                      active
                        ? "rounded-md bg-secondary px-3 py-1.5 text-sm font-medium"
                        : "rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
                    }
                  >
                    {entry.label}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
        <ActiveView view={view} onSessionChange={onSessionChange} />
      </main>
      <footer className="border-t">
        <p className="mx-auto w-full max-w-6xl px-4 py-3 text-xs text-muted-foreground sm:px-6">
          Demo analytics over your uploaded file only. Findings describe the
          uploaded dataset, not a real company.
        </p>
      </footer>
    </div>
  );
}
