/// <reference types="node" />
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AppShell from "./components/AppShell";
import { SessionContext } from "./lib/session";

const frontendRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const css = readFileSync(join(frontendRoot, "src/index.css"), "utf8");
const html = readFileSync(join(frontendRoot, "index.html"), "utf8");

describe("foundation slice 1: deterministic dark theme", () => {
  it("establishes dark statically with no runtime toggle", () => {
    expect(html).toContain('<html lang="en" class="dark">');
    expect(html).toContain('name="color-scheme" content="dark"');
    expect(css).toMatch(/:root\s*{[^}]*color-scheme:\s*dark/);
    expect(css).toMatch(/--background:\s*oklch\(0\.16/);
  });

  it("delivers JetBrains Mono from the local package, never a CDN", () => {
    expect(css).toContain("@fontsource-variable/jetbrains-mono");
    expect(css).not.toMatch(
      /fonts\.googleapis|fonts\.gstatic|https?:\/\/.*\.woff2/,
    );
  });

  it("centralizes token roles with no scattered hex or gradients", () => {
    for (const token of [
      "--accent-blue",
      "--focus-ring",
      "--text-muted",
      "--chart-grid",
      "--chart-secondary",
      "--border-strong",
      "--status-error",
      "--status-warning",
      "--status-ok",
      "--status-info",
    ]) {
      expect(css).toContain(token);
    }
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).not.toContain("linear-gradient");
  });

  it("holds the data-brutalist geometry scale and eyebrow utility", () => {
    // Sheets cap at 6px (rounded-lg), controls land near 4px (rounded-md).
    expect(css).toMatch(/--radius:\s*0\.375rem/);
    expect(css).toContain(".eyebrow");
    // Structural edges resolve through the shell-frame role, not a
    // Tailwind utility (no `border-strong` utility is generated).
    expect(css).toContain(".shell-frame");
    expect(css).toContain("var(--border-strong)");
  });

  it("ships focus-visible and reduced-motion foundations", () => {
    expect(css).toContain(":focus-visible");
    expect(css).toContain("outline-offset");
    expect(css).toContain("prefers-reduced-motion");
  });
});

function renderShellWith(state: string | null, sessionId: string | null) {
  render(
    <SessionContext.Provider
      value={{
        session:
          sessionId === null
            ? null
            : {
                sessionId,
                statusUrl: "/api/v1/sessions/x/status",
                filenameSafe: "orders.csv",
                bytes: 41,
                sha256: "ab".repeat(32),
                encoding: "utf-8",
              },
        sessionState: state,
        updateSnapshot: () => {},
      }}
    >
      <AppShell onSessionChange={vi.fn()} />
    </SessionContext.Provider>,
  );
}

describe("foundation slice 1: session marker tones", () => {
  const id = "3fa85f64-5717-4562-b3fc-2c963f66afa6";

  it.each([
    ["READY", "ok"],
    ["FAILED", "error"],
    ["PROFILING", "pending"],
    ["CANONICALIZING", "pending"],
  ])("maps %s to the %s marker without renaming the state", (state, tone) => {
    renderShellWith(state, id);
    const badge = screen.getByRole("status");
    expect(badge).toHaveTextContent("3fa85f64");
    expect(badge).toHaveTextContent(state);
    expect(badge.querySelector(".session-dot")).toHaveAttribute(
      "data-tone",
      tone,
    );
  });

  it("keeps the no-session state distinguishable and honest", () => {
    renderShellWith(null, null);
    const badge = screen.getByRole("status");
    expect(badge).toHaveTextContent("No session");
    expect(badge.querySelector(".session-dot")).toHaveAttribute(
      "data-tone",
      "idle",
    );
  });
});
