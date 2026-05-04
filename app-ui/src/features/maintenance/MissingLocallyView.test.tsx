import { render, screen, within } from "@testing-library/react";

import { MissingLocallyView } from "./MissingLocallyView";

describe("MissingLocallyView", () => {
  it("renders summary counts for streaming tracks without local matches", () => {
    render(<MissingLocallyView />);

    const summary = screen.getByLabelText("Missing locally summary");

    expect(within(summary).getByLabelText("Missing tracks")).toHaveTextContent("3");
    expect(within(summary).getByLabelText("Affected playlists")).toHaveTextContent("3");
    expect(within(summary).getByLabelText("High priority")).toHaveTextContent("1");
  });

  it("lists streaming tracks with playlist and match gap details", () => {
    render(<MissingLocallyView />);

    const trackList = screen.getByRole("region", { name: "Missing local tracks" });

    expect(within(trackList).getByRole("heading", { name: "Streaming tracks without local matches" })).toBeInTheDocument();
    expect(within(trackList).getByText("3 rows")).toBeInTheDocument();
    expect(within(trackList).getAllByRole("status", { name: "Streaming track missing local match" })).toHaveLength(3);
    expect(within(trackList).getByText("Open Eye Signal")).toBeInTheDocument();
    expect(within(trackList).getByText("Jon Hopkins")).toBeInTheDocument();
    expect(within(trackList).getByText("Immunity")).toBeInTheDocument();
    expect(within(trackList).getByText("Late Night Drive")).toBeInTheDocument();
    expect(within(trackList).getByText("ytm:VLPL_missing_018")).toBeInTheDocument();
    expect(within(trackList).getByText("High gap")).toBeInTheDocument();
    expect(within(trackList).getAllByText("No local match")).toHaveLength(3);
    expect(within(trackList).getByText("No Reason")).toBeInTheDocument();
    expect(within(trackList).getByText("Bonobo feat. Nick Murphy")).toBeInTheDocument();
    expect(within(trackList).getByText("Melt!")).toBeInTheDocument();
    expect(within(trackList).getByText("Album unavailable")).toBeInTheDocument();
  });

  it("renders a pending status while missing-local matching is running", () => {
    render(<MissingLocallyView isPending />);

    expect(screen.getByText("Missing locally scan in progress")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Missing local tracks" })).toBeInTheDocument();
  });

  it("renders missing-locally loading, error, and empty states", () => {
    const { rerender } = render(<MissingLocallyView state="loading" />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading missing tracks");
    expect(screen.queryByText("Open Eye Signal")).not.toBeInTheDocument();

    rerender(<MissingLocallyView state="error" />);

    expect(screen.getByRole("alert")).toHaveTextContent("Missing locally unavailable");

    rerender(<MissingLocallyView tracks={[]} />);

    expect(screen.getByRole("heading", { name: "No missing tracks" })).toBeInTheDocument();
    expect(screen.getByLabelText("Missing tracks")).toHaveTextContent("0");
    expect(screen.getByLabelText("Affected playlists")).toHaveTextContent("0");
    expect(screen.getByLabelText("High priority")).toHaveTextContent("0");
  });
});
