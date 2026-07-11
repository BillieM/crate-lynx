import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ViewShell } from "./ViewShell";
import type { AppViewEntry } from "./viewRegistry";

function FailedChunk(): ReactNode {
  throw new Error("Failed to fetch dynamically imported module");
}

describe("ViewShell", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("recovers a failed lazy view in place when retry is selected", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const view: AppViewEntry = {
      actionLabels: [],
      icon: "tool",
      id: "recoverable-view",
      render: ({ retryKey }) =>
        retryKey === 0 ? <FailedChunk /> : <h2>Recovered view</h2>,
      title: "Recoverable view",
    };

    render(<ViewShell activeViewId={view.id} view={view} />);

    expect(screen.getByRole("heading", { name: "Recoverable view could not load" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry view" }));
    expect(screen.getByRole("heading", { name: "Recovered view" })).toBeInTheDocument();
  });
});
