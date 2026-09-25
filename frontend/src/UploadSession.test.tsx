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
});
