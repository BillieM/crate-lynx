import { fireEvent, render, screen } from "@testing-library/react";

import { FilterChips } from "./FilterChips";
import { filterPlaylistTracks, getPlaylistTrackFilterCounts, type PlaylistTrackFilter } from "./filterTracks";
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

describe("FilterChips", () => {
  it("renders status filter chips with counts and selected state", () => {
    render(
      <FilterChips
        activeFilter="pending"
        counts={{ all: 4, linked: 1, pending: 2, unlinked: 1 }}
        onFilterChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("group", { name: "Track status filters" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All 4" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Linked 1" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Pending 2" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Unlinked 1" })).toHaveAttribute("aria-pressed", "false");
  });

  it("notifies when a chip is selected", () => {
    const onFilterChange = vi.fn<(filter: PlaylistTrackFilter) => void>();

    render(<FilterChips activeFilter="all" onFilterChange={onFilterChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Unlinked" }));

    expect(onFilterChange).toHaveBeenCalledWith("unlinked");
  });

  it("filters tracks by status client-side", () => {
    const tracks = [
      buildTrack({ id: 1, status: "linked", title: "Linked track" }),
      buildTrack({ id: 2, status: "pending", title: "Pending track" }),
      buildTrack({ id: 3, status: "unlinked", title: "Unlinked track" }),
    ];

    expect(filterPlaylistTracks(tracks, "all")).toEqual(tracks);
    expect(filterPlaylistTracks(tracks, "linked")).toEqual([tracks[0]]);
    expect(filterPlaylistTracks(tracks, "pending")).toEqual([tracks[1]]);
    expect(filterPlaylistTracks(tracks, "unlinked")).toEqual([tracks[2]]);
  });

  it("counts tracks for each filter", () => {
    const tracks = [
      buildTrack({ id: 1, status: "linked" }),
      buildTrack({ id: 2, status: "pending" }),
      buildTrack({ id: 3, status: "pending" }),
      buildTrack({ id: 4, status: "unlinked" }),
    ];

    expect(getPlaylistTrackFilterCounts(tracks)).toEqual({
      all: 4,
      linked: 1,
      pending: 2,
      unlinked: 1,
    });
  });
});
