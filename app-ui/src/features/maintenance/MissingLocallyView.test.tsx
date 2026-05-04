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
});
