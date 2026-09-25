import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import * as matchers from "vitest-axe/matchers";
import App from "./App";
import UploadSession from "./components/UploadSession";

expect.extend(matchers);

class FakeXMLHttpRequest {
  static script: { status: number; body: unknown } = {
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
    this.readyState = 4;
    this.status = script.status;
    this.responseText = JSON.stringify(script.body);
    if (this.onreadystatechange !== null) {
      this.onreadystatechange();
    }
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("accessibility foundation", () => {
  it("reports no axe violations on the application shell", async () => {
    const { container } = render(<App />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("reports no axe violations on the upload error state", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest);
    const { container } = render(<UploadSession />);
    fireEvent.change(screen.getByTestId("file-input"), {
      target: {
        files: [
          new File(["order_id\n1\n"], "orders.csv", { type: "text/csv" }),
        ],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    expect(await screen.findByTestId("error-panel")).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("reports no axe violations on the schema result state", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest);
    FakeXMLHttpRequest.script = {
      status: 202,
      body: {
        data: {
          sessionId: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
          statusUrl: "/api/v1/sessions/x/status",
          filenameSafe: "orders.csv",
          bytes: 41,
          sha256: "ab".repeat(32),
          encoding: "utf-8",
        },
        meta: {},
        error: null,
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: unknown) => {
        const url = String(input);
        const body = url.endsWith("/schema")
          ? {
              data: {
                sourceColumns: ["Order Id", "Sales"],
                mapping: [
                  {
                    source: "Order Id",
                    canonical: "order_id",
                    class: "required",
                  },
                  {
                    source: "Sales",
                    canonical: "gross_sales",
                    class: "required",
                  },
                ],
                missingCritical: [],
              },
              meta: {},
              error: null,
            }
          : url.endsWith("/profile")
            ? {
                data: {
                  rows: 2,
                  columns: 2,
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
              }
            : url.endsWith("/data-quality")
              ? {
                  data: {
                    summary: {
                      rulesEvaluated: 20,
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
                }
              : url.endsWith("/cleaning-report")
                ? {
                    data: { steps: [] },
                    meta: {},
                    error: null,
                  }
                : {
                    data: {
                      state: "CANONICALIZING",
                      stage: "CANONICALIZING",
                      progress: {
                        completedStages: [
                          "UPLOADING",
                          "VALIDATING",
                          "PROFILING",
                          "CLEANING",
                        ],
                        currentStage: "CANONICALIZING",
                        remainingStages: [],
                        note: "Cleaning is complete.",
                      },
                      startedAt: "2026-09-24T00:00:00",
                      updatedAt: "2026-09-24T00:00:01",
                      error: null,
                    },
                    meta: {},
                    error: null,
                  };
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
      target: {
        files: [
          new File(["order_id\n1\n"], "orders.csv", { type: "text/csv" }),
        ],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    expect(await screen.findByTestId("schema-panel")).toBeInTheDocument();
    expect(await screen.findByTestId("quality-panel")).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });
});
