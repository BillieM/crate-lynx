import { render, screen } from "@testing-library/react";

import { TrackStatusDot } from "./TrackStatusDot";

describe("TrackStatusDot", () => {
  it("renders a green status dot for linked tracks", () => {
    render(<TrackStatusDot status="linked" />);

    expect(screen.getByRole("status", { name: "Linked track" })).toHaveClass("bg-ctp-green");
  });

  it("renders a yellow status dot for pending tracks", () => {
    render(<TrackStatusDot status="pending" />);

    expect(screen.getByRole("status", { name: "Pending track" })).toHaveClass("bg-ctp-yellow");
  });

  it("renders a red status dot for unlinked tracks", () => {
    render(<TrackStatusDot status="unlinked" />);

    expect(screen.getByRole("status", { name: "Unlinked track" })).toHaveClass("bg-ctp-red");
  });
});
