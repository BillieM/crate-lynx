import { render, screen } from "@testing-library/react";

import { PlaylistTrackRow } from "./PlaylistTrackRow";
import type { PlaylistTrack } from "./queries";

function buildTrack(overrides: Partial<PlaylistTrack> = {}): PlaylistTrack {
  return {
    id: 81,
    provider_track_id: "ytm-track-81",
    local_track_id: 22,
    proposal_id: 54,
    final_link_id: 88,
    position: 7,
    status: "pending",
    title: "Night Shift",
    artist: "The Midnight",
    album: "Nocturnal",
    duration_ms: 245000,
    ...overrides,
  };
}

describe("PlaylistTrackRow", () => {
  it("renders track metadata and action slot content", () => {
    render(<PlaylistTrackRow actionSlot={<button type="button">Review</button>} track={buildTrack()} />);

    expect(screen.getByRole("status", { name: "Pending track" })).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("Night Shift")).toBeInTheDocument();
    expect(screen.getByText("The Midnight")).toBeInTheDocument();
    expect(screen.getByText("Nocturnal")).toBeInTheDocument();
    expect(screen.getByText("4:05")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review" })).toBeInTheDocument();
  });

  it("renders fallbacks when album or duration are missing", () => {
    render(
      <PlaylistTrackRow
        track={buildTrack({
          album: null,
          duration_ms: null,
          status: "unlinked",
        })}
      />,
    );

    expect(screen.getByRole("status", { name: "Unlinked track" })).toBeInTheDocument();
    expect(screen.getByText("Single / unknown release")).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });
});
