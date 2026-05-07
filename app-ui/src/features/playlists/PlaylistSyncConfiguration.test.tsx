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

    if ((url === "/api/streaming/playlists/12" || url === "/api/streaming/playlists/31") && init?.method === "PATCH") {
      const requestBody = JSON.parse(String(init.body)) as { selected_for_sync: boolean };
      const playlist = response.playlists.find((candidate) => url.endsWith(`/${candidate.id}`));

      return {
        ok: true,
        json: async () => ({ ...playlist, selected_for_sync: requestBody.selected_for_sync }),
      } as Response;
    }

    if ((url === "/api/streaming/playlists/12/sync" || url === "/api/streaming/playlists/31/sync") && init?.method === "POST") {
      const playlistId = Number(url.split("/").at(-2));

      return {
        ok: true,
        json: async () => ({ job_id: `playlist-sync-${playlistId}`, playlist_id: playlistId }),
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
    expect(screen.getByRole("columnheader", { name: /Provider ID/ })).toBeInTheDocument();
    expect(screen.getByText("PL31")).toBeInTheDocument();
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

  it("queues enabled sync and metadata refresh actions with visible status", async () => {
    const fetchMock = mockConfigFetch();

    renderPlaylistSyncConfiguration();

    fireEvent.click(await screen.findByRole("button", { name: "Sync enabled" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts/4/sync", { method: "POST" });
    });
    expect(await screen.findByText("Enabled playlist sync queued.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh playlist metadata" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts/4/refresh-metadata", { method: "POST" });
    });
    expect(await screen.findByText("Metadata refresh queued.")).toBeInTheDocument();
  });

  it("runs bulk enable, disable, and row sync actions for selected rows", async () => {
    const fetchMock = mockConfigFetch();

    renderPlaylistSyncConfiguration();

    await screen.findByRole("cell", { name: "Fresh Discoveries" });
    expect(screen.queryByRole("button", { name: /Enable sync/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("checkbox", { name: /^Select row/ })[1]);

    expect(screen.getByRole("button", { name: /Enable sync/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Disable sync/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Sync rows/ })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: /Enable sync/ }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists/31", {
        body: JSON.stringify({ selected_for_sync: true }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "PATCH",
      });
    });
    expect(await screen.findByText("1 playlist was enabled.")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("checkbox", { name: /^Select row/ })[0]);
    fireEvent.click(screen.getByRole("button", { name: /Disable sync/ }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists/12", {
        body: JSON.stringify({ selected_for_sync: false }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "PATCH",
      });
    });
    expect(await screen.findByText("1 playlist was disabled.")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("checkbox", { name: /^Select row/ })[0]);
    fireEvent.click(screen.getByRole("button", { name: /Sync rows/ }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists/12/sync", { method: "POST" });
    });
    expect(await screen.findByText("1 playlist was queued for sync.")).toBeInTheDocument();
  });
});
