import { render, screen } from "@testing-library/react";

import { ActionButton } from "./ActionButton";
import { EmptyStateCard } from "./EmptyStateCard";
import { Pill } from "./Pill";
import { StatusMessage } from "./StatusMessage";

describe("shared UI primitives", () => {
  it("renders action buttons with neutral and disabled state classes", () => {
    render(<ActionButton disabled>Queue sync</ActionButton>);

    expect(screen.getByRole("button", { name: "Queue sync" })).toHaveClass(
      "border-ctp-surface1",
      "bg-ctp-surface0",
      "text-ctp-text",
      "disabled:cursor-not-allowed",
    );
  });

  it("renders toneable pills for repeated badges", () => {
    render(<Pill tone="pending">Pending</Pill>);

    expect(screen.getByText("Pending")).toHaveClass("bg-ctp-yellow/18", "text-ctp-yellow", "ring-ctp-yellow/30");
  });

  it("keeps status and empty states available as shared primitives", () => {
    render(
      <>
        <StatusMessage body="Tracks are being synced." status="pending" title="Sync in progress" />
        <EmptyStateCard body="There is nothing to review." role="status" title="No proposals" />
      </>,
    );

    expect(screen.getByRole("status", { name: "" })).toHaveTextContent("There is nothing to review.");
    expect(screen.getByText("Sync in progress")).toHaveClass("text-ctp-text");
  });
});
