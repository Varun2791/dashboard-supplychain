import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App shell", () => {
  it("renders the dashboard heading and the upload view", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", {
        name: /supply chain analytics dashboard/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /upload a supply-chain csv/i }),
    ).toBeInTheDocument();
  });

  it("states local-only processing and the upload cap", () => {
    render(<App />);
    expect(screen.getByText(/only on this machine/i)).toBeInTheDocument();
    expect(screen.getByText(/maximum 250 mb/i)).toBeInTheDocument();
  });
});
