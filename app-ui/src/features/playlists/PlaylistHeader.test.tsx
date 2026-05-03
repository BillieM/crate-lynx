import { render, screen } from "@testing-library/react";

import { PlaylistHeader } from "./PlaylistHeader";
import type { PlaylistDetail } from "./queries";

function buildPlaylist(overrides: Partial<PlaylistDetail> = {}): PlaylistDetail {
  return {
    id: 12,
    account_id: 4,
    provider_playlist_id: "PL12",
    name: "Late Night Drive",
    cover_art_url: "https://cdn.example.test/cover.jpg",
    track_count: 62,
    linked_count: 58,
    pending_count: 3,
    unlinked_count: 1,
    synced_at: "2026-05-01T09:00:00Z",
    ...overrides,
  };
}

describe("PlaylistHeader", () => {
  it("renders cover art, title, progress, and status counts", () => {
    render(<PlaylistHeader playlist={buildPlaylist()} />);

    expect(screen.getByRole("img", { name: "Late Night Drive cover art" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Late Night Drive" })).toBeInTheDocument();
    expect(screen.getByText("58 / 62")).toBeInTheDocument();
    expect(screen.getByText("Linked")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("Unlinked")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("falls back to the playlist glyph when cover art is missing", () => {
    render(<PlaylistHeader playlist={buildPlaylist({ cover_art_url: null, synced_at: null })} />);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("Awaiting first sync")).toBeInTheDocument();
  });
});
