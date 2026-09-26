import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { act, useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import * as matchers from "vitest-axe/matchers";
import App from "./App";
import AppShell from "./components/AppShell";
import { FilterSelect, KpiDefinition } from "./components/patterns";
import { EmptyState, ErrorState, LoadingState } from "./components/states";
import { chartPalette, seriesShape } from "./lib/chart-theme";
import { SessionProvider } from "./lib/session-context";
import { useSession } from "./lib/session";
import type { SessionSnapshot } from "./lib/session";
import UploadSession from "./components/UploadSession";

expect.extend(matchers);

const VIEW_PHASES: Array<[string, string]> = [
  ["Commercial", "Phase 14"],
  ["Diagnostics", "Phase 15"],
];
// Data Quality left the stub set in Phase 11, Overview in Phase 12, and
// Delivery in Phase 13: they render real views now (covered in their own
// test files), so they are asserted separately below.

describe("Phase-10 application shell", () => {
  it("navigates six governed views with the upload view active first", () => {
    render(<App />);
    const nav = screen.getByRole("navigation", { name: /dashboard views/i });
    const inNav = within(nav);
    const buttons = [
      "Upload",
      "Data Quality",
      "Overview",
      "Delivery",
      ...VIEW_PHASES.map(([label]) => label),
    ].map((label) => inNav.getByRole("button", { name: label }));
    expect(nav).toBeInTheDocument();
    expect(buttons).toHaveLength(6);
    expect(inNav.getByRole("button", { name: "Upload" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    fireEvent.click(inNav.getByRole("button", { name: "Delivery" }));
    expect(inNav.getByRole("button", { name: "Delivery" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.getByRole("heading", { name: "Delivery" }),
    ).toBeInTheDocument();
  });

  it("renders the real Data Quality view instead of a phase stub", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Data Quality" }));
    expect(
      screen.getByRole("heading", { name: "Data Quality" }),
    ).toBeInTheDocument();
    expect(screen.getByText("No dataset loaded")).toBeInTheDocument();
    expect(screen.queryByText(/phase 11/i)).not.toBeInTheDocument();
  });

  it("renders the real Overview view instead of a phase stub", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Overview" }));
    expect(
      screen.getByRole("heading", { name: "Overview" }),
    ).toBeInTheDocument();
    expect(screen.getByText("No dataset loaded")).toBeInTheDocument();
    expect(screen.queryByText(/phase 12/i)).not.toBeInTheDocument();
  });

  it("renders the real Delivery view instead of a phase stub", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Delivery" }));
    expect(
      screen.getByRole("heading", { name: "Delivery" }),
    ).toBeInTheDocument();
    expect(screen.getByText("No dataset loaded")).toBeInTheDocument();
    expect(screen.queryByText(/phase 13/i)).not.toBeInTheDocument();
  });

  it("marks future views with their owning phase and no fabricated numbers", () => {
    render(<App />);
    for (const [label, phase] of VIEW_PHASES) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(screen.getByText(new RegExp(`${phase}`))).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: "Commercial" }));
    expect(screen.queryByTestId(/kpi/i)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/57\.3|42\.7|33,054,402/);
  });

  it("shows an empty session badge until a session snapshot arrives", () => {
    render(<App />);
    expect(screen.getByText("No session")).toBeInTheDocument();
  });

  it("reflects the global session snapshot in the shell badge", () => {
    const snapshot: SessionSnapshot = {
      session: {
        sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        statusUrl: "/api/v1/sessions/x/status",
        filenameSafe: "orders.csv",
        bytes: 41,
        sha256: "ab".repeat(32),
        encoding: "utf-8",
      },
      sessionState: "READY",
    };
    function Host() {
      const { updateSnapshot } = useSession();
      useEffect(() => {
        updateSnapshot(snapshot);
      }, [updateSnapshot]);
      return <AppShell onSessionChange={updateSnapshot} />;
    }
    render(
      <SessionProvider>
        <Host />
      </SessionProvider>,
    );
    expect(screen.getByText(/3fa85f64/)).toBeInTheDocument();
    expect(screen.getByText(/READY/)).toBeInTheDocument();
  });

  it("notifies the shell snapshot without changing upload rendering", () => {
    const seen: SessionSnapshot[] = [];
    render(
      <UploadSession
        onSessionChange={(change) => {
          seen.push(change);
        }}
      />,
    );
    expect(
      screen.getByRole("heading", { name: /upload a supply-chain csv/i }),
    ).toBeInTheDocument();
    expect(seen.length).toBeGreaterThan(0);
    expect(seen[seen.length - 1]).toEqual({
      session: null,
      sessionState: null,
    });
  });

  it("keeps every nav control keyboard-focusable and operable", () => {
    render(<App />);
    const nav = screen.getByRole("navigation", { name: /dashboard views/i });
    const cases: Array<[string, RegExp]> = [
      ["Upload", /upload a supply-chain csv/i],
      ["Data Quality", /^data quality$/i],
      ["Overview", /^overview$/i],
      ["Delivery", /^delivery$/i],
      ["Commercial", /^commercial$/i],
      ["Diagnostics", /^diagnostics$/i],
    ];
    for (const [label, heading] of cases) {
      const button = within(nav).getByRole("button", { name: label });
      // Native button semantics: keyboard activation (Enter/Space) fires
      // click by default, so focus + click covers operability. Trusted
      // key-triggered activation itself is a browser default that jsdom
      // does not implement; no user-event dependency is added for it.
      expect(button.tagName).toBe("BUTTON");
      button.focus();
      expect(document.activeElement).toBe(button);
      fireEvent.click(button);
      expect(button).toHaveAttribute("aria-current", "page");
      expect(
        screen.getByRole("heading", { name: heading }),
      ).toBeInTheDocument();
    }
  });

  it("reports no axe violations on the shell and a future view", async () => {
    const { container } = render(<App />);
    expect(await axe(container)).toHaveNoViolations();
    fireEvent.click(screen.getByRole("button", { name: "Overview" }));
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("Phase-10 state primitives", () => {
  it("renders loading, error, and empty states distinctly", () => {
    const { rerender } = render(<LoadingState label="Loading the session…" />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading the session…",
    );
    rerender(
      <ErrorState message="Could not reach the server." guidance="Retry." />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Could not reach the server.",
    );
    rerender(
      <EmptyState title="Nothing here yet" body="Upload a file first." />,
    );
    expect(screen.getByText("Nothing here yet")).toBeInTheDocument();
  });
});

describe("Phase-10 filter and definition patterns", () => {
  it("collects and clears a filter choice without fetching", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <FilterSelect
        id="region"
        label="Region"
        options={[{ value: "South", label: "South" }]}
        value={null}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByLabelText("Region"), {
      target: { value: "South" },
    });
    expect(onChange).toHaveBeenCalledWith("South");
    rerender(
      <FilterSelect
        id="region"
        label="Region"
        options={[{ value: "South", label: "South" }]}
        value="South"
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /clear region/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("discloses a governed KPI definition on demand", () => {
    render(
      <KpiDefinition
        term="Recorded net order value"
        meaning="Authoritative commercial total."
        population="All order-item lines in scope."
        exclusions="None."
      />,
    );
    const details = document.querySelector("details");
    expect(details?.open ?? false).toBe(false);
    fireEvent.click(screen.getByText(/what does/i));
    expect(details?.open ?? false).toBe(true);
    expect(
      screen.getByText("Authoritative commercial total."),
    ).toBeInTheDocument();
  });

  it("fixes chart conventions without rendering data", () => {
    expect(chartPalette).toHaveLength(5);
    expect(new Set(chartPalette).size).toBe(5);
    expect(seriesShape(0)).toBe("solid");
    expect(seriesShape(3)).toBe("solid");
  });
});

const LIFETIME_SESSION_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6";
const LIFETIME_SHORT_ID = LIFETIME_SESSION_ID.slice(0, 8);

const LIFETIME_ACCEPTED = {
  data: {
    sessionId: LIFETIME_SESSION_ID,
    statusUrl: `/api/v1/sessions/${LIFETIME_SESSION_ID}/status`,
    filenameSafe: "orders.csv",
    bytes: 41,
    sha256: "ab".repeat(32),
    encoding: "utf-8",
  },
  meta: {
    appVersion: "0.1.0",
    schemaVersion: 1,
    generatedAt: "2026-09-24T00:00:00",
    sessionId: LIFETIME_SESSION_ID,
    sessionState: "VALIDATING",
  },
  error: null,
};

function lifetimeStatus(
  state: string,
  error: Record<string, unknown> | null = null,
): unknown {
  return {
    data: {
      state,
      stage: state,
      progress: {
        completedStages: ["UPLOADING"],
        currentStage: state,
        remainingStages: [],
        note: "Synthetic lifetime fixture.",
      },
      startedAt: "2026-09-24T00:00:00",
      updatedAt: "2026-09-24T00:00:01",
      error,
    },
    meta: {
      appVersion: "0.1.0",
      schemaVersion: 1,
      generatedAt: "2026-09-24T00:00:01",
      sessionId: LIFETIME_SESSION_ID,
      sessionState: state,
    },
    error: null,
  };
}

const LIFETIME_FAILED_SCHEMA_ERROR = {
  code: "SCHEMA_MISSING_COLUMN",
  stage: "VALIDATING",
  message:
    "The file is missing 2 required columns: Order Id, Sales. V1 supports DataCo-compatible CSV files: add the missing columns and upload again.",
  details: {
    missing: ["Order Id", "Sales"],
    recognized: 1,
    columnCount: 3,
  },
};

const LIFETIME_SCHEMA = {
  data: {
    sourceColumns: ["Order Id"],
    mapping: [{ source: "Order Id", canonical: "order_id", class: "required" }],
    missingCritical: [],
  },
  meta: {},
  error: null,
};

const LIFETIME_PROFILE = {
  data: {
    rows: 2,
    columns: 1,
    grain: "order_item",
    missingness: [],
    cardinality: [],
    duplicates: { exact: 0, keyDupes: 0 },
    invarianceConflicts: {
      ordersChecked: 2,
      conflictingOrders: 0,
      byField: [],
    },
  },
  meta: {},
  error: null,
};

const LIFETIME_QUALITY = {
  data: {
    summary: {
      rulesEvaluated: 1,
      rulesTriggered: 0,
      errors: 0,
      warnings: 0,
      infos: 0,
      blockingIssues: 0,
    },
    issues: [],
  },
  meta: {},
  error: null,
};

const LIFETIME_CLEANING = {
  data: { steps: [] },
  meta: {},
  error: null,
};

/** Scripted XHR transport: upload always accepted (202). */
class LifetimeXHR {
  static DONE = 4;
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = {
    onprogress: null,
  };
  onreadystatechange: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  status = 0;
  responseText = "";

  open(): void {
    // No-op: scripted transport.
  }

  send(): void {
    this.readyState = 4;
    this.status = 202;
    this.responseText = JSON.stringify(LIFETIME_ACCEPTED);
    if (this.onreadystatechange !== null) {
      this.onreadystatechange();
    }
  }
}

/** Route stubbed fetch calls by URL suffix; DELETE removes the session. */
function stubLifetimeApi(statusNext: () => unknown): void {
  // KPI endpoints answer 409 NOT_READY here: these lifetime tests exercise
  // session/badge preservation across navigation (not KPI content), and the
  // real backend gates every KPI endpoint behind READY the same way.
  const kpiNotReady = {
    data: null,
    meta: {},
    error: {
      code: "NOT_READY",
      stage: "ANALYZING",
      message: "KPI analysis has not completed yet.",
      details: {},
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((input: unknown, init?: { method?: string }) => {
      const url = String(input);
      let body: unknown;
      let status = 200;
      if (init?.method === "DELETE") {
        body = { data: { deleted: true }, meta: {}, error: null };
      } else if (url.endsWith("/status")) {
        body = statusNext();
      } else if (url.includes("/kpis/")) {
        body = kpiNotReady;
        status = 409;
      } else if (url.endsWith("/schema")) {
        body = LIFETIME_SCHEMA;
      } else if (url.endsWith("/profile")) {
        body = LIFETIME_PROFILE;
      } else if (url.endsWith("/data-quality")) {
        body = LIFETIME_QUALITY;
      } else if (url.endsWith("/cleaning-report")) {
        body = LIFETIME_CLEANING;
      } else {
        body = lifetimeStatus("VALIDATING");
      }
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
}

function lifetimeCsv(): File {
  return new File(["order_id\n1\n"], "orders.csv", { type: "text/csv" });
}

async function uploadLifetimeFile(): Promise<void> {
  fireEvent.change(screen.getByTestId("file-input"), {
    target: { files: [lifetimeCsv()] },
  });
  fireEvent.click(screen.getByTestId("upload-button"));
  await screen.findByTestId("success-panel");
}

/** The shell badge carrying the live session id (never the "No session" one). */
function lifetimeBadge(): HTMLElement {
  const matches = screen
    .getAllByRole("status")
    .filter((element) =>
      (element.textContent ?? "").includes(LIFETIME_SHORT_ID),
    );
  expect(matches.length).toBeGreaterThan(0);
  return matches[0];
}

describe("Phase-10 session lifetime across navigation", () => {
  beforeEach(() => {
    vi.stubGlobal("XMLHttpRequest", LifetimeXHR);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("keeps a READY session across away/back navigation", async () => {
    stubLifetimeApi(() => lifetimeStatus("READY"));
    render(<App />);
    await uploadLifetimeFile();
    await waitFor(() => {
      expect(lifetimeBadge()).toHaveTextContent("READY");
    });

    fireEvent.click(screen.getByRole("button", { name: "Delivery" }));
    expect(
      screen.getByRole("heading", { name: "Delivery" }),
    ).toBeInTheDocument();
    // Session survives navigation: badge keeps id + READY, no empty state.
    expect(screen.queryByText("No session")).not.toBeInTheDocument();
    expect(lifetimeBadge()).toHaveTextContent("READY");
    // Upload stays mounted but leaves the accessibility tree while hidden.
    expect(
      screen.queryByRole("heading", { name: /upload a supply-chain csv/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("success-panel").closest("[hidden]"),
    ).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    // Same session is still represented; the empty picker does not return.
    expect(lifetimeBadge()).toHaveTextContent(LIFETIME_SHORT_ID);
    expect(screen.getByTestId("success-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("file-input")).not.toBeInTheDocument();
    expect(screen.queryByText("No session")).not.toBeInTheDocument();
  });

  it("advances a processing session to READY while Upload is hidden", async () => {
    vi.useFakeTimers();
    let statusCalls = 0;
    stubLifetimeApi(() => {
      statusCalls += 1;
      return lifetimeStatus(statusCalls === 1 ? "VALIDATING" : "READY");
    });
    render(<App />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [lifetimeCsv()] },
    });
    fireEvent.click(screen.getByTestId("upload-button"));
    await act(async () => {});
    expect(screen.getByTestId("success-panel")).toBeInTheDocument();
    expect(statusCalls).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "Delivery" }));
    expect(
      screen.queryByRole("heading", { name: /upload a supply-chain csv/i }),
    ).not.toBeInTheDocument();

    // Polling continues while hidden: the retry fires and READY propagates
    // to the shell badge without ever showing the Upload view again.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(statusCalls).toBe(2);
    expect(screen.queryByText("No session")).not.toBeInTheDocument();
    expect(lifetimeBadge()).toHaveTextContent("READY");

    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(screen.getByTestId("success-panel")).toBeInTheDocument();
    expect(screen.getByTestId("status-note")).toHaveTextContent(
      /kpi analysis is complete/i,
    );
  });

  it("clears the global snapshot through the user-visible reset flow", async () => {
    stubLifetimeApi(() => lifetimeStatus("READY"));
    render(<App />);
    await uploadLifetimeFile();
    await waitFor(() => {
      expect(lifetimeBadge()).toHaveTextContent("READY");
    });
    expect(lifetimeBadge()).toHaveTextContent(LIFETIME_SHORT_ID);

    fireEvent.click(screen.getByRole("button", { name: /remove session/i }));
    await waitFor(() => {
      expect(screen.getByText("No session")).toBeInTheDocument();
    });
    expect(screen.queryByText(LIFETIME_SHORT_ID)).not.toBeInTheDocument();
    expect(screen.queryByTestId("success-panel")).not.toBeInTheDocument();
    // Upload returns to its no-session picker UI.
    expect(screen.getByTestId("file-input")).toBeInTheDocument();
  });

  it("propagates FAILED to the shell badge without stale READY state", async () => {
    stubLifetimeApi(() =>
      lifetimeStatus("FAILED", LIFETIME_FAILED_SCHEMA_ERROR),
    );
    render(<App />);
    await uploadLifetimeFile();
    await waitFor(() => {
      expect(lifetimeBadge()).toHaveTextContent("FAILED");
    });
    expect(screen.queryByText("No session")).not.toBeInTheDocument();
    expect(screen.getByTestId("error-panel")).toHaveTextContent(
      /missing 2 required columns/i,
    );
    expect(screen.queryByText(/READY/)).not.toBeInTheDocument();
  });

  it("reports no axe violations with Upload hidden behind a future view", async () => {
    stubLifetimeApi(() => lifetimeStatus("READY"));
    const { container } = render(<App />);
    await uploadLifetimeFile();
    fireEvent.click(screen.getByRole("button", { name: "Delivery" }));
    expect(await axe(container)).toHaveNoViolations();
  });
});
