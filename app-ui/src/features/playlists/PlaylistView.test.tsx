import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { PropsWithChildren, ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import { createMockApi, jsonResponse } from "../../test/mockApi";
import type { StreamingAccount } from "../streamingAccounts/queries";
import { PlaylistView } from "./PlaylistView";
import type { PlaylistDetailResponse, PlaylistTracksResponse } from "./queries";

const connectedStreamingAccount: StreamingAccount = {
  auth_error: null,
  auth_error_at: null,
  auth_state: "connected",
  created_at: "2026-05-01T09:00:00Z",
  display_name: "YouTube Music",
  id: 4,
  provider: "youtube_music",
  updated_at: "2026-05-01T09:00:00Z",
};

const authErrorStreamingAccount: StreamingAccount = {
  ...connectedStreamingAccount,
  auth_error: "Browser headers expired.",
  auth_error_at: "2026-05-02T10:30:00+00:00",
  auth_state: "connected",
  updated_at: "2026-05-02T10:30:00Z",
};

const playlistDetailResponse: PlaylistDetailResponse = {
  playlist: {
    account_id: 4,
    cover_art_url: "https://cdn.example.test/cover.jpg",
    id: 12,
    last_sync_error: null,
    last_sync_error_at: null,
    linked_count: 1,
    metadata_synced_at: "2026-05-01T08:55:00Z",
    name: "Late Night Drive",
    pending_count: 1,
    provider_track_count: 3,
    provider_playlist_id: "PL12",
    sync_mode: "full",
    imported_track_count: 3,
    tracks_synced_at: "2026-05-01T09:00:00Z",
    unlinked_count: 1,
  },
};

const playlistTracksResponse: PlaylistTracksResponse = {
  tracks: [
    {
      album: "Late Night Drive",
      artist: "Frame Delay",
      duration_ms: 214000,
      final_link_id: 9001,
      id: 101,
      local_track_id: 501,
      position: 1,
      proposal_id: null,
      provider_track_id: "ytm-101",
      status: "linked",
      title: "Night Runner",
    },
    {
      album: null,
      artist: "Static Gate",
      duration_ms: 188000,
      final_link_id: null,
      id: 102,
      local_track_id: null,
      position: 2,
      proposal_id: 44,
      provider_track_id: "ytm-102",
      status: "pending",
      title: "Pending Signal",
    },
    {
      album: "Maintenance Window",
      artist: "Patch Bay",
      duration_ms: null,
      final_link_id: null,
      id: 103,
      local_track_id: null,
      position: 3,
      proposal_id: null,
      provider_track_id: "ytm-103",
      status: "unlinked",
      title: "Loose Cable",
    },
  ],
};

function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  function Wrapper({ children }: PropsWithChildren) {
    return (
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </MemoryRouter>
    );
  }

  return render(ui, { wrapper: Wrapper });
}

function mockPlaylistApi({
  deleteHandler = () =>
    jsonResponse({
      final_link_id: 9001,
      rejected_at: "2026-05-03T12:00:00+00:00",
      rejected_suggestion_id: 7001,
      status: "rejected",
    }),
  detailResponse = playlistDetailResponse,
  accounts = [connectedStreamingAccount],
  tracksResponse = playlistTracksResponse,
}: {
  accounts?: StreamingAccount[];
  deleteHandler?: () => Response;
  detailResponse?: PlaylistDetailResponse;
  tracksResponse?: PlaylistTracksResponse;
} = {}) {
  return createMockApi()
    .get("/api/playlists/12", () => jsonResponse(detailResponse))
    .get("/api/playlists/12/tracks", () => jsonResponse(tracksResponse))
    .get("/api/streaming/playlists", () => jsonResponse({ playlists: [] }))
    .get("/api/streaming/accounts", () => jsonResponse({ accounts }))
    .delete("/api/final-links/9001", deleteHandler)
    .get("/api/streaming/tracks/101", () =>
      jsonResponse({
        album: "Late Night Drive",
        artist: "Frame Delay",
        duration_ms: 214000,
        equivalent_tracks: [],
        id: 101,
        isrc: "USFD1260001",
        pending_local_suggestions: [],
        playlist_appearances: [
          {
            account_id: 4,
            playlist_id: 12,
            position: 1,
            provider_playlist_id: "PL12",
            sync_mode: "full",
            title: "Late Night Drive",
          },
        ],
        provider_track_id: "ytm-101",
        relationships: [],
        resolved_local_link: {
          approved_at: "2026-05-01T09:00:00Z",
          final_link_id: 9001,
          local_track: {
            album: "Late Night Drive",
            artist: "Frame Delay",
            file_path: "/library/Frame Delay/Night Runner.mp3",
            id: 501,
            library_root_rel_path: "Frame Delay/Night Runner.mp3",
            title: "Night Runner",
          },
          local_track_id: 501,
          resolution_source: "direct",
          source_streaming_track_id: 101,
        },
        title: "Night Runner",
        year: 2026,
      }),
    )
    .get("/api/local-tracks/501", () =>
      jsonResponse({
        failed_ingestion_attempts: [],
        file_path: "/library/Frame Delay/Night Runner.mp3",
        final_link: {
          approved_at: "2026-05-01T09:00:00Z",
          id: 9001,
          streaming_track_id: 101,
        },
        id: 501,
        library_root_rel_path: "Frame Delay/Night Runner.mp3",
        link_status: "linked",
        pending_suggestions: [],
      }),
    )
    .mockFetch();
}

describe("PlaylistView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders playlist tracks as a responsive dense table with the compact toolbar", async () => {
    mockPlaylistApi();

    renderWithProviders(<PlaylistView isActive playlistResourceId={12} />);

    expect(await screen.findByRole("region", { name: "Playlist toolbar" })).toBeInTheDocument();

    const trackRegion = screen.getByRole("region", { name: "Playlist tracks" });
    expect(within(trackRegion).getByRole("columnheader", { name: /Album/ })).toHaveClass("hidden", "md:table-cell");
    expect(within(trackRegion).getByRole("columnheader", { name: /Provider ID/ })).toHaveClass("hidden", "lg:table-cell");
    expect(within(trackRegion).getByText("Night Runner")).toBeInTheDocument();
    expect(within(trackRegion).getByText("Frame Delay")).toBeInTheDocument();
    expect(within(trackRegion).getByText("Late Night Drive")).toBeInTheDocument();
    expect(within(trackRegion).getByText("3:34")).toBeInTheDocument();
    expect(within(trackRegion).getByText("ytm-101")).toBeInTheDocument();
  });

  it("keeps the pending review action reachable", async () => {
    mockPlaylistApi();

    renderWithProviders(<PlaylistView isActive playlistResourceId={12} />);

    const trackRegion = await screen.findByRole("region", { name: "Playlist tracks" });
    expect(within(trackRegion).getByRole("button", { name: "Review" })).toBeInTheDocument();
  });

  it("filters playlist rows through the table and clears selected rows", async () => {
    mockPlaylistApi();

    renderWithProviders(<PlaylistView isActive playlistResourceId={12} />);

    expect(await screen.findByText("Showing 3 of 3 tracks")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 1" }));
    expect(screen.getByText("1 row selected")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Pending 1" }));

    expect(await screen.findByText("Showing 1 of 3 tracks")).toBeInTheDocument();
    expect(screen.getByText("Pending Signal")).toBeInTheDocument();
    expect(screen.queryByText("Night Runner")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "All 3" }));

    expect(await screen.findByText("Night Runner")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText("1 row selected")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("checkbox", { name: "Select row 1" })).not.toBeChecked();
  });

  it("opens the streaming track drawer for a linked row action", async () => {
    mockPlaylistApi();

    renderWithProviders(<PlaylistView isActive playlistResourceId={12} />);

    fireEvent.click(await screen.findByRole("button", { name: "Linked" }));

    const dialog = await screen.findByRole("dialog", { name: "Night Runner" });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText("ytm-101")).toBeInTheDocument();
  });

  it("renders account auth errors alongside playlist sync errors", async () => {
    mockPlaylistApi({
      accounts: [authErrorStreamingAccount],
      detailResponse: {
        playlist: {
          ...playlistDetailResponse.playlist,
          last_sync_error: "Playlist response reported logged_in: 0",
          last_sync_error_at: "2026-05-02T10:31:00Z",
        },
      },
    });

    renderWithProviders(<PlaylistView isActive playlistResourceId={12} />);

    expect(await screen.findByText("YouTube Music authentication needs attention")).toBeInTheDocument();
    expect(screen.getByText(/^Browser headers expired\. Reported .+\.$/)).toBeInTheDocument();
    expect(screen.getByText("Last sync error")).toBeInTheDocument();
    expect(screen.getByText("Playlist response reported logged_in: 0")).toBeInTheDocument();
  });

  it("unlinks selected linked rows and renders aggregate success feedback", async () => {
    const fetchMock = mockPlaylistApi();

    renderWithProviders(<PlaylistView isActive playlistResourceId={12} />);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select row 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Unlink" }));

    expect(await screen.findByText("Bulk unlink complete")).toBeInTheDocument();
    expect(screen.getByText("1 link was removed.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/final-links/9001", { method: "DELETE" });
  });

  it("renders partial failure feedback for bulk unlink errors", async () => {
    mockPlaylistApi({
      deleteHandler: () => jsonResponse({ detail: "failed" }, { status: 500 }),
    });

    renderWithProviders(<PlaylistView isActive playlistResourceId={12} />);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select row 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Unlink" }));

    await waitFor(() => {
      expect(screen.getByText("Bulk unlink partially failed")).toBeInTheDocument();
    });
    expect(screen.getByText("0 links were removed and 1 row failed.")).toBeInTheDocument();
  });
});
