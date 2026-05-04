import { fireEvent, render, screen, within } from "@testing-library/react";

import { LocalLibraryView } from "./LocalLibraryView";

describe("LocalLibraryView", () => {
  it("renders the library filter facets with current counts", () => {
    render(<LocalLibraryView />);

    const filters = screen.getByRole("region", { name: "Library filters" });

    expect(within(filters).getByRole("group", { name: "Library link status filters" })).toBeInTheDocument();
    expect(within(filters).getByRole("button", { name: "All 312" })).toHaveAttribute("aria-pressed", "true");
    expect(within(filters).getByRole("button", { name: "Linked 244" })).toHaveAttribute("aria-pressed", "false");
    expect(within(filters).getByRole("button", { name: "Pending 43" })).toHaveAttribute("aria-pressed", "false");
    expect(within(filters).getByRole("button", { name: "Unlinked 25" })).toHaveAttribute("aria-pressed", "false");
    expect(within(filters).getByLabelText("Match method")).toHaveValue("all");
    expect(within(filters).getByLabelText("File status")).toHaveValue("all");
    expect(within(filters).getByRole("button", { name: "Reset library filters" })).toBeDisabled();
  });

  it("updates and resets library filter selections", () => {
    render(<LocalLibraryView />);

    const filters = screen.getByRole("region", { name: "Library filters" });

    fireEvent.click(within(filters).getByRole("button", { name: "Pending 43" }));
    fireEvent.change(within(filters).getByLabelText("Match method"), { target: { value: "acoustic" } });
    fireEvent.change(within(filters).getByLabelText("File status"), { target: { value: "missing" } });

    expect(within(filters).getByRole("button", { name: "Pending 43" })).toHaveAttribute("aria-pressed", "true");
    expect(within(filters).getByLabelText("Match method")).toHaveValue("acoustic");
    expect(within(filters).getByLabelText("File status")).toHaveValue("missing");

    const resetButton = within(filters).getByRole("button", { name: "Reset library filters" });
    expect(resetButton).toBeEnabled();
    fireEvent.click(resetButton);

    expect(within(filters).getByRole("button", { name: "All 312" })).toHaveAttribute("aria-pressed", "true");
    expect(within(filters).getByLabelText("Match method")).toHaveValue("all");
    expect(within(filters).getByLabelText("File status")).toHaveValue("all");
    expect(resetButton).toBeDisabled();
  });
});
