import { render, screen } from "@testing-library/react";
import { Music2, Settings } from "lucide-react";

import { ActionButton } from "./ActionButton";
import { EmptyStateCard } from "./EmptyStateCard";
import { IconButton } from "./IconButton";
import { MetricCard } from "./MetricCard";
import { Pill } from "./Pill";
import { StatusMessage } from "./StatusMessage";
import { TrackStatusDot } from "./TrackStatusDot";

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

  it("renders icon buttons with accessible labels and tooltips", () => {
    render(
      <IconButton disabled label="Open app settings">
        <Settings data-testid="settings-icon" />
      </IconButton>,
    );

    const button = screen.getByRole("button", { name: "Open app settings" });
    const tooltip = screen.getByRole("tooltip");

    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Open app settings");
    expect(button).toHaveAttribute("aria-describedby", tooltip.id);
    expect(button).toHaveTextContent("");
    expect(button).toHaveClass("h-7", "w-7", "disabled:cursor-not-allowed");
    expect(screen.getByTestId("settings-icon")).toBeInTheDocument();
    expect(tooltip).toHaveTextContent("Open app settings");
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

  it("renders shared track status dots", () => {
    render(<TrackStatusDot status="linked" />);

    expect(screen.getByRole("status", { name: "Linked track" })).toHaveClass("bg-ctp-green");
  });

  it("renders reusable metric cards", () => {
    render(
      <MetricCard
        icon={Music2}
        label="Missing tracks"
        toneClass="bg-ctp-yellow/18 text-ctp-yellow ring-ctp-yellow/30"
        value={12}
      />,
    );

    expect(screen.getByRole("region", { name: "Missing tracks" })).toHaveTextContent("12");
  });
});
