import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SessionLifecycle from "./components/SessionLifecycle";
import { stepForState } from "./lib/lifecycle-map";

describe("stepForState (lifecycle semantic map)", () => {
  it("maps every actual backend state explicitly", () => {
    expect(stepForState(null)).toEqual({
      complete: [],
      current: "Upload",
      status: "active",
    });
    expect(stepForState("UPLOADING")).toEqual({
      complete: [],
      current: "Upload",
      status: "active",
    });
    // Validation completes with upload acceptance; profiling starts next.
    expect(stepForState("VALIDATING")).toEqual({
      complete: [],
      current: "Upload",
      status: "active",
    });
    expect(stepForState("PROFILING")).toEqual({
      complete: ["Upload", "Validate"],
      current: "Profile",
      status: "active",
    });
    expect(stepForState("CLEANING")).toEqual({
      complete: ["Upload", "Validate", "Profile"],
      current: "Clean",
      status: "active",
    });
    // A quality gate parks canonicalization recoverably: Analyze is
    // current, nothing claims BLOCKED, nothing claims terminal.
    expect(stepForState("CANONICALIZING")).toEqual({
      complete: ["Upload", "Validate", "Profile", "Clean"],
      current: "Analyze",
      status: "active",
    });
    expect(stepForState("ANALYZING")).toEqual({
      complete: ["Upload", "Validate", "Profile", "Clean"],
      current: "Analyze",
      status: "active",
    });
    expect(stepForState("READY").complete).toHaveLength(6);
    expect(stepForState("READY").current).toBeNull();
    expect(stepForState("FAILED")).toEqual({
      complete: [],
      current: null,
      status: "failed",
    });
    expect(stepForState("EXPIRED")).toEqual({
      complete: [],
      current: null,
      status: "expired",
    });
  });

  it("claims no step for unknown states", () => {
    expect(stepForState("SOMETHING_NEW")).toEqual({
      complete: [],
      current: null,
      status: "pending",
    });
  });
});

describe("SessionLifecycle (conceptual pipeline display)", () => {
  it("marks the current step without percentages or progress bars", () => {
    render(<SessionLifecycle state="PROFILING" />);
    const pipeline = screen.getByRole("list", { name: "Session pipeline" });
    expect(pipeline).toHaveTextContent("Profile");
    expect(
      screen.getByText("Profile").closest("[aria-current]"),
    ).toHaveAttribute("aria-current", "step");
    expect(document.body.textContent).not.toMatch(/%/);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("distinguishes failed from expired without inventing BLOCKED", () => {
    const { rerender } = render(<SessionLifecycle state="FAILED" />);
    expect(screen.getByText(/· Failed/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/blocked/i);
    rerender(<SessionLifecycle state="EXPIRED" />);
    expect(screen.getByText(/· Expired/)).toBeInTheDocument();
    expect(screen.queryByText(/· Failed/)).not.toBeInTheDocument();
  });
});
