import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { soulseekQueryKeys } from "../soulseek/queryKeys";
import {
  streamingAccountQueryKeys,
  useStreamingAccountsQuery,
  type StreamingAccount,
} from "../streamingAccounts/queries";
import { PlaylistSyncConfiguration } from "./PlaylistSyncConfiguration";
import {
  playlistQueryKeys,
  type StreamingPlaylistConfigResponse,
  type StreamingPlaylistsResponse,
  useStreamingPlaylistsQuery,
} from "./queries";

type PlaylistSyncMode = StreamingPlaylistConfigResponse["playlists"][number]["sync_mode"];
type PlaylistConfigRow = StreamingPlaylistConfigResponse["playlists"][number];
type PlaylistPatchHandler = ({
  playlist,
  syncMode,
  url,
}: {
  playlist: PlaylistConfigRow;
  syncMode: PlaylistSyncMode;
  url: string;
}) => Promise<Response> | Response;

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
  auth_state: "error",
  updated_at: "2026-05-02T10:30:00Z",
};

const playlistConfigResponse: StreamingPlaylistConfigResponse = {
  playlists: [
    {
      account_id: 4,
      id: 12,
      last_sync_error: null,
      last_sync_error_at: null,
      imported_track_count: 62,
      metadata_synced_at: "2026-05-01T08:55:00Z",
      provider_playlist_id: "PL12",
      provider_track_count: 70,
      sync_mode: "full",
      title: "Late Night Drive",
      tracks_synced_at: "2026-05-01T09:00:00Z",
    },
    {
      account_id: 4,
      id: 31,
      last_sync_error: "Malformed playlist payload",
      last_sync_error_at: "2026-05-02T10:30:00Z",
      imported_track_count: 0,
      metadata_synced_at: null,
      provider_playlist_id: "PL31",
      provider_track_count: 12,
      sync_mode: "off",
      title: "Fresh Discoveries",
      tracks_synced_at: null,
    },
    {
      account_id: 4,
      id: 44,
      last_sync_error: null,
      last_sync_error_at: null,
      imported_track_count: 9,
      metadata_synced_at: "2026-05-01T09:10:00Z",
      provider_playlist_id: "PL44",
      provider_track_count: 18,
      sync_mode: "match_only",
      title: "Matcher Seeds",
      tracks_synced_at: "2026-05-01T09:20:00Z",
    },
  ],
};

function SyncRefreshObservers() {
  useStreamingAccountsQuery();
  useStreamingPlaylistsQuery();

  return null;
}

function renderPlaylistSyncConfiguration({ includeSyncRefreshObservers = false } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  queryClient.setQueryData(playlistQueryKeys.list(), {
    playlists: playlistConfigResponse.playlists.filter((playlist) => playlist.sync_mode === "full"),
  });
  queryClient.setQueryData(soulseekQueryKeys.queue(), { items: [] });

  const result = render(
    <QueryClientProvider client={queryClient}>
      {includeSyncRefreshObservers ? <SyncRefreshObservers /> : null}
      <PlaylistSyncConfiguration />
    </QueryClientProvider>,
  );

  return { queryClient, ...result };
}

function mockConfigFetch(
  response: StreamingPlaylistConfigResponse = playlistConfigResponse,
  {
    accounts = [connectedStreamingAccount],
    patchHandler,
  }: { accounts?: StreamingAccount[] | (() => StreamingAccount[]); patchHandler?: PlaylistPatchHandler } = {},
) {
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
          playlists: response.playlists.filter((playlist) => playlist.sync_mode === "full"),
        }),
      } as Response;
    }

    if (url === "/api/streaming/accounts" && init?.method === undefined) {
      const accountRows = typeof accounts === "function" ? accounts() : accounts;

      return {
        ok: true,
        json: async () => ({ accounts: accountRows }),
      } as Response;
    }

    if (/^\/api\/streaming\/playlists\/\d+$/.test(url) && init?.method === "PATCH") {
      const requestBody = JSON.parse(String(init.body)) as { sync_mode: PlaylistSyncMode };
      const playlist = response.playlists.find((candidate) => url.endsWith(`/${candidate.id}`));

      if (playlist === undefined) {
        throw new Error(`Unexpected playlist PATCH URL: ${url}`);
      }

      if (patchHandler !== undefined) {
        return patchHandler({ playlist, syncMode: requestBody.sync_mode, url });
      }

      return {
        ok: true,
        json: async () => ({ ...playlist, sync_mode: requestBody.sync_mode }),
      } as Response;
    }

    if (/^\/api\/streaming\/playlists\/\d+\/sync$/.test(url) && init?.method === "POST") {
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

function createDeferredResponse() {
  let resolve: (response: Response) => void = () => {};
  const promise = new Promise<Response>((resolvePromise) => {
    resolve = resolvePromise;
  });

  return { promise, resolve };
}

function countFetches(fetchMock: ReturnType<typeof mockConfigFetch>, url: string) {
  return fetchMock.mock.calls.filter(([input]) => String(input) === url).length;
}

async function flushAsyncWork() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

async function advanceTimers(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("PlaylistSyncConfiguration", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders discovered playlists with mode controls, summary counts, split columns, and last sync errors", async () => {
    mockConfigFetch();

    renderPlaylistSyncConfiguration();

    expect(await screen.findByRole("heading", { level: 2, name: "Playlist sync configuration" })).toBeInTheDocument();
    expect(screen.getByText("3 discovered")).toBeInTheDocument();
    expect(screen.getByText("1 full sync")).toBeInTheDocument();
    expect(screen.getByText("1 match only")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync Full + Match" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh playlist metadata" })).toBeInTheDocument();
    const fullModeControl = screen.getByRole("group", { name: "Sync mode for Late Night Drive" });
    expect(within(fullModeControl).getByRole("button", { name: "Full sync" })).toHaveAttribute("aria-pressed", "true");
    const offModeControl = screen.getByRole("group", { name: "Sync mode for Fresh Discoveries" });
    expect(within(offModeControl).getByRole("button", { name: "Off" })).toHaveAttribute("aria-pressed", "true");
    const matchModeControl = screen.getByRole("group", { name: "Sync mode for Matcher Seeds" });
    expect(within(matchModeControl).getByRole("button", { name: "Match only" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("columnheader", { name: /YouTube count/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Imported/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Metadata refreshed/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Tracks synced/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Provider ID/ })).toBeInTheDocument();
    expect(screen.getByText("PL31")).toBeInTheDocument();
    expect(screen.getByText("Malformed playlist payload")).toBeInTheDocument();
  });

  it("renders playlist sync rows without row checkboxes or selected-row action bar", async () => {
    mockConfigFetch();

    renderPlaylistSyncConfiguration();

    expect(await screen.findByRole("cell", { name: "Fresh Discoveries" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Select all visible rows" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /^Select row/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/rows? selected/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear selection" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Set Off/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Set Match only/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Set Full sync/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Sync active rows/ })).not.toBeInTheDocument();
  });

  it("searches and filters discovered playlists with a recoverable filtered-empty state", async () => {
    mockConfigFetch();

    renderPlaylistSyncConfiguration();

    await screen.findByRole("cell", { name: "Fresh Discoveries" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search playlists" }), {
      target: { value: "matcher" },
    });

    expect(screen.getByText("1 of 3 rows")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Matcher Seeds" })).toBeInTheDocument();
    expect(screen.queryByRole("cell", { name: "Fresh Discoveries" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Sync mode"), { target: { value: "full" } });

    expect(screen.getByRole("heading", { name: "No matching playlists" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(screen.getByText("3 of 3 rows")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Fresh Discoveries" })).toBeInTheDocument();
  });

  it("queues metadata refresh from an empty playlist configuration when an account exists", async () => {
    const fetchMock = mockConfigFetch({ playlists: [] });

    renderPlaylistSyncConfiguration();

    expect(await screen.findByRole("heading", { name: "No playlists discovered" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh playlist metadata" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts/4/refresh-metadata", { method: "POST" });
    });
    expect(await screen.findByText("Metadata refresh queued.")).toBeInTheDocument();
  });

  it("links empty playlist configuration to authentication settings when no account exists", async () => {
    mockConfigFetch({ playlists: [] }, { accounts: [] });

    renderPlaylistSyncConfiguration();

    expect(await screen.findByRole("heading", { name: "No playlists discovered" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Authentication" })).toHaveAttribute("href", "/settings/authentication");
  });

  it("patches playlist sync mode with cache updates instead of refetching the config list", async () => {
    const fetchMock = mockConfigFetch();

    const { queryClient } = renderPlaylistSyncConfiguration();

    const modeControl = await screen.findByRole("group", { name: "Sync mode for Fresh Discoveries" });
    const configFetchCountBeforeToggle = countFetches(fetchMock, "/api/streaming/playlists/config");

    fireEvent.click(within(modeControl).getByRole("button", { name: "Match only" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists/31", {
        body: JSON.stringify({ sync_mode: "match_only" }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "PATCH",
      });
    });
    await waitFor(() => {
      const refreshedModeControl = screen.getByRole("group", { name: "Sync mode for Fresh Discoveries" });
      expect(within(refreshedModeControl).getByRole("button", { name: "Match only" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(countFetches(fetchMock, "/api/streaming/playlists/config")).toBe(configFetchCountBeforeToggle);
      expect(queryClient.getQueryState(playlistQueryKeys.config())?.isInvalidated).not.toBe(true);
      expect(queryClient.getQueryState(soulseekQueryKeys.queue())?.isInvalidated).not.toBe(true);
    });
    expect(
      queryClient
        .getQueryData<StreamingPlaylistConfigResponse>(playlistQueryKeys.config())
        ?.playlists.find((playlist) => playlist.id === 31)?.sync_mode,
    ).toBe("match_only");
  });

  it("keeps the table rendered while a mode patch is pending and after it succeeds", async () => {
    const deferredPatch = createDeferredResponse();
    let pendingPatch: { playlist: PlaylistConfigRow; syncMode: PlaylistSyncMode } | undefined;
    const fetchMock = mockConfigFetch(playlistConfigResponse, {
      patchHandler: ({ playlist, syncMode }) => {
        pendingPatch = { playlist, syncMode };
        return deferredPatch.promise;
      },
    });

    renderPlaylistSyncConfiguration();

    const modeControl = await screen.findByRole("group", { name: "Sync mode for Fresh Discoveries" });
    const table = screen.getByRole("table");
    const row = screen.getByRole("cell", { name: "Fresh Discoveries" }).closest("tr");

    fireEvent.click(within(modeControl).getByRole("button", { name: "Match only" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists/31", {
        body: JSON.stringify({ sync_mode: "match_only" }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "PATCH",
      });
    });
    expect(screen.getByRole("region", { name: "Playlist sync configuration list" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Fresh Discoveries" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBe(table);
    expect(screen.getByRole("cell", { name: "Fresh Discoveries" }).closest("tr")).toBe(row);
    await waitFor(() => {
      const refreshedModeControl = screen.getByRole("group", { name: "Sync mode for Fresh Discoveries" });
      expect(within(refreshedModeControl).getByRole("button", { name: "Updating..." })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });

    await act(async () => {
      if (pendingPatch === undefined) {
        throw new Error("Expected a pending playlist mode PATCH");
      }

      const resolvedPatch = pendingPatch;
      deferredPatch.resolve({
        ok: true,
        json: async () => ({ ...resolvedPatch.playlist, sync_mode: resolvedPatch.syncMode }),
      } as Response);
      await deferredPatch.promise;
    });

    await waitFor(() => {
      const refreshedModeControl = screen.getByRole("group", { name: "Sync mode for Fresh Discoveries" });
      expect(within(refreshedModeControl).getByRole("button", { name: "Match only" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    expect(screen.getByRole("cell", { name: "Fresh Discoveries" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBe(table);
    expect(screen.getByRole("cell", { name: "Fresh Discoveries" }).closest("tr")).toBe(row);
  });

  it("rolls back a failed mode patch and shows a table-level error", async () => {
    const fetchMock = mockConfigFetch(playlistConfigResponse, {
      patchHandler: () =>
        ({
          ok: false,
          status: 500,
        }) as Response,
    });

    const { queryClient } = renderPlaylistSyncConfiguration();

    const modeControl = await screen.findByRole("group", { name: "Sync mode for Fresh Discoveries" });
    const configFetchCountBeforeToggle = countFetches(fetchMock, "/api/streaming/playlists/config");

    fireEvent.click(within(modeControl).getByRole("button", { name: "Match only" }));

    expect(await screen.findByText("Playlist mode update failed")).toBeInTheDocument();
    expect(
      screen.getByText("The playlist mode could not be saved. The table was restored to its previous state."),
    ).toBeInTheDocument();
    const refreshedModeControl = screen.getByRole("group", { name: "Sync mode for Fresh Discoveries" });
    expect(within(refreshedModeControl).getByRole("button", { name: "Off" })).toHaveAttribute("aria-pressed", "true");
    expect(countFetches(fetchMock, "/api/streaming/playlists/config")).toBe(configFetchCountBeforeToggle);
    expect(
      queryClient
        .getQueryData<StreamingPlaylistConfigResponse>(playlistQueryKeys.config())
        ?.playlists.find((playlist) => playlist.id === 31)?.sync_mode,
    ).toBe("off");
    expect(
      queryClient
        .getQueryData<StreamingPlaylistsResponse>(playlistQueryKeys.list())
        ?.playlists.some((playlist) => playlist.id === 31),
    ).toBe(false);
  });

  it("adds and removes full playlists in the full-playlist cache after mode patches", async () => {
    mockConfigFetch();

    const { queryClient } = renderPlaylistSyncConfiguration();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const offModeControl = await screen.findByRole("group", { name: "Sync mode for Fresh Discoveries" });

    fireEvent.click(within(offModeControl).getByRole("button", { name: "Full sync" }));

    await waitFor(() => {
      expect(
        queryClient
          .getQueryData<StreamingPlaylistsResponse>(playlistQueryKeys.list())
          ?.playlists.find((playlist) => playlist.id === 31)?.sync_mode,
      ).toBe("full");
    });
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: soulseekQueryKeys.all });
    });
    invalidateSpy.mockClear();

    const fullModeControl = screen.getByRole("group", { name: "Sync mode for Late Night Drive" });

    fireEvent.click(within(fullModeControl).getByRole("button", { name: "Off" }));

    await waitFor(() => {
      expect(
        queryClient
          .getQueryData<StreamingPlaylistsResponse>(playlistQueryKeys.list())
          ?.playlists.some((playlist) => playlist.id === 12),
      ).toBe(false);
    });
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: soulseekQueryKeys.all });
    });
  });

  it("keeps the full-playlist cache object unchanged for off and match-only mode changes", async () => {
    mockConfigFetch();

    const { queryClient } = renderPlaylistSyncConfiguration();

    await screen.findByRole("group", { name: "Sync mode for Fresh Discoveries" });
    const initialFullPlaylistCache = queryClient.getQueryData<StreamingPlaylistsResponse>(playlistQueryKeys.list());

    fireEvent.click(
      within(screen.getByRole("group", { name: "Sync mode for Fresh Discoveries" })).getByRole("button", {
        name: "Match only",
      }),
    );

    await waitFor(() => {
      expect(
        within(screen.getByRole("group", { name: "Sync mode for Fresh Discoveries" })).getByRole("button", {
          name: "Match only",
        }),
      ).toHaveAttribute("aria-pressed", "true");
    });
    expect(queryClient.getQueryData<StreamingPlaylistsResponse>(playlistQueryKeys.list())).toBe(initialFullPlaylistCache);

    fireEvent.click(
      within(screen.getByRole("group", { name: "Sync mode for Matcher Seeds" })).getByRole("button", {
        name: "Off",
      }),
    );

    await waitFor(() => {
      expect(
        within(screen.getByRole("group", { name: "Sync mode for Matcher Seeds" })).getByRole("button", {
          name: "Off",
        }),
      ).toHaveAttribute("aria-pressed", "true");
    });
    expect(queryClient.getQueryData<StreamingPlaylistsResponse>(playlistQueryKeys.list())).toBe(initialFullPlaylistCache);
  });

  it("queues enabled sync and metadata refresh actions with visible status", async () => {
    const fetchMock = mockConfigFetch();

    renderPlaylistSyncConfiguration();

    fireEvent.click(await screen.findByRole("button", { name: "Sync Full + Match" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts/4/sync", { method: "POST" });
    });
    expect(await screen.findByText("Full + Match playlist sync queued.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh playlist metadata" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts/4/refresh-metadata", { method: "POST" });
    });
    expect(await screen.findByText("Metadata refresh queued.")).toBeInTheDocument();
  });

  it("surfaces account auth errors and disables sync controls", async () => {
    mockConfigFetch(playlistConfigResponse, { accounts: [authErrorStreamingAccount] });

    renderPlaylistSyncConfiguration();

    expect(await screen.findByText("YouTube Music authentication needs attention")).toBeInTheDocument();
    expect(screen.getByText(/^Browser headers expired\. Reported .+\.$/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Refresh authentication" })).toHaveAttribute(
      "href",
      "/settings/authentication",
    );
    expect(screen.getByRole("button", { name: "Sync Full + Match" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Refresh playlist metadata" })).toBeDisabled();
  });

  it("delays sidebar and config refetches after enabled sync and metadata refresh queue", async () => {
    const fetchMock = mockConfigFetch();

    renderPlaylistSyncConfiguration({ includeSyncRefreshObservers: true });

    await screen.findByRole("button", { name: "Sync Full + Match" });
    vi.useFakeTimers();

    const listFetchesBeforeSyncQueued = countFetches(fetchMock, "/api/streaming/playlists");
    const configFetchesBeforeSyncQueued = countFetches(fetchMock, "/api/streaming/playlists/config");
    const accountFetchesBeforeSyncQueued = countFetches(fetchMock, "/api/streaming/accounts");

    fireEvent.click(screen.getByRole("button", { name: "Sync Full + Match" }));
    await flushAsyncWork();

    expect(screen.getByText("Full + Match playlist sync queued.")).toBeInTheDocument();
    expect(countFetches(fetchMock, "/api/streaming/playlists")).toBe(listFetchesBeforeSyncQueued);
    expect(countFetches(fetchMock, "/api/streaming/playlists/config")).toBe(configFetchesBeforeSyncQueued);
    expect(countFetches(fetchMock, "/api/streaming/accounts")).toBe(accountFetchesBeforeSyncQueued);
    const listFetchesAfterSyncQueued = countFetches(fetchMock, "/api/streaming/playlists");
    const configFetchesAfterSyncQueued = countFetches(fetchMock, "/api/streaming/playlists/config");
    const accountFetchesAfterSyncQueued = countFetches(fetchMock, "/api/streaming/accounts");

    await advanceTimers(3000);

    expect(countFetches(fetchMock, "/api/streaming/playlists")).toBeGreaterThan(listFetchesAfterSyncQueued);
    expect(countFetches(fetchMock, "/api/streaming/playlists/config")).toBeGreaterThan(configFetchesAfterSyncQueued);
    expect(countFetches(fetchMock, "/api/streaming/accounts")).toBeGreaterThan(accountFetchesAfterSyncQueued);

    const listFetchesAfterFirstDelay = countFetches(fetchMock, "/api/streaming/playlists");
    const configFetchesAfterFirstDelay = countFetches(fetchMock, "/api/streaming/playlists/config");
    const accountFetchesAfterFirstDelay = countFetches(fetchMock, "/api/streaming/accounts");

    await advanceTimers(7000);

    expect(countFetches(fetchMock, "/api/streaming/playlists")).toBeGreaterThan(listFetchesAfterFirstDelay);
    expect(countFetches(fetchMock, "/api/streaming/playlists/config")).toBeGreaterThan(configFetchesAfterFirstDelay);
    expect(countFetches(fetchMock, "/api/streaming/accounts")).toBeGreaterThan(accountFetchesAfterFirstDelay);

    const listFetchesBeforeRefreshQueued = countFetches(fetchMock, "/api/streaming/playlists");
    const configFetchesBeforeRefreshQueued = countFetches(fetchMock, "/api/streaming/playlists/config");
    const accountFetchesBeforeRefreshQueued = countFetches(fetchMock, "/api/streaming/accounts");

    fireEvent.click(screen.getByRole("button", { name: "Refresh playlist metadata" }));
    await flushAsyncWork();

    expect(screen.getByText("Metadata refresh queued.")).toBeInTheDocument();
    expect(countFetches(fetchMock, "/api/streaming/playlists")).toBe(listFetchesBeforeRefreshQueued);
    expect(countFetches(fetchMock, "/api/streaming/playlists/config")).toBe(configFetchesBeforeRefreshQueued);
    expect(countFetches(fetchMock, "/api/streaming/accounts")).toBe(accountFetchesBeforeRefreshQueued);
    const listFetchesAfterRefreshQueued = countFetches(fetchMock, "/api/streaming/playlists");
    const configFetchesAfterRefreshQueued = countFetches(fetchMock, "/api/streaming/playlists/config");
    const accountFetchesAfterRefreshQueued = countFetches(fetchMock, "/api/streaming/accounts");

    await advanceTimers(3000);

    expect(countFetches(fetchMock, "/api/streaming/playlists")).toBeGreaterThan(listFetchesAfterRefreshQueued);
    expect(countFetches(fetchMock, "/api/streaming/playlists/config")).toBeGreaterThan(configFetchesAfterRefreshQueued);
    expect(countFetches(fetchMock, "/api/streaming/accounts")).toBeGreaterThan(accountFetchesAfterRefreshQueued);

    const listFetchesAfterRefreshFirstDelay = countFetches(fetchMock, "/api/streaming/playlists");
    const configFetchesAfterRefreshFirstDelay = countFetches(fetchMock, "/api/streaming/playlists/config");
    const accountFetchesAfterRefreshFirstDelay = countFetches(fetchMock, "/api/streaming/accounts");

    await advanceTimers(7000);

    expect(countFetches(fetchMock, "/api/streaming/playlists")).toBeGreaterThan(listFetchesAfterRefreshFirstDelay);
    expect(countFetches(fetchMock, "/api/streaming/playlists/config")).toBeGreaterThan(configFetchesAfterRefreshFirstDelay);
    expect(countFetches(fetchMock, "/api/streaming/accounts")).toBeGreaterThan(accountFetchesAfterRefreshFirstDelay);
  });

  it("shows refetched account auth errors after delayed sync invalidation", async () => {
    let hasAuthError = false;
    const fetchMock = mockConfigFetch(playlistConfigResponse, {
      accounts: () => [hasAuthError ? authErrorStreamingAccount : connectedStreamingAccount],
    });

    const { queryClient } = renderPlaylistSyncConfiguration();

    await screen.findByRole("button", { name: "Sync Full + Match" });
    vi.useFakeTimers();

    fireEvent.click(screen.getByRole("button", { name: "Sync Full + Match" }));
    await flushAsyncWork();

    expect(screen.getByText("Full + Match playlist sync queued.")).toBeInTheDocument();
    expect(screen.queryByText("YouTube Music authentication needs attention")).not.toBeInTheDocument();
    const accountFetchesAfterQueued = countFetches(fetchMock, "/api/streaming/accounts");

    hasAuthError = true;
    await advanceTimers(3000);
    await flushAsyncWork();

    expect(countFetches(fetchMock, "/api/streaming/accounts")).toBeGreaterThan(accountFetchesAfterQueued);
    expect(queryClient.getQueryData(streamingAccountQueryKeys.list())).toEqual({ accounts: [authErrorStreamingAccount] });
    await flushAsyncWork();
    await advanceTimers(1);
    vi.useRealTimers();
    expect(await screen.findByText("YouTube Music authentication needs attention")).toBeInTheDocument();
    expect(screen.getByText(/^Browser headers expired\. Reported .+\.$/)).toBeInTheDocument();
  });

});
