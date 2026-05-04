import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App, { asRgb, getProgressColor, lerp, mixColors } from "./App";
import type {
  PlaylistDetailResponse,
  PlaylistTracksResponse,
  StreamingPlaylistConfigResponse,
  StreamingPlaylistsResponse,
} from "./features/playlists/queries";

const playlistDetailResponse: PlaylistDetailResponse = {
  playlist: {
    id: 12,
    account_id: 4,
    provider_playlist_id: "PL12",
    name: "Late Night Drive",
    cover_art_url: "https://cdn.example.test/late-night-drive.jpg",
    track_count: 62,
    linked_count: 58,
    pending_count: 3,
    unlinked_count: 1,
    synced_at: "2026-05-01T09:00:00Z",
    last_sync_error: null,
    last_sync_error_at: null,
  },
};

const playlistTracksResponse: PlaylistTracksResponse = {
  tracks: [
    {
      id: 101,
      provider_track_id: "ytm-101",
      position: 1,
      title: "Night Runner",
      artist: "Frame Delay",
      album: "Late Night Drive",
      duration_ms: 214000,
      status: "linked",
      local_track_id: 501,
      proposal_id: null,
      final_link_id: 9001,
    },
    {
      id: 102,
      provider_track_id: "ytm-102",
      position: 2,
      title: "Pending Signal",
      artist: "Static Gate",
      album: null,
      duration_ms: 188000,
      status: "pending",
      local_track_id: null,
      proposal_id: 44,
      final_link_id: null,
    },
    {
      id: 103,
      provider_track_id: "ytm-103",
      position: 3,
      title: "Loose Cable",
      artist: "Patch Bay",
      album: "Maintenance Window",
      duration_ms: null,
      status: "unlinked",
      local_track_id: 503,
      proposal_id: null,
      final_link_id: null,
    },
  ],
};

const secondaryPlaylistFixtures = [
  { id: 9, name: "Static Bloom", trackTitle: "Bloom Protocol", viewId: "playlist-9" },
  { id: 14, name: "Afterglow", trackTitle: "Afterimage Delay", viewId: "playlist-14" },
  { id: 18, name: "Signal Loss", trackTitle: "Packet Fade", viewId: "playlist-18" },
  { id: 27, name: "Chrome Hearts", trackTitle: "Mirror Finish", viewId: "playlist-27" },
] as const;

const streamingPlaylistsResponse: StreamingPlaylistsResponse = {
  playlists: [
    {
      id: 12,
      account_id: 4,
      provider_playlist_id: "PL12",
      title: "Late Night Drive",
      track_count: 62,
      synced_at: "2026-05-01T09:00:00Z",
    },
    ...secondaryPlaylistFixtures.map(({ id, name }) => ({
      id,
      account_id: id + 100,
      provider_playlist_id: `PL${id}`,
      title: name,
      track_count: 1,
      synced_at: "2026-05-01T09:00:00Z",
    })),
  ],
};
const streamingPlaylistConfigResponse: StreamingPlaylistConfigResponse = {
  playlists: [
    {
      ...streamingPlaylistsResponse.playlists[0],
      selected_for_sync: true,
      last_sync_error: null,
      last_sync_error_at: null,
    },
    {
      id: 31,
      account_id: 4,
      provider_playlist_id: "PL31",
      title: "Fresh Discoveries",
      track_count: 0,
      synced_at: null,
      selected_for_sync: false,
      last_sync_error: "Malformed playlist payload",
      last_sync_error_at: "2026-05-02T10:30:00Z",
    },
  ],
};
const selectedPlaylistSyncEndpoint = "/api/streaming/accounts/4/sync";
const selectedPlaylistSyncResponse = { account_id: 4, job_id: "selected-playlists-sync-job-4" };
const activePlaylistSyncEndpoint = (playlistId: number | string) => `/api/streaming/playlists/${playlistId}/sync`;
const metadataRefreshEndpoint = "/api/streaming/accounts/4/refresh-metadata";
const metadataRefreshResponse = { account_id: 4, job_id: "metadata-refresh-job-4" };

type MockPlaylistFetchOptions = {
  activeSyncHandler?: () => Promise<Response> | Response;
  metadataRefreshHandler?: () => Promise<Response> | Response;
  selectedSyncHandler?: () => Promise<Response> | Response;
};

function failUnexpectedFetch(url: string, init?: RequestInit): never {
  throw new Error(`Unexpected fetch request: ${init?.method ?? "GET"} ${url}`);
}

function buildPlaylistDetail(id: number, name: string): PlaylistDetailResponse {
  return {
    playlist: {
      ...playlistDetailResponse.playlist,
      id,
      account_id: id + 100,
      provider_playlist_id: `PL${id}`,
      name,
      cover_art_url: `https://cdn.example.test/${id}.jpg`,
      track_count: 1,
      linked_count: 1,
      pending_count: 0,
      unlinked_count: 0,
    },
  };
}

function buildPlaylistTracks(id: number, title: string): PlaylistTracksResponse {
  return {
    tracks: [
      {
        ...playlistTracksResponse.tracks[0],
        id: id * 100,
        provider_track_id: `ytm-${id}`,
        title,
        album: `${title} Album`,
      },
    ],
  };
}

function mockPlaylistFetch({ activeSyncHandler, metadataRefreshHandler, selectedSyncHandler }: MockPlaylistFetchOptions = {}) {
  const playlistDetailsById = new Map<string, typeof playlistDetailResponse>([
    ["12", playlistDetailResponse],
    ...secondaryPlaylistFixtures.map(({ id, name }) => [String(id), buildPlaylistDetail(id, name)] as const),
  ]);
  const playlistTracksById = new Map<string, typeof playlistTracksResponse>([
    ["12", playlistTracksResponse],
    ...secondaryPlaylistFixtures.map(({ id, trackTitle }) => [String(id), buildPlaylistTracks(id, trackTitle)] as const),
  ]);

  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const playlistEndpointMatch = url.match(/^\/api\/playlists\/(\d+)(\/tracks|\/m3u)?$/);

    if (url === "/api/streaming/playlists") {
      return {
        ok: true,
        json: async () => streamingPlaylistsResponse,
      } as Response;
    }

    if (url === "/api/streaming/playlists/config") {
      return {
        ok: true,
        json: async () => streamingPlaylistConfigResponse,
      } as Response;
    }

    if (url === "/api/streaming/playlists/31" && init?.method === "PATCH") {
      return {
        ok: true,
        json: async () => ({
          ...streamingPlaylistConfigResponse.playlists[1],
          selected_for_sync: true,
        }),
      } as Response;
    }

    if (url === "/api/streaming/playlists/12" && init?.method === "PATCH") {
      return {
        ok: true,
        json: async () => ({
          ...streamingPlaylistConfigResponse.playlists[0],
          selected_for_sync: false,
        }),
      } as Response;
    }

    if (playlistEndpointMatch) {
      const [, playlistId, suffix] = playlistEndpointMatch;

      if (suffix === "/m3u") {
        const playlistName = playlistDetailsById.get(playlistId)?.playlist.name ?? "Playlist";

        return {
          ok: true,
          blob: async () => new Blob(["#EXTM3U\n/library/night-runner.flac\n"], { type: "audio/x-mpegurl" }),
          headers: new Headers({
            "Content-Disposition": `attachment; filename="${playlistName}.m3u"`,
          }),
        } as Response;
      }

      if (suffix === "/tracks") {
        return {
          ok: true,
          json: async () => playlistTracksById.get(playlistId) ?? playlistTracksResponse,
        } as Response;
      }

      return {
        ok: true,
        json: async () => playlistDetailsById.get(playlistId) ?? playlistDetailResponse,
      } as Response;
    }

    if (url === selectedPlaylistSyncEndpoint && init?.method === "POST") {
      if (selectedSyncHandler) {
        return selectedSyncHandler();
      }

      return {
        ok: true,
        json: async () => selectedPlaylistSyncResponse,
      } as Response;
    }

    const activePlaylistSyncMatch = url.match(/^\/api\/streaming\/playlists\/(\d+)\/sync$/);
    if (activePlaylistSyncMatch && init?.method === "POST") {
      if (activeSyncHandler) {
        return activeSyncHandler();
      }

      const [, playlistId] = activePlaylistSyncMatch;
      return {
        ok: true,
        json: async () => ({ playlist_id: Number(playlistId), job_id: `playlist-sync-job-${playlistId}` }),
      } as Response;
    }

    if (url === metadataRefreshEndpoint && init?.method === "POST") {
      if (metadataRefreshHandler) {
        return metadataRefreshHandler();
      }

      return {
        ok: true,
        json: async () => metadataRefreshResponse,
      } as Response;
    }

    failUnexpectedFetch(url, init);
  });
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

describe("App", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders the fixed-height shell container, sidebar scaffold, and topbar", async () => {
    mockPlaylistFetch();
    const { container } = renderApp();

    expect(container.firstChild).toHaveClass("flex", "flex-1", "flex-row", "overflow-hidden", "bg-ctp-base", "text-ctp-text");

    const shell = container.querySelector(".bg-ctp-base");

    expect(shell).toHaveClass("flex", "flex-1", "flex-row", "overflow-hidden", "bg-ctp-base", "text-ctp-text");

    const sidebar = screen.getByRole("complementary");

    expect(sidebar).toHaveClass("w-[220px]", "bg-ctp-mantle", "border-r", "border-ctp-surface0");
    expect(screen.getByText("MUSEBRIDGE")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Search tracks, artists, playlists")).toBeInTheDocument();
    expect(screen.getByText("Maintenance")).toBeInTheDocument();
    expect(screen.getAllByText("YouTube Music").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Local Library")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Link proposals/i })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Late Night Drive/i })).toBeInTheDocument();
    expect(screen.getByText("62")).toBeInTheDocument();
    expect(screen.getByText("312")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    expect(screen.getAllByText("YouTube Music")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Configure sync" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync" })).toBeInTheDocument();

    for (const viewId of [
      "proposals",
      "unidentified",
      "missing",
      "playlists",
      "playlist-12",
      "playlist-9",
      "playlist-14",
      "playlist-18",
      "playlist-27",
      "library",
    ]) {
      expect(document.getElementById(viewId)).toBeInTheDocument();
    }
  });

  it("updates the topbar config when a playlist nav item is selected", async () => {
    mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("button", { name: /Late Night Drive/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(document.getElementById("playlist-12")).toHaveAttribute("data-view-active", "true");
    });

    fireEvent.click(screen.getByRole("button", { name: /Link proposals/i }));

    expect(screen.getByRole("heading", { name: "Link proposals" })).toBeInTheDocument();
    expect(screen.getByText("Needs approval")).toBeInTheDocument();
    expect(document.getElementById("proposals")).toHaveAttribute("data-view-active", "true");
    expect(document.getElementById("playlist-12")).toHaveAttribute("data-view-active", "false");

    fireEvent.click(screen.getByRole("button", { name: /Late Night Drive/i }));

    expect(screen.getByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Late Night Drive/i })).toBeInTheDocument();
    expect(screen.getAllByText("YouTube Music")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Configure sync" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export M3U" })).toBeInTheDocument();
    expect(document.getElementById("proposals")).toHaveAttribute("data-view-active", "false");
    expect(document.getElementById("playlist-12")).toHaveAttribute("data-view-active", "true");
  });

  it("opens the YouTube Music sync configuration shell from the topbar", async () => {
    mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Fresh Discoveries/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Configure sync" }));

    expect(screen.getByRole("heading", { level: 1, name: "YouTube Music" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Playlist sync configuration" })).toBeInTheDocument();
    expect(await screen.findByText("1 of 2 discovered playlists selected for sync.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Late Night Drive" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Fresh Discoveries" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Late Night Drive for sync" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Fresh Discoveries for sync" })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Refresh playlist metadata" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync" })).not.toBeInTheDocument();
    expect(screen.getByText("Provider ID PL31 / Account 4")).toBeInTheDocument();
    expect(screen.getByText("Malformed playlist payload")).toBeInTheDocument();
    expect(document.getElementById("playlists")).toHaveAttribute("data-view-active", "true");
    expect(document.getElementById("playlist-12")).toHaveAttribute("data-view-active", "false");
    expect(screen.queryByRole("button", { name: "Configure sync" })).not.toBeInTheDocument();
  });

  it("updates playlist sync selections and refreshes sidebar and config queries", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Configure sync" }));

    const playlistListFetchesBeforeToggle = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/streaming/playlists",
    ).length;
    const configFetchesBeforeToggle = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/streaming/playlists/config",
    ).length;

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select Late Night Drive for sync" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists/12", {
        body: JSON.stringify({ selected_for_sync: false }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "PATCH",
      });
    });

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select Fresh Discoveries for sync" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists/31", {
        body: JSON.stringify({ selected_for_sync: true }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "PATCH",
      });
    });
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(([input]) => String(input) === "/api/streaming/playlists").length,
      ).toBeGreaterThan(playlistListFetchesBeforeToggle);
      expect(
        fetchMock.mock.calls.filter(([input]) => String(input) === "/api/streaming/playlists/config").length,
      ).toBeGreaterThan(configFetchesBeforeToggle);
    });
  });

  it("queues a playlist metadata refresh and refreshes sidebar and config queries", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Configure sync" }));

    const playlistListFetchesBeforeRefresh = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/streaming/playlists",
    ).length;
    const configFetchesBeforeRefresh = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/streaming/playlists/config",
    ).length;

    fireEvent.click(await screen.findByRole("button", { name: "Refresh playlist metadata" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(metadataRefreshEndpoint, {
        method: "POST",
      });
    });
    expect(await screen.findByText("Metadata refresh queued.")).toBeInTheDocument();
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(([input]) => String(input) === "/api/streaming/playlists").length,
      ).toBeGreaterThan(playlistListFetchesBeforeRefresh);
      expect(
        fetchMock.mock.calls.filter(([input]) => String(input) === "/api/streaming/playlists/config").length,
      ).toBeGreaterThan(configFetchesBeforeRefresh);
    });
  });

  it("shows success state when selected playlist sync is queued", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Configure sync" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sync selected" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(selectedPlaylistSyncEndpoint, {
        method: "POST",
      });
    });
    expect(await screen.findByText("Selected playlist sync queued.")).toBeInTheDocument();
  });

  it("shows pending state while selected playlist sync is running", async () => {
    let resolveSync: (response: Response) => void = () => {};
    const syncPromise = new Promise<Response>((resolve) => {
      resolveSync = resolve;
    });
    mockPlaylistFetch({
      selectedSyncHandler: () => syncPromise,
    });

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Configure sync" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sync selected" }));

    expect(await screen.findByRole("button", { name: "Syncing selected..." })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Syncing selected playlists...");

    resolveSync({
      ok: true,
      json: async () => selectedPlaylistSyncResponse,
    } as Response);

    expect(await screen.findByText("Selected playlist sync queued.")).toBeInTheDocument();
  });

  it("shows an error state when selected playlist sync fails", async () => {
    mockPlaylistFetch({
      selectedSyncHandler: () =>
        ({
          ok: false,
          status: 500,
        }) as Response,
    });

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Configure sync" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sync selected" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Selected playlist sync failed.");
    expect(screen.getByRole("button", { name: "Sync selected" })).toBeEnabled();
  });

  it("shows pending state while playlist metadata refresh is running", async () => {
    let resolveRefresh: (response: Response) => void = () => {};
    const refreshPromise = new Promise<Response>((resolve) => {
      resolveRefresh = resolve;
    });
    mockPlaylistFetch({
      metadataRefreshHandler: () => refreshPromise,
    });

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Configure sync" }));
    fireEvent.click(await screen.findByRole("button", { name: "Refresh playlist metadata" }));

    expect(await screen.findByRole("button", { name: "Refreshing..." })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Refreshing playlist metadata...");

    resolveRefresh({
      ok: true,
      json: async () => metadataRefreshResponse,
    } as Response);

    expect(await screen.findByText("Metadata refresh queued.")).toBeInTheDocument();
  });

  it("shows an error state when playlist metadata refresh fails", async () => {
    mockPlaylistFetch({
      metadataRefreshHandler: () =>
        ({
          ok: false,
          status: 500,
        }) as Response,
    });

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Configure sync" }));
    fireEvent.click(await screen.findByRole("button", { name: "Refresh playlist metadata" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Metadata refresh failed.");
    expect(screen.getByRole("button", { name: "Refresh playlist metadata" })).toBeEnabled();
  });

  it("opens the first synced playlist by default", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: "Late Night Drive cover art" })).toBeInTheDocument();
    expect(document.getElementById("playlist-12")).toHaveAttribute("data-view-active", "true");
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12");
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12/tracks");
  });

  it("renders the playlist view inside the active playlist shell", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("img", { name: "Late Night Drive cover art" })).toBeInTheDocument();
    expect(screen.getByText("Playlist overview")).toBeInTheDocument();
    expect(screen.getByText("58 / 62")).toBeInTheDocument();
    expect(screen.getByText("Night Runner")).toBeInTheDocument();
    expect(screen.getByText("Pending Signal")).toBeInTheDocument();
    expect(screen.getByText("Loose Cable")).toBeInTheDocument();
    expect(screen.getByText("Showing 3 of 3 tracks")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12");
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12/tracks");
  });

  it("renders secondary playlist shells with their configured playlist resources", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    for (const playlist of secondaryPlaylistFixtures) {
      fireEvent.click(await screen.findByRole("button", { name: new RegExp(playlist.name, "i") }));

      expect(await screen.findByRole("img", { name: `${playlist.name} cover art` })).toBeInTheDocument();
      expect(screen.getByRole("heading", { level: 2, name: playlist.name })).toBeInTheDocument();
      expect(screen.getByText(playlist.trackTitle)).toBeInTheDocument();
      expect(screen.getByText("Showing 1 of 1 tracks")).toBeInTheDocument();
      expect(document.getElementById(playlist.viewId)).toHaveAttribute("data-view-active", "true");
      expect(fetchMock).toHaveBeenCalledWith(`/api/playlists/${playlist.id}`);
      expect(fetchMock).toHaveBeenCalledWith(`/api/playlists/${playlist.id}/tracks`);
    }
  });

  it("routes users to configure sync when no selected playlists exist", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url === "/api/streaming/playlists") {
        return {
          ok: true,
          json: async () => ({ playlists: [] }),
        } as Response;
      }

      if (url === "/api/streaming/playlists/config") {
        return {
          ok: true,
          json: async () => ({ playlists: [] }),
        } as Response;
      }

      failUnexpectedFetch(url);
    });

    renderApp();

    expect(await screen.findByRole("heading", { name: "No selected playlists" })).toBeInTheDocument();
    expect(screen.getByText("No selected playlists. Configure YouTube Music sync to choose playlists.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Configure sync" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync" })).not.toBeInTheDocument();
    expect(document.getElementById("playlists")).toHaveAttribute("data-view-active", "true");
  });

  it("queues a YouTube Music sync for the active playlist from the topbar", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /Static Bloom/i }));

    const syncButton = await screen.findByRole("button", { name: "Sync" });
    await waitFor(() => {
      expect(syncButton).toBeEnabled();
    });

    fireEvent.click(syncButton);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(activePlaylistSyncEndpoint(9), { method: "POST" });
    });
    expect(fetchMock).not.toHaveBeenCalledWith(selectedPlaylistSyncEndpoint, { method: "POST" });
    expect(await screen.findByText("Playlist sync queued.")).toBeInTheDocument();
  });

  it("shows pending state while active playlist sync is running", async () => {
    let resolveSync: (response: Response) => void = () => {};
    const syncPromise = new Promise<Response>((resolve) => {
      resolveSync = resolve;
    });

    mockPlaylistFetch({
      activeSyncHandler: () => syncPromise,
    });

    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /Late Night Drive/i }));

    const syncButton = await screen.findByRole("button", { name: "Sync" });
    await waitFor(() => {
      expect(syncButton).toBeEnabled();
    });

    fireEvent.click(syncButton);

    expect(await screen.findByText("Syncing playlist...")).toHaveAttribute("role", "status");
    expect(screen.getByRole("button", { name: "Syncing..." })).toBeDisabled();

    resolveSync({
      ok: true,
      json: async () => ({ playlist_id: 12, job_id: "playlist-sync-job-12" }),
    } as Response);

    expect(await screen.findByText("Playlist sync queued.")).toBeInTheDocument();
  });

  it("shows an error state when active playlist sync fails", async () => {
    mockPlaylistFetch({
      activeSyncHandler: () =>
        ({
          ok: false,
          status: 503,
        }) as Response,
    });

    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /Late Night Drive/i }));

    const syncButton = await screen.findByRole("button", { name: "Sync" });
    await waitFor(() => {
      expect(syncButton).toBeEnabled();
    });

    fireEvent.click(syncButton);

    expect(await screen.findByRole("alert")).toHaveTextContent("Playlist sync failed.");
    expect(screen.getByRole("button", { name: "Sync" })).toBeEnabled();
  });

  it("downloads an M3U export from the active playlist topbar", async () => {
    const fetchMock = mockPlaylistFetch();
    const createObjectUrlMock = vi.fn(() => "blob:playlist-export");
    const revokeObjectUrlMock = vi.fn();
    const clickMock = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    Object.defineProperty(window.URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrlMock,
    });
    Object.defineProperty(window.URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectUrlMock,
    });

    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /Late Night Drive/i }));

    const exportButton = await screen.findByRole("button", { name: "Export M3U" });
    fireEvent.click(exportButton);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12/m3u");
    });

    expect(await screen.findByText("M3U ready.")).toBeInTheDocument();
    expect(createObjectUrlMock).toHaveBeenCalledWith(expect.any(Blob));
    expect(clickMock).toHaveBeenCalled();
    expect(revokeObjectUrlMock).toHaveBeenCalledWith("blob:playlist-export");
  });

  it("filters playlist tracks by status", async () => {
    mockPlaylistFetch();

    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /Late Night Drive/i }));

    expect(await screen.findByText("Night Runner")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Pending/i }));

    expect(screen.getByText("Pending Signal")).toBeInTheDocument();
    expect(screen.queryByText("Night Runner")).not.toBeInTheDocument();
    expect(screen.queryByText("Loose Cable")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 1 of 3 tracks")).toBeInTheDocument();
  });

  it("debounces sidebar search requests and renders compact results", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url === "/api/streaming/playlists") {
        return {
          ok: true,
          json: async () => ({ playlists: [] }),
        } as Response;
      }

      if (url === "/api/streaming/playlists/config") {
        return {
          ok: true,
          json: async () => ({ playlists: [] }),
        } as Response;
      }

      if (url === "/api/search?q=mix") {
        return {
          ok: true,
          json: async () => ({
            query: "mix",
            results: [
              {
                id: 1,
                kind: "playlist",
                title: "Morning Mix",
                subtitle: "Playlist • 12 tracks",
                route_path: "/youtube-music",
              },
              {
                id: 2,
                kind: "local_track",
                title: "Mixdown.mp3",
                subtitle: "Local file • Artist/Mixdown.mp3",
                route_path: "/local-library",
              },
            ],
          }),
        } as Response;
      }

      failUnexpectedFetch(url);
    });

    renderApp();

    fireEvent.change(screen.getByPlaceholderText("Search tracks, artists, playlists"), {
      target: { value: "mix" },
    });

    expect(fetchMock).not.toHaveBeenCalledWith("/api/search?q=mix");

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/search?q=mix");
    });

    expect(await screen.findByText("Morning Mix")).toBeInTheDocument();
    expect(screen.getByText("Mixdown.mp3")).toBeInTheDocument();
    expect(screen.getByText("Playlist")).toBeInTheDocument();
    expect(screen.getByText("Local")).toBeInTheDocument();
  });

  it("fails playlist UI tests on unsupported playlist API routes", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();

    await expect(fetch("/api/playlists")).rejects.toThrow("Unexpected fetch request: GET /api/playlists");
    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists");
  });

  it("interpolates scalar values with rounding", () => {
    expect(lerp(10, 20, 0.45)).toBe(15);
  });

  it("mixes RGB colors channel by channel", () => {
    expect(
      mixColors(
        { red: 10, green: 20, blue: 30 },
        { red: 40, green: 80, blue: 120 },
        0.5,
      ),
    ).toEqual({ red: 25, green: 50, blue: 75 });
  });

  it("maps progress percentages onto the Catppuccin gradient", () => {
    expect(getProgressColor(-10)).toEqual({ red: 108, green: 112, blue: 134 });
    expect(getProgressColor(50)).toEqual({ red: 249, green: 226, blue: 175 });
    expect(getProgressColor(100)).toEqual({ red: 166, green: 227, blue: 161 });
  });

  it("formats rgba strings with optional alpha", () => {
    expect(asRgb({ red: 1, green: 2, blue: 3 })).toBe("rgba(1, 2, 3, 1)");
    expect(asRgb({ red: 1, green: 2, blue: 3 }, 0.4)).toBe("rgba(1, 2, 3, 0.4)");
  });
});
