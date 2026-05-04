import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { maintenanceQueryKeys } from "../maintenance/queries";
import { PlaylistSyncConfiguration } from "./PlaylistSyncConfiguration";
import { playlistQueryKeys, type StreamingPlaylistConfigResponse } from "./queries";

const playlistConfigResponse: StreamingPlaylistConfigResponse = {
  playlists: [
    {
      account_id: 4,
      id: 12,
      last_sync_error: null,
      last_sync_error_at: null,
      provider_playlist_id: "PL12",
      selected_for_sync: true,
      synced_at: "2026-05-01T09:00:00Z",
      title: "Late Night Drive",
      track_count: 62,
    },
    {
      account_id: 4,
      id: 31,
      last_sync_error: "Malformed playlist payload",
      last_sync_error_at: "2026-05-02T10:30:00Z",
      provider_playlist_id: "PL31",
      selected_for_sync: false,
      synced_at: null,
      title: "Fresh Discoveries",
      track_count: 0,
    },
  ],
};

function renderPlaylistSyncConfiguration() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  queryClient.setQueryData(playlistQueryKeys.list(), {
    playlists: playlistConfigResponse.playlists.filter((playlist) => playlist.selected_for_sync),
  });
  queryClient.setQueryData(maintenanceQueryKeys.missingLocally(), { tracks: [] });

  const result = render(
    <QueryClientProvider client={queryClient}>
      <PlaylistSyncConfiguration />
    </QueryClientProvider>,
  );

  return { queryClient, ...result };
}

function mockConfigFetch(response: StreamingPlaylistConfigResponse = playlistConfigResponse) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);

    if (url === "/api/streaming/playlists/config" && init?.method === undefined) {
      return {
        ok: true,
        json: async () => response,
      } as Response;
    }

    if (url === "/api/streaming/playlists" && init?.method === undefined) {
      return {
        ok: true,
        json: async () => ({
          playlists: response.playlists.filter((playlist) => playlist.selected_for_sync),
        }),
      } as Response;
    }

    if (url === "/api/streaming/playlists/31" && init?.method === "PATCH") {
      return {
        ok: true,
        json: async () => ({ ...response.playlists[1], selected_for_sync: true }),
      } as Response;
    }

    if (url === "/api/streaming/accounts/4/sync" && init?.method === "POST") {
      return {
        ok: true,
        json: async () => ({ account_id: 4, job_id: "selected-sync-4" }),
      } as Response;
    }

    if (url === "/api/streaming/accounts/4/refresh-metadata" && init?.method === "POST") {
      return {
        ok: true,
        json: async () => ({ account_id: 4, job_id: "metadata-refresh-4" }),
      } as Response;
    }

    throw new Error(`Unexpected fetch request: ${init?.method ?? "GET"} ${url}`);
  });
}

describe("PlaylistSyncConfiguration", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders discovered playlists with selection state and last sync errors", async () => {
    mockConfigFetch();

    renderPlaylistSyncConfiguration();

    expect(await screen.findByRole("heading", { level: 2, name: "Playlist sync configuration" })).toBeInTheDocument();
    expect(screen.getByText("1 of 2 discovered playlists selected for sync.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Late Night Drive for sync" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Fresh Discoveries for sync" })).not.toBeChecked();
    expect(screen.getByText("Provider ID PL31 / Account 4")).toBeInTheDocument();
    expect(screen.getByText("Malformed playlist payload")).toBeInTheDocument();
  });

  it("patches playlist selection and invalidates config, sidebar, and missing-locally queries", async () => {
    const fetchMock = mockConfigFetch();

    const { queryClient } = renderPlaylistSyncConfiguration();

    expect(await screen.findByRole("checkbox", { name: "Select Fresh Discoveries for sync" })).toBeInTheDocument();
    const configFetchCountBeforeToggle = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/streaming/playlists/config",
    ).length;

    fireEvent.click(screen.getByRole("checkbox", { name: "Select Fresh Discoveries for sync" }));

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
        fetchMock.mock.calls.filter(([input]) => String(input) === "/api/streaming/playlists/config").length,
      ).toBeGreaterThan(configFetchCountBeforeToggle);
      expect(queryClient.getQueryState(playlistQueryKeys.list())?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState(maintenanceQueryKeys.missingLocally())?.isInvalidated).toBe(true);
    });
  });

  it("queues selected sync and metadata refresh actions with visible status", async () => {
    const fetchMock = mockConfigFetch();

    renderPlaylistSyncConfiguration();

    fireEvent.click(await screen.findByRole("button", { name: "Sync selected" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts/4/sync", { method: "POST" });
    });
    expect(await screen.findByText("Selected playlist sync queued.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh playlist metadata" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts/4/refresh-metadata", { method: "POST" });
    });
    expect(await screen.findByText("Metadata refresh queued.")).toBeInTheDocument();
  });
});
