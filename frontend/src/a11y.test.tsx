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
});
