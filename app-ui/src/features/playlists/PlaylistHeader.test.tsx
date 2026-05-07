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
    last_sync_error: null,
    last_sync_error_at: null,
    ...overrides,
  };
}

describe("PlaylistHeader", () => {
  it("renders the compact toolbar with title, sync time, and status counts", () => {
    render(<PlaylistHeader playlist={buildPlaylist()} />);

    expect(screen.getByRole("region", { name: "Playlist toolbar" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Late Night Drive" })).toBeInTheDocument();
    expect(screen.getByText(/Synced/)).toHaveTextContent(/May 1/);
    expect(screen.getByText("Linked")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("Unlinked")).toBeInTheDocument();
    expect(screen.getByText("58")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders the first sync fallback without cover art", () => {
    render(<PlaylistHeader playlist={buildPlaylist({ cover_art_url: null, synced_at: null })} />);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByText("Awaiting first sync")).toBeInTheDocument();
  });

  it("surfaces the last sync error string and timestamp when present", () => {
    render(
      <PlaylistHeader
        playlist={buildPlaylist({
          last_sync_error: "Malformed playlist payload",
          last_sync_error_at: "2026-05-02T10:30:00Z",
        })}
      />,
    );

    expect(screen.getByText("Last sync error")).toBeInTheDocument();
    expect(screen.getByText("Malformed playlist payload")).toBeInTheDocument();
    expect(screen.getByText(/Failed/)).toHaveTextContent(/May 2/);
  });
});
