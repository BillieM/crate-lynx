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

  it("renders compact local library track rows with metadata and link state", () => {
    render(<LocalLibraryView />);

    const trackList = screen.getByRole("region", { name: "Local library tracks" });

    expect(within(trackList).getByRole("heading", { name: "Local library track list" })).toBeInTheDocument();
    expect(within(trackList).getByText("Showing 5 of 5 rows")).toBeInTheDocument();
    expect(within(trackList).getAllByRole("status", { name: "Linked track" })).toHaveLength(2);
    expect(within(trackList).getByText("Night Shift")).toBeInTheDocument();
    expect(within(trackList).getByText("The Midnight")).toBeInTheDocument();
    expect(within(trackList).getByText("Nocturnal")).toBeInTheDocument();
    expect(within(trackList).getByText("Synthwave/The Midnight/Nocturnal/Night Shift.mp3")).toBeInTheDocument();
    expect(within(trackList).getAllByText("4:05")).toHaveLength(2);
    expect(within(trackList).getAllByText("ISRC")).toHaveLength(1);
    expect(within(trackList).getAllByText("Available")).toHaveLength(3);
  });

  it("filters the rendered library track rows by selected facets", () => {
    render(<LocalLibraryView />);

    const filters = screen.getByRole("region", { name: "Library filters" });

    fireEvent.click(within(filters).getByRole("button", { name: "Pending 43" }));
    fireEvent.change(within(filters).getByLabelText("Match method"), { target: { value: "manual" } });
    fireEvent.change(within(filters).getByLabelText("File status"), { target: { value: "missing" } });

    const trackList = screen.getByRole("region", { name: "Local library tracks" });
    expect(within(trackList).getByText("Showing 1 of 5 rows")).toBeInTheDocument();
    expect(within(trackList).getByText("Open Eye Signal")).toBeInTheDocument();
    expect(within(trackList).getByText("Jon Hopkins")).toBeInTheDocument();
    expect(within(trackList).queryByText("Night Shift")).not.toBeInTheDocument();
  });

  it("disables library filters while a refresh is pending", () => {
    render(<LocalLibraryView isPending />);

    expect(screen.getByText("Library refresh in progress")).toBeInTheDocument();

    const filters = screen.getByRole("region", { name: "Library filters" });
    expect(within(filters).getByRole("button", { name: "All 312" })).toBeDisabled();
    expect(within(filters).getByLabelText("Match method")).toBeDisabled();
    expect(within(filters).getByLabelText("File status")).toBeDisabled();
    expect(within(filters).getByRole("button", { name: "Reset library filters" })).toBeDisabled();
  });

  it("renders the library loading, error, and empty states", () => {
    const { rerender } = render(<LocalLibraryView state="loading" />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading library tracks");
    expect(screen.getByRole("region", { name: "Library filters" })).toBeInTheDocument();

    rerender(<LocalLibraryView state="error" />);

    expect(screen.getByRole("alert")).toHaveTextContent("Library unavailable");
    expect(screen.getByRole("region", { name: "Library filters" })).toBeInTheDocument();

    rerender(<LocalLibraryView tracks={[]} />);

    expect(screen.getByRole("heading", { name: "No matching library tracks" })).toBeInTheDocument();
  });
});
