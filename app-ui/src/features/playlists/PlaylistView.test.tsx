import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { PropsWithChildren, ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import { createMockApi, jsonResponse } from "../../test/mockApi";
import { PlaylistView } from "./PlaylistView";
import type { PlaylistDetailResponse, PlaylistTracksResponse } from "./queries";

const playlistDetailResponse: PlaylistDetailResponse = {
  playlist: {
    account_id: 4,
    cover_art_url: "https://cdn.example.test/cover.jpg",
    id: 12,
    last_sync_error: null,
    last_sync_error_at: null,
    linked_count: 1,
    name: "Late Night Drive",
    pending_count: 1,
    provider_playlist_id: "PL12",
    synced_at: "2026-05-01T09:00:00Z",
    track_count: 3,
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
  deleteHandler = () => jsonResponse({ final_link_id: 9001, status: "deleted" }),
  tracksResponse = playlistTracksResponse,
}: {
  deleteHandler?: () => Response;
  tracksResponse?: PlaylistTracksResponse;
} = {}) {
  return createMockApi()
    .get("/api/playlists/12", () => jsonResponse(playlistDetailResponse))
    .get("/api/playlists/12/tracks", () => jsonResponse(tracksResponse))
    .get("/api/streaming/playlists", () => jsonResponse({ playlists: [] }))
    .get("/api/streaming/accounts", () =>
      jsonResponse({
        accounts: [
          {
            auth_error: null,
            auth_error_at: null,
            auth_state: "connected",
            created_at: "2026-05-01T09:00:00Z",
            display_name: "YouTube Music",
            id: 4,
            provider: "youtube_music",
            updated_at: "2026-05-01T09:00:00Z",
          },
        ],
      }),
    )
    .delete("/api/final-links/9001", deleteHandler)
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

  it("opens the local track drawer for a linked row action", async () => {
    mockPlaylistApi();

    renderWithProviders(<PlaylistView isActive playlistResourceId={12} />);

    fireEvent.click(await screen.findByRole("button", { name: "Linked" }));

    expect(await screen.findByRole("dialog", { name: "Track #501" })).toBeInTheDocument();
    expect(await screen.findByText(/Frame Delay\/Night Runner\.mp3/)).toBeInTheDocument();
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
