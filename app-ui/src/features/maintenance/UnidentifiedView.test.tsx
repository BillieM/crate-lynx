import { render, screen, within } from "@testing-library/react";

import { UnidentifiedView } from "./UnidentifiedView";

describe("UnidentifiedView", () => {
  it("renders Beets-failed tracks with filenames and fingerprint hashes", () => {
    render(<UnidentifiedView />);

    const summary = screen.getByLabelText("Unidentified summary");
    expect(within(summary).getByLabelText("Failed imports")).toHaveTextContent("3");
    expect(within(summary).getByLabelText("Fingerprinted")).toHaveTextContent("3");

    const trackList = screen.getByRole("region", { name: "Unidentified tracks" });
    expect(within(trackList).getByRole("heading", { name: "Beets failed track list" })).toBeInTheDocument();
    expect(within(trackList).getByText("3 rows")).toBeInTheDocument();
    expect(within(trackList).getAllByRole("status", { name: "Beets failed track" })).toHaveLength(3);
    expect(within(trackList).getByText("unknown-import-9a4f.mp3")).toBeInTheDocument();
    expect(within(trackList).getByText("fp_7d91c2a8e4b0")).toBeInTheDocument();
    expect(within(trackList).getByText("ingestion/failed/unknown-import-9a4f.mp3")).toBeInTheDocument();
    expect(within(trackList).getByText("side-b-live-rip.flac")).toBeInTheDocument();
    expect(within(trackList).getByText("fp_2c0f88b4aa17")).toBeInTheDocument();
    expect(within(trackList).getByText("cassette-transfer-03.wav")).toBeInTheDocument();
    expect(within(trackList).getByText("fp_b62e14d973c5")).toBeInTheDocument();
  });

  it("renders rescue actions disabled until endpoint wiring is implemented", () => {
    render(<UnidentifiedView />);

    expect(screen.getByRole("button", { name: "Rescue unknown-import-9a4f.mp3" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Rescue side-b-live-rip.flac" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Rescue cassette-transfer-03.wav" })).toBeDisabled();
  });
});
