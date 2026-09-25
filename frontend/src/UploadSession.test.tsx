import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import UploadSession from "./components/UploadSession";

const ACCEPTED_202 = {
  data: {
    sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    statusUrl: "/api/v1/sessions/3fa85f64-5717-4562-b3fc-2c963f66afa6/status",
    filenameSafe: "orders.csv",
    bytes: 41,
    sha256: "ab".repeat(32),
    encoding: "utf-8",
  },
  meta: {
    appVersion: "0.1.0",
    schemaVersion: 1,
    generatedAt: "2026-09-24T00:00:00",
    sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    sessionState: "VALIDATING",
  },
  error: null,
};

const STATUS_FAILED_SCHEMA = {
  data: {
    state: "FAILED",
    stage: "VALIDATING",
    progress: {
      completedStages: ["UPLOADING"],
      currentStage: "VALIDATING",
      remainingStages: ["PROFILING"],
      note: "Later processing stages are not implemented yet.",
    },
    startedAt: "2026-09-24T00:00:00",
    updatedAt: "2026-09-24T00:00:01",
    error: {
      code: "SCHEMA_MISSING_COLUMN",
      stage: "VALIDATING",
      message:
        "The file is missing 2 required columns: Order Id, Sales. V1 supports DataCo-compatible CSV files: add the missing columns and upload again.",
      details: {
        missing: ["Order Id", "Sales"],
        recognized: 1,
        columnCount: 3,
      },
    },
  },
  meta: {
    appVersion: "0.1.0",
    schemaVersion: 1,
    generatedAt: "2026-09-24T00:00:01",
    sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    sessionState: "FAILED",
  },
  error: null,
};

const SCHEMA_OK = {
  data: {
    sourceColumns: ["Order Id", "Sales", "Warehouse Zone"],
    mapping: [
      { source: "Order Id", canonical: "order_id", class: "required" },
      { source: "Sales", canonical: "gross_sales", class: "required" },
      { source: "Warehouse Zone", canonical: null, class: "unknown" },
    ],
    missingCritical: [],
  },
  meta: {
    appVersion: "0.1.0",
    schemaVersion: 1,
    generatedAt: "2026-09-24T00:00:02",
    sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    sessionState: "PROFILING",
  },
  error: null,
};

const STATUS_CANONICALIZING = {
  data: {
    state: "CANONICALIZING",
    stage: "CANONICALIZING",
    progress: {
      completedStages: ["UPLOADING", "VALIDATING", "PROFILING", "CLEANING"],
      currentStage: "CANONICALIZING",
      remainingStages: ["ANALYZING", "READY"],
      note: "Cleaning is complete; canonicalization is parked at its quality gate.",
    },
    startedAt: "2026-09-24T00:00:00",
    updatedAt: "2026-09-24T00:00:02",
    error: null,
  },
  meta: {
    appVersion: "0.1.0",
    schemaVersion: 1,
    generatedAt: "2026-09-24T00:00:02",
    sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    sessionState: "CANONICALIZING",
  },
  error: null,
};

const STATUS_ANALYZING = {
  data: {
    state: "ANALYZING",
    stage: "ANALYZING",
    progress: {
      completedStages: [
        "UPLOADING",
        "VALIDATING",
        "PROFILING",
        "CLEANING",
        "CANONICALIZING",
      ],
      currentStage: "ANALYZING",
      remainingStages: ["READY"],
      note: "Canonical tables are built; KPI analysis is not implemented yet.",
    },
    startedAt: "2026-09-24T00:00:00",
    updatedAt: "2026-09-24T00:00:02",
    error: null,
  },
  meta: {
    appVersion: "0.1.0",
    schemaVersion: 1,
    generatedAt: "2026-09-24T00:00:02",
    sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    sessionState: "ANALYZING",
  },
  error: null,
};

const STATUS_READY = {
  data: {
    state: "READY",
    stage: "READY",
    progress: {
      completedStages: [
        "UPLOADING",
        "VALIDATING",
        "PROFILING",
        "CLEANING",
        "CANONICALIZING",
        "ANALYZING",
      ],
      currentStage: "READY",
      remainingStages: [],
      note: "KPI analysis is complete; dashboard and export endpoints serve results.",
    },
    startedAt: "2026-09-24T00:00:00",
    updatedAt: "2026-09-24T00:00:02",
    error: null,
  },
  meta: {
    appVersion: "0.1.0",
    schemaVersion: 1,
    generatedAt: "2026-09-24T00:00:02",
    sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    sessionState: "READY",
  },
  error: null,
};

const PROFILE_OK = {
  data: {
    rows: 4,
    columns: 25,
    grain: "order_item",
    missingness: [],
    cardinality: [],
    duplicates: { exact: 0, keyDupes: 0 },
    invarianceConflicts: {
      ordersChecked: 4,
      conflictingOrders: 0,
      byField: [],
    },
  },
  meta: {
    appVersion: "0.1.0",
    schemaVersion: 1,
    generatedAt: "2026-09-24T00:00:02",
    sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    sessionState: "CANONICALIZING",
  },
  error: null,
};

const QUALITY_OK = {
  data: {
    summary: {
      rulesEvaluated: 20,
      rulesTriggered: 2,
      errors: 0,
      warnings: 1,
      infos: 1,
      blockingIssues: 0,
    },
    issues: [
      {
        ruleId: "DQ-CAT-005",
        severity: "INFO",
        count: 1,
        treatment: "detected",
        blockedStage: null,
      },
      {
        ruleId: "DQ-NUM-002",
        severity: "WARNING",
        count: 1,
        treatment: "flagged",
        blockedStage: null,
      },
    ],
  },
  meta: {
    appVersion: "0.1.0",
    schemaVersion: 1,
    generatedAt: "2026-09-24T00:00:02",
    sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    sessionState: "CANONICALIZING",
  },
  error: null,
};

const QUALITY_BLOCKED = {
  data: {
    summary: {
      rulesEvaluated: 20,
      rulesTriggered: 1,
      errors: 1,
      warnings: 0,
      infos: 0,
      blockingIssues: 1,
    },
    issues: [
      {
        ruleId: "DQ-KEY-001",
        severity: "ERROR",
        count: 2,
        treatment: "flagged",
        blockedStage: "CANONICALIZATION",
      },
    ],
  },
  meta: {
    appVersion: "0.1.0",
    schemaVersion: 1,
    generatedAt: "2026-09-24T00:00:02",
    sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    sessionState: "CANONICALIZING",
  },
  error: null,
};

const CLEANING_OK = {
  data: {
    steps: [
      {
        ruleId: "DQ-CAT-005",
        field: "destination_country",
        detected: 1,
        fixed: 1,
        flagged: 0,
        excluded: 0,
        unchanged: 0,
        reason: "Trimmed leading/trailing whitespace; 1 cell(s) changed.",
      },
      {
        ruleId: "DQ-NUM-002",
        field: "gross_sales,discount_amount,net_sales",
        detected: 1,
        fixed: 0,
        flagged: 1,
        excluded: 0,
        unchanged: 0,
        reason: "1 observation(s) retained without change for investigation.",
      },
    ],
  },
  meta: {
    appVersion: "0.1.0",
    schemaVersion: 1,
    generatedAt: "2026-09-24T00:00:02",
    sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    sessionState: "CANONICALIZING",
  },
  error: null,
};

const CLEANING_FLAGGED_ONLY = {
  data: {
    steps: [
      {
        ruleId: "DQ-KEY-001",
        field: "order_item_id",
        detected: 2,
        fixed: 0,
        flagged: 2,
        excluded: 0,
        unchanged: 0,
        reason:
          "2 observation(s) retained without change. Blocks CANONICALIZATION until the input is fixed or replaced.",
      },
    ],
  },
  meta: {
    appVersion: "0.1.0",
    schemaVersion: 1,
    generatedAt: "2026-09-24T00:00:02",
    sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    sessionState: "CANONICALIZING",
  },
  error: null,
};

/** Route stubbed fetch calls to the report fixtures by URL suffix. */
function stubPhase6Fetch(
  qualityBody: unknown = QUALITY_OK,
  cleaningBody: unknown = CLEANING_OK,
  statusBody: unknown = STATUS_ANALYZING,
): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: unknown) => {
      const url = String(input);
      const body = url.endsWith("/schema")
        ? SCHEMA_OK
        : url.endsWith("/profile")
          ? PROFILE_OK
          : url.endsWith("/data-quality")
            ? qualityBody
            : url.endsWith("/cleaning-report")
              ? cleaningBody
              : statusBody;
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
}

const STATUS_VALIDATING = {
  data: {
    state: "VALIDATING",
    stage: "VALIDATING",
    progress: {
      completedStages: ["UPLOADING"],
      currentStage: "VALIDATING",
      remainingStages: ["PROFILING"],
      note: "Later processing stages are not implemented yet.",
    },
    startedAt: "2026-09-24T00:00:00",
    updatedAt: "2026-09-24T00:00:01",
    error: null,
  },
  meta: {
    appVersion: "0.1.0",
    schemaVersion: 1,
    generatedAt: "2026-09-24T00:00:01",
    sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    sessionState: "VALIDATING",
  },
  error: null,
};

interface XhrScript {
  status: number;
  body: unknown;
  networkError?: boolean;
}

class FakeXMLHttpRequest {
  static script: XhrScript = { status: 202, body: ACCEPTED_202 };
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
    const script = FakeXMLHttpRequest.script;
    if (script.networkError === true) {
      if (this.onerror !== null) {
        this.onerror();
      }
      return;
    }
    this.readyState = 4;
    this.status = script.status;
    this.responseText = JSON.stringify(script.body);
    if (this.onreadystatechange !== null) {
      this.onreadystatechange();
    }
  }
}

function stubFetchJson(body: unknown, status = 200): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    ),
  );
}

function csvFile(name = "orders.csv"): File {
  return new File(["order_id\n1\n"], name, { type: "text/csv" });
}

beforeEach(() => {
  FakeXMLHttpRequest.script = { status: 202, body: ACCEPTED_202 };
  vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest);
  stubFetchJson(STATUS_VALIDATING);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("UploadSession", () => {
  it("exposes an accessible upload control with cap guidance", () => {
    render(<UploadSession />);
    expect(screen.getByLabelText(/choose a csv file/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^upload$/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/maximum 250 mb/i)).toBeInTheDocument();
  });

  it("shows the selected file before uploading", () => {
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    expect(screen.getByTestId("selected-file")).toHaveTextContent("orders.csv");
  });

  it("accepts a dropped file", () => {
    render(<UploadSession />);
    fireEvent.drop(screen.getByTestId("dropzone"), {
      dataTransfer: { files: [csvFile("dropped.csv")] },
    });
    expect(screen.getByTestId("selected-file")).toHaveTextContent(
      "dropped.csv",
    );
  });

  it("gives immediate feedback for a non-CSV extension", () => {
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: {
        files: [new File(["x"], "notes.txt", { type: "text/plain" })],
      },
    });
    expect(screen.getByRole("status")).toHaveTextContent(/only .csv files/i);
    expect(screen.getByRole("button", { name: /^upload$/i })).toBeDisabled();
  });

  it("gives immediate feedback for an oversized file", () => {
    render(<UploadSession />);
    const huge = csvFile("huge.csv");
    Object.defineProperty(huge, "size", { value: 260 * 1024 * 1024 });
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [huge] },
    });
    expect(screen.getByRole("status")).toHaveTextContent(/over the 250 mb/i);
    expect(screen.getByRole("button", { name: /^upload$/i })).toBeDisabled();
  });

  it("renders the 202 session facts and the pending-stages note", async () => {
    vi.useFakeTimers();
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    // Flush the scripted XHR + first status fetch (microtasks only).
    await act(async () => {});
    expect(screen.getByTestId("success-panel")).toBeInTheDocument();
    expect(screen.getByTestId("success-panel")).toHaveTextContent("orders.csv");
    expect(screen.getByTestId("success-panel")).toHaveTextContent("utf-8");
    // Exhaust the bounded poll loop: state never leaves VALIDATING.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6 * 2000);
    });
    expect(screen.getByTestId("status-note")).toHaveTextContent(
      /not available in this build yet/i,
    );
  });

  it("renders the backend error envelope actionably", async () => {
    FakeXMLHttpRequest.script = {
      status: 400,
      body: {
        data: null,
        meta: {
          appVersion: "0.1.0",
          schemaVersion: 1,
          generatedAt: "2026-09-24T00:00:00",
        },
        error: {
          code: "EMPTY_FILE",
          stage: "VALIDATING",
          message: "The file is empty (0 bytes).",
          details: {},
        },
      },
    };
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    const panel = await screen.findByTestId("error-panel");
    expect(panel).toHaveTextContent(/empty \(0 bytes\)/i);
    expect(panel).toHaveTextContent(/header row/i);
    expect(panel).toHaveTextContent(/EMPTY_FILE/);
    expect(screen.queryByTestId("success-panel")).not.toBeInTheDocument();
  });

  it("explains an unreachable backend", async () => {
    FakeXMLHttpRequest.script = {
      status: 0,
      body: null,
      networkError: true,
    };
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    expect(await screen.findByTestId("error-panel")).toHaveTextContent(
      /could not reach the local server/i,
    );
  });

  it("resets to the empty upload state after delete", async () => {
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    await screen.findByTestId("success-panel");
    stubFetchJson({ data: { deleted: true }, meta: {}, error: null });
    fireEvent.click(screen.getByRole("button", { name: /remove session/i }));
    await waitFor(() => {
      expect(screen.getByTestId("file-input")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("success-panel")).not.toBeInTheDocument();
  });

  it("sends no further status requests after reset", async () => {
    vi.useFakeTimers();
    const seen: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: unknown) => {
        const url = String(input);
        seen.push(url);
        const body = url.includes("/status")
          ? STATUS_VALIDATING
          : { data: { deleted: true }, meta: {}, error: null };
        return Promise.resolve(
          new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );
    const statusCalls = (): number =>
      seen.filter((url) => url.includes("/status")).length;
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    await act(async () => {});
    expect(screen.getByTestId("success-panel")).toBeInTheDocument();
    expect(statusCalls()).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: /remove session/i }));
    await act(async () => {});
    expect(screen.getByTestId("file-input")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(statusCalls()).toBe(1);
  });

  it("shows no dashboard or KPI content", async () => {
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    await screen.findByTestId("success-panel");
    for (const term of [
      /overview/i,
      /commercial/i,
      /diagnostics/i,
      /profit/i,
    ]) {
      expect(screen.queryByText(term)).not.toBeInTheDocument();
    }
  });

  it("shows the schema compatibility result for a compatible file", async () => {
    stubPhase6Fetch();
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    const panel = await screen.findByTestId("schema-panel");
    expect(panel).toHaveTextContent(/schema check passed/i);
    expect(panel).toHaveTextContent(/2 of 3 columns mapped/i);
    expect(panel).toHaveTextContent(/1 extra column ignored/i);
  });

  it("shows the profiling summary without repaired values", async () => {
    stubPhase6Fetch();
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    const panel = await screen.findByTestId("quality-panel");
    expect(panel).toHaveTextContent(/no values were repaired/i);
    expect(panel).toHaveTextContent(/4 order-item lines assessed/i);
    expect(panel).toHaveTextContent(/across 25 mapped fields/i);
    expect(panel).toHaveTextContent(/20 data-quality rules checked/i);
    expect(panel).toHaveTextContent(/2 issues found/i);
    expect(panel).toHaveTextContent(/Errors: 0/i);
    expect(panel).toHaveTextContent(/Warnings: 1/i);
    expect(panel).toHaveTextContent(/Informational notes: 1/i);
    expect(panel).toHaveTextContent(/no issue blocks the next stage/i);
    expect(panel).toHaveTextContent(/cleaning review below/i);
  });

  it("shows the cleaning review with detected-versus-fixed counts", async () => {
    stubPhase6Fetch();
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    const panel = await screen.findByTestId("cleaning-panel");
    expect(panel).toHaveTextContent(/2 detected across 2 rules/i);
    expect(panel).toHaveTextContent(/1 fixed/i);
    expect(panel).toHaveTextContent(/1 flagged/i);
    expect(panel).toHaveTextContent(/DQ-CAT-005/);
    expect(panel).toHaveTextContent(/DQ-NUM-002/);
    expect(panel).toHaveTextContent(/detected is not the same as fixed/i);
    expect(panel).toHaveTextContent(/next stage: kpi analysis/i);
    expect(panel.querySelector("p")).not.toBeNull();
  });

  it("states the analyzing park without claiming analytics", async () => {
    stubPhase6Fetch();
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    const note = await screen.findByTestId("status-note");
    expect(note).toHaveTextContent(/canonical tables are built/i);
    expect(note).toHaveTextContent(/kpi analytics are not available/i);
    for (const term of [
      /analysis complete/i,
      /dashboard ready/i,
      /clean dataset/i,
    ]) {
      expect(note).not.toHaveTextContent(term);
    }
  });

  it("states analysis completion without the unavailable copy", async () => {
    stubPhase6Fetch(QUALITY_OK, CLEANING_OK, STATUS_READY);
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    const note = await screen.findByTestId("status-note");
    expect(note).toHaveTextContent(/kpi analysis is complete/i);
    expect(note).toHaveTextContent(/ready for the dashboard views/i);
    expect(note).not.toHaveTextContent(/not available/i);
  });

  it("states the canonicalization gate instead of implying progress", async () => {
    stubPhase6Fetch(
      QUALITY_BLOCKED,
      CLEANING_FLAGGED_ONLY,
      STATUS_CANONICALIZING,
    );
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    const panel = await screen.findByTestId("cleaning-panel");
    expect(panel).toHaveTextContent(/canonicalization is gated/i);
    expect(panel).toHaveTextContent(/no complete canonical build exists/i);
    expect(panel).toHaveTextContent(/parked until the input/i);
  });

  it("never claims success while flagged issues remain", async () => {
    stubPhase6Fetch(
      QUALITY_BLOCKED,
      CLEANING_FLAGGED_ONLY,
      STATUS_CANONICALIZING,
    );
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    const panel = await screen.findByTestId("cleaning-panel");
    expect(panel).toHaveTextContent(/2 flagged issues remain/i);
    expect(panel).toHaveTextContent(/DQ-KEY-001/);
    for (const term of [
      /data cleaned successfully/i,
      /all issues fixed/i,
      /cleaning complete.*no issues/i,
    ]) {
      expect(panel).not.toHaveTextContent(term);
    }
  });

  it("states blocking issues without alarming language", async () => {
    stubPhase6Fetch(QUALITY_BLOCKED, CLEANING_OK, STATUS_CANONICALIZING);
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    const panel = await screen.findByTestId("quality-panel");
    expect(panel).toHaveTextContent(/1 issue blocks a later stage/i);
    expect(panel).toHaveTextContent(/nothing was fixed automatically/i);
  });

  it("shows missing columns for an incompatible file", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify(STATUS_FAILED_SCHEMA), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    const panel = await screen.findByTestId("error-panel");
    expect(panel).toHaveTextContent(/missing 2 required columns/i);
    expect(panel).toHaveTextContent("Order Id");
    expect(panel).toHaveTextContent("Sales");
    expect(panel).toHaveTextContent(/dataco-compatible/i);
    expect(panel).toHaveTextContent(/SCHEMA_MISSING_COLUMN/);
  });

  it("treats pending reports as retryable, not a failure", async () => {
    vi.useFakeTimers();
    let reportCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: unknown) => {
        const url = String(input);
        let body: unknown = STATUS_CANONICALIZING;
        let status = 200;
        if (
          url.endsWith("/schema") ||
          url.endsWith("/profile") ||
          url.endsWith("/data-quality") ||
          url.endsWith("/cleaning-report")
        ) {
          reportCalls += 1;
          if (reportCalls === 1) {
            status = 409;
            body = {
              data: null,
              meta: {},
              error: {
                code: "NOT_READY",
                stage: "CLEANING",
                message: "Auditable cleaning has not completed yet.",
                details: { state: "CANONICALIZING" },
              },
            };
          } else if (url.endsWith("/schema")) {
            body = SCHEMA_OK;
          } else if (url.endsWith("/profile")) {
            body = PROFILE_OK;
          } else if (url.endsWith("/data-quality")) {
            body = QUALITY_OK;
          } else {
            body = CLEANING_OK;
          }
        }
        return Promise.resolve(
          new Response(JSON.stringify(body), {
            status,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );
    render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    await act(async () => {});
    expect(screen.queryByTestId("error-panel")).not.toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByTestId("schema-panel")).toBeInTheDocument();
    expect(screen.getByTestId("quality-panel")).toBeInTheDocument();
    expect(screen.getByTestId("cleaning-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("error-panel")).not.toBeInTheDocument();
  });

  it("renders hostile header text inertly, never as HTML", async () => {
    const hostile = "<script>alert(1)</script>";
    vi.stubGlobal(
      "fetch",
      vi.fn((input: unknown) => {
        const url = String(input);
        let body: unknown = STATUS_CANONICALIZING;
        if (url.endsWith("/schema")) {
          body = {
            data: {
              sourceColumns: [hostile],
              mapping: [{ source: hostile, canonical: null, class: "unknown" }],
              missingCritical: [],
            },
            meta: {},
            error: null,
          };
        } else if (url.endsWith("/profile")) {
          body = PROFILE_OK;
        } else if (url.endsWith("/data-quality")) {
          body = QUALITY_OK;
        } else if (url.endsWith("/cleaning-report")) {
          body = CLEANING_OK;
        }
        return Promise.resolve(
          new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );
    const { container } = render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [csvFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    // The schema panel shows counts only, never header strings; the error
    // path below would render names as text. Either way no script element
    // may exist and markup must be escaped.
    await screen.findByTestId("schema-panel");
    await screen.findByTestId("quality-panel");
    expect(container.querySelector("script")).toBeNull();
    expect(container.innerHTML).not.toContain("<script>alert");
  });
});
