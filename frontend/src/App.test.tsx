import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App shell", () => {
  it("renders the dashboard heading", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", {
        name: /supply chain analytics dashboard/i,
      }),
    ).toBeInTheDocument();
  });

  it("reveals the stack-check status after activation", () => {
    render(<App />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /run stack check/i }));
    expect(screen.getByRole("status")).toHaveTextContent(/stack check passed/i);
  });
});
