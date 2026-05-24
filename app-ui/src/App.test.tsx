import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import type { LibraryTracksResponse } from "./features/library/queries";
import type { MissingLocallyResponse, UnidentifiedResponse } from "./features/maintenance/queries";
import type {
  LinkProposalsResponse,
  M3uExportPreviewResponse,
  M3uExportProfileListResponse,
  PlaylistDetailResponse,
  PlaylistTracksResponse,
  StreamingPlaylistConfigResponse,
  StreamingPlaylistsResponse,
} from "./features/playlists/queries";
import type { StreamingRelationshipSuggestionsResponse } from "./features/relationships/queries";
import type {
  GeneratedPlaylistListResponse,
  PlaylistGenerationRunListResponse,
  SonicFeatureSummary,
} from "./features/sonic/queries";
import { getProgressColor } from "./features/shell/progress";
import { blobResponse, createMockApi, emptyResponse, failUnexpectedFetch, jsonResponse } from "./test/mockApi";

const playlistDetailResponse: PlaylistDetailResponse = {
  playlist: {
    id: 12,
    account_id: 4,
    provider_playlist_id: "PL12",
    name: "Late Night Drive",
    cover_art_url: "https://cdn.example.test/late-night-drive.jpg",
    sync_mode: "full",
    provider_track_count: 70,
    imported_track_count: 62,
    linked_count: 58,
    pending_count: 3,
    unlinked_count: 1,
    metadata_synced_at: "2026-05-01T08:55:00Z",
    tracks_synced_at: "2026-05-01T09:00:00Z",
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
      sync_mode: "full",
      provider_track_count: 70,
      imported_track_count: 62,
      metadata_synced_at: "2026-05-01T08:55:00Z",
      tracks_synced_at: "2026-05-01T09:00:00Z",
      last_sync_error: null,
      last_sync_error_at: null,
    },
    ...secondaryPlaylistFixtures.map(({ id, name }) => ({
      id,
      account_id: id + 100,
      provider_playlist_id: `PL${id}`,
      title: name,
      sync_mode: "full" as const,
      provider_track_count: 1,
      imported_track_count: 1,
      metadata_synced_at: "2026-05-01T08:55:00Z",
      tracks_synced_at: "2026-05-01T09:00:00Z",
      last_sync_error: null,
      last_sync_error_at: null,
    })),
  ],
};
const streamingPlaylistConfigResponse: StreamingPlaylistConfigResponse = {
  playlists: [
    {
      ...streamingPlaylistsResponse.playlists[0],
      last_sync_error: null,
      last_sync_error_at: null,
    },
    {
      id: 31,
      account_id: 4,
      provider_playlist_id: "PL31",
      title: "Fresh Discoveries",
      sync_mode: "off",
      provider_track_count: 12,
      imported_track_count: 0,
      metadata_synced_at: null,
      tracks_synced_at: null,
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
const linkProposalsResponse: LinkProposalsResponse = {
  limit: 50,
  next_cursor: null,
  proposals: [
    {
      id: 44,
      local_track_id: 501,
      local_album: "Private Archive",
      local_artist: "Frame Delay",
      local_file_path: "Frame Delay/Night Runner.mp3",
      local_title: "Night Runner File",
      streaming_track_id: 901,
      streaming_provider_track_id: "ytm-901",
      streaming_title: "Night Runner",
      streaming_artist: "Frame Delay",
      streaming_album: "Late Night Drive",
      match_method: "tag",
      score: 0.92,
      status: "pending",
      rejected_at: null,
      confidence_band: "high",
    },
    {
      id: 45,
      local_track_id: 502,
      local_album: null,
      local_artist: null,
      local_file_path: "Static Gate/Pending Signal.mp3",
      local_title: null,
      streaming_track_id: 902,
      streaming_provider_track_id: "ytm-902",
      streaming_title: "Pending Signal",
      streaming_artist: "Static Gate",
      streaming_album: null,
      match_method: "tag",
      score: 0.72,
      status: "pending",
      rejected_at: null,
      confidence_band: "medium",
    },
    {
      id: 46,
      local_track_id: 503,
      local_album: "Maintenance Window",
      local_artist: "Patch Bay",
      local_file_path: "Patch Bay/Loose Cable.mp3",
      local_title: "Loose Cable",
      streaming_track_id: 903,
      streaming_provider_track_id: "ytm-903",
      streaming_title: "Loose Cable",
      streaming_artist: "Patch Bay",
      streaming_album: "Maintenance Window",
      match_method: "tag",
      score: 0.44,
      status: "pending",
      rejected_at: null,
      confidence_band: "low",
    },
  ],
  returned_count: 3,
  total_count: 3,
};
const streamingRelationshipSuggestionsResponse: StreamingRelationshipSuggestionsResponse = {
  limit: 50,
  next_cursor: null,
  returned_count: 2,
  suggestions: [
    {
      id: 91,
      confidence: "high",
      conflict_state: "none",
      created_at: "2026-05-18T12:00:00Z",
      match_method: "isrc",
      relationship_type: "equivalent",
      score: 0.99,
      status: "pending",
      first_track: {
        id: 901,
        provider_track_id: "ytm:first-901",
        title: "Night Runner",
        artist: "Frame Delay",
        album: "Late Night Drive",
        year: 2024,
        isrc: "GBABC2400001",
        duration_ms: 214000,
      },
      second_track: {
        id: 902,
        provider_track_id: "ytm:second-902",
        title: "Night Runner",
        artist: "Frame Delay",
        album: "Private Archive",
        year: null,
        isrc: "GBABC2400001",
        duration_ms: 214400,
      },
      first_link: null,
      second_link: null,
      conflict: null,
    },
    {
      id: 92,
      confidence: "medium",
      conflict_state: "none",
      created_at: "2026-05-18T12:05:00Z",
      match_method: "fuzzy",
      relationship_type: "related",
      score: 0.73,
      status: "pending",
      first_track: {
        id: 903,
        provider_track_id: "ytm:first-903",
        title: "Loose Cable",
        artist: "Patch Bay",
        album: "Maintenance Window",
        year: null,
        isrc: null,
        duration_ms: null,
      },
      second_track: {
        id: 904,
        provider_track_id: "ytm:second-904",
        title: "Loose Cable Live",
        artist: "Patch Bay",
        album: "Live Diagnostics",
        year: null,
        isrc: null,
        duration_ms: 232000,
      },
      first_link: null,
      second_link: null,
      conflict: null,
    },
  ],
  total_count: 2,
};

const libraryTracksResponse: LibraryTracksResponse = {
  next_cursor: null,
  stats: {
    linked: 244,
    pending: 43,
    total: 321,
    unlinked: 25,
  },
  tracks: [
    {
      album: "Nocturnal",
      artist: "The Midnight",
      duration_ms: 245000,
      file_path: "/library/Synthwave/The Midnight/Nocturnal/Night Shift.mp3",
      file_status: "available",
      final_link_id: 9001,
      id: 1001,
      library_root_rel_path: "Synthwave/The Midnight/Nocturnal/Night Shift.mp3",
      link_status: "linked",
      match_method: "isrc",
      title: "Night Shift",
    },
  ],
};
const missingLocallyResponse: MissingLocallyResponse = {
  tracks: [
    {
      album: "Immunity",
      artist: "Jon Hopkins",
      duration_ms: 270000,
      id: 5001,
      playlist_count: 2,
      playlist_ids: [11, 12],
      playlist_titles: ["Late Night Drive", "Focus Queue"],
      provider_track_id: "ytm:VLPL_missing_018",
      title: "Open Eye Signal",
    },
  ],
};
const unidentifiedResponse: UnidentifiedResponse = {
  tracks: [
    {
      attempt_count: 3,
      can_rematch_local_track: false,
      can_rescue_metadata: false,
      failed_at: "2026-05-02T21:44:00Z",
      failure_reason: "Beets could not identify metadata",
      filename: "unknown-import-9a4f.mp3",
      first_failed_at: "2026-05-01T20:10:00Z",
      id: 4001,
      ignored_at: null,
      local_track_id: null,
      source_mtime_ns: 1746217040000000000,
      source_path: "ingestion/failed/unknown-import-9a4f.mp3",
      source_size: 3210,
    },
  ],
};
const generalSettingsResponse = {
  ingest_folders: [
    { id: 1, path: "/ingestion" },
    { id: 2, path: "/soulseek" },
  ],
};
const sonicFeatureSummaryResponse: SonicFeatureSummary = {
  failed_tracks: 0,
  missing_tracks: 2,
  pending_tracks: 1,
  ready_tracks: 58,
  total_tracks: 61,
};
const sonicRunsResponse: PlaylistGenerationRunListResponse = {
  runs: [
    {
      completed_at: "2026-05-24T12:00:00Z",
      created_at: "2026-05-24T11:55:00Z",
      error_detail: null,
      generation_config: {
        clustering_method: "kmeans",
        feature_profile: "balanced_v1",
        max_children: 4,
        max_depth: 2,
        min_playlist_size: 8,
        random_seed: 42,
        target_playlist_size: 25,
      },
      id: 501,
      playlist_count: 2,
      source_filter: {
        source_type: "all_local",
        streaming_playlist_ids: [],
        tag_filters: [],
      },
      status: "completed",
      track_count: 58,
      updated_at: "2026-05-24T12:00:00Z",
    },
  ],
};
const generatedPlaylistsResponse: GeneratedPlaylistListResponse = {
  playlists: [
    {
      created_at: "2026-05-24T12:00:00Z",
      depth: 0,
      id: 7001,
      name: "Fast Bright",
      parent_playlist_id: null,
      position: 1,
      run_id: 501,
      summary: { top_deltas: [] },
      track_count: 24,
    },
  ],
};
const m3uExportProfilesResponse: M3uExportProfileListResponse = {
  profiles: [
    {
      id: 1,
      is_default: true,
      library_path: "/mnt/music",
      name: "NAS",
    },
  ],
};
const m3uExportPreviewResponse: M3uExportPreviewResponse = {
  formats: ["m3u", "m3u8"],
  library_path: "/mnt/music",
  path_format: "file_url",
  playlist_count: 1,
  playlists: [
    {
      exported_track_count: 58,
      filename_m3u: "Late Night Drive [yt].m3u",
      filename_m3u8: "Late Night Drive [yt].m3u8",
      filenames: ["Late Night Drive [yt].m3u", "Late Night Drive [yt].m3u8"],
      generated_playlist_id: null,
      playlist_id: 12,
      sample_path: "file://localhost/mnt/music/Frame%20Delay/Night%20Runner.flac",
      skipped_track_count: 4,
      source: "streaming",
      title: "Late Night Drive",
    },
  ],
  total_exported_track_count: 58,
  total_skipped_track_count: 4,
};

type MockPlaylistFetchOptions = {
  activeSyncHandler?: () => Promise<Response> | Response;
  approveProposalHandler?: (proposalId: string) => Promise<Response> | Response;
  createIngestFolderHandler?: (init?: RequestInit) => Promise<Response> | Response;
  deleteIngestFolderHandler?: (folderId: string) => Promise<Response> | Response;
  generalSettingsHandler?: () => Promise<Response> | Response;
  linkProposalsHandler?: (url: string) => Promise<Response> | Response;
  m3uExportHandler?: (init?: RequestInit) => Promise<Response> | Response;
  m3uExportPreviewHandler?: (init?: RequestInit) => Promise<Response> | Response;
  m3uExportProfilesHandler?: () => Promise<Response> | Response;
  metadataRefreshHandler?: () => Promise<Response> | Response;
  rejectProposalHandler?: (proposalId: string) => Promise<Response> | Response;
  relationshipSuggestionsHandler?: (url: string) => Promise<Response> | Response;
  selectedSyncHandler?: () => Promise<Response> | Response;
};

function buildPlaylistDetail(id: number, name: string): PlaylistDetailResponse {
  return {
    playlist: {
      ...playlistDetailResponse.playlist,
      id,
      account_id: id + 100,
      provider_playlist_id: `PL${id}`,
      name,
      cover_art_url: `https://cdn.example.test/${id}.jpg`,
      provider_track_count: 1,
      imported_track_count: 1,
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

function mockPlaylistFetch({
  activeSyncHandler,
  approveProposalHandler,
  createIngestFolderHandler,
  deleteIngestFolderHandler,
  generalSettingsHandler,
  linkProposalsHandler,
  m3uExportHandler,
  m3uExportPreviewHandler,
  m3uExportProfilesHandler,
  metadataRefreshHandler,
  rejectProposalHandler,
  relationshipSuggestionsHandler,
  selectedSyncHandler,
}: MockPlaylistFetchOptions = {}) {
  const playlistDetailsById = new Map<string, typeof playlistDetailResponse>([
    ["12", playlistDetailResponse],
    ...secondaryPlaylistFixtures.map(({ id, name }) => [String(id), buildPlaylistDetail(id, name)] as const),
  ]);
  const playlistTracksById = new Map<string, typeof playlistTracksResponse>([
    ["12", playlistTracksResponse],
    ...secondaryPlaylistFixtures.map(({ id, trackTitle }) => [String(id), buildPlaylistTracks(id, trackTitle)] as const),
  ]);

  return createMockApi()
    .get("/api/streaming/playlists", () => jsonResponse(streamingPlaylistsResponse))
    .get("/api/streaming/playlists/config", () => jsonResponse(streamingPlaylistConfigResponse))
    .get(/^\/api\/streaming\/relationships\/suggestions(?:\?|$)/, ({ url }) =>
      relationshipSuggestionsHandler?.(url) ?? jsonResponse(streamingRelationshipSuggestionsResponse),
    )
    .get(/^\/api\/proposals(?:\?|$)/, ({ url }) => linkProposalsHandler?.(url) ?? jsonResponse(linkProposalsResponse))
    .get("/api/library/tracks", () => jsonResponse(libraryTracksResponse))
    .get("/api/maintenance/missing-locally", () => jsonResponse(missingLocallyResponse))
    .get("/api/maintenance/unidentified", () => jsonResponse(unidentifiedResponse))
    .get("/api/sonic/features/summary", () => jsonResponse(sonicFeatureSummaryResponse))
    .get("/api/sonic/runs", () => jsonResponse(sonicRunsResponse))
    .get("/api/sonic/generated-playlists", () => jsonResponse(generatedPlaylistsResponse))
    .get("/api/sonic/runs/501", () =>
      jsonResponse({
        playlists: generatedPlaylistsResponse.playlists,
        run: sonicRunsResponse.runs[0],
      }),
    )
    .get("/api/sonic/generated-playlists/7001/tracks", () =>
      jsonResponse({
        tracks: [
          {
            album: "Late Night Drive",
            artist: "Frame Delay",
            duration_ms: 214000,
            file_path: "Frame Delay/Night Runner.mp3",
            id: 1,
            library_root_rel_path: "Frame Delay/Night Runner.mp3",
            local_track_id: 501,
            position: 1,
            title: "Night Runner",
          },
        ],
      }),
    )
    .get("/api/settings/general", () => generalSettingsHandler?.() ?? jsonResponse(generalSettingsResponse))
    .get("/api/m3u/export-profiles", () => m3uExportProfilesHandler?.() ?? jsonResponse(m3uExportProfilesResponse))
    .post("/api/m3u/export-profiles", ({ init }) =>
      jsonResponse({
        id: 2,
        is_default: false,
        library_path: JSON.parse(String(init?.body ?? "{}")).library_path ?? "/mnt/music",
        name: JSON.parse(String(init?.body ?? "{}")).name ?? "USB",
      }),
    )
    .post("/api/m3u/export/preview", ({ init }) => m3uExportPreviewHandler?.(init) ?? jsonResponse(m3uExportPreviewResponse))
    .post("/api/m3u/export", ({ init }) =>
      m3uExportHandler?.(init) ??
      blobResponse(new Blob(["zip"], { type: "application/zip" }), {
        headers: {
          "Content-Disposition": 'attachment; filename="m3u-export.zip"',
        },
      }),
    )
    .post("/api/settings/ingest-folders", ({ init }) =>
      createIngestFolderHandler?.(init) ?? jsonResponse({ id: 3, path: "/downloads" }),
    )
    .delete(/^\/api\/settings\/ingest-folders\/(\d+)$/, ({ match }) =>
      deleteIngestFolderHandler?.(match![1]) ?? emptyResponse(),
    )
    .post(/^\/api\/proposals\/(\d+)\/approve$/, ({ match }) =>
      approveProposalHandler?.(match![1]) ??
      jsonResponse({
        final_link_id: 9000 + Number(match![1]),
        proposal_id: Number(match![1]),
        status: "approved",
      }),
    )
    .post(/^\/api\/proposals\/(\d+)\/reject$/, ({ match }) =>
      rejectProposalHandler?.(match![1]) ??
      jsonResponse({
        proposal_id: Number(match![1]),
        rejected_at: "2026-05-04T10:00:00Z",
        status: "rejected",
      }),
    )
    .patch("/api/streaming/playlists/31", () =>
      jsonResponse({
        ...streamingPlaylistConfigResponse.playlists[1],
        sync_mode: "match_only",
      }),
    )
    .patch("/api/streaming/playlists/12", () =>
      jsonResponse({
        ...streamingPlaylistConfigResponse.playlists[0],
        sync_mode: "off",
      }),
    )
    .get(/^\/api\/playlists\/(\d+)(\/tracks|\/m3u)?$/, ({ match }) => {
      const [, playlistId, suffix] = match!;

      if (suffix === "/m3u") {
        const playlistName = playlistDetailsById.get(playlistId)?.playlist.name ?? "Playlist";

        return blobResponse(new Blob(["#EXTM3U\n/library/night-runner.flac\n"], { type: "audio/x-mpegurl" }), {
          headers: {
            "Content-Disposition": `attachment; filename="${playlistName}.m3u"`,
          },
        });
      }

      if (suffix === "/tracks") {
        return jsonResponse(playlistTracksById.get(playlistId) ?? playlistTracksResponse);
      }

      return jsonResponse(playlistDetailsById.get(playlistId) ?? playlistDetailResponse);
    })
    .post(selectedPlaylistSyncEndpoint, () => selectedSyncHandler?.() ?? jsonResponse(selectedPlaylistSyncResponse))
    .post(/^\/api\/streaming\/playlists\/(\d+)\/sync$/, ({ match }) => {
      if (activeSyncHandler) {
        return activeSyncHandler();
      }

      const [, playlistId] = match!;
      return jsonResponse({ playlist_id: Number(playlistId), job_id: `playlist-sync-job-${playlistId}` });
    })
    .post(metadataRefreshEndpoint, () => metadataRefreshHandler?.() ?? jsonResponse(metadataRefreshResponse))
    .mockFetch();
}

function renderApp(initialEntries = ["/"]) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function openYoutubeMusicSettings() {
  fireEvent.click(screen.getByRole("button", { name: "Open app settings" }));
  expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "YouTube Music sync" }));
  expect(await screen.findByRole("heading", { level: 2, name: "Playlist sync configuration" })).toBeInTheDocument();
}

function countFetches(fetchMock: ReturnType<typeof mockPlaylistFetch>, url: string) {
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

describe("App", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders the responsive shell container, sidebar scaffold, and topbar", async () => {
    mockPlaylistFetch();
    const { container } = renderApp();

    expect(container.firstChild).toHaveClass(
      "flex",
      "min-h-0",
      "flex-1",
      "flex-row",
      "overflow-hidden",
      "bg-ctp-base",
      "text-ctp-text",
      "max-md:flex-col",
    );

    const shell = container.querySelector(".bg-ctp-base");

    expect(shell).toHaveClass(
      "flex",
      "min-h-0",
      "flex-1",
      "flex-row",
      "overflow-hidden",
      "bg-ctp-base",
      "text-ctp-text",
      "max-md:flex-col",
    );

    const sidebar = screen.getByRole("complementary");

    expect(sidebar).toHaveClass(
      "w-[208px]",
      "bg-ctp-mantle",
      "border-r",
      "border-ctp-surface0",
      "max-md:max-h-[45vh]",
      "max-md:w-full",
      "max-md:border-b",
    );
    expect(screen.getByRole("banner")).toHaveClass(
      "h-10",
      "min-h-10",
      "justify-between",
      "max-md:h-auto",
      "max-md:flex-wrap",
      "max-md:py-2",
    );
    expect(screen.getByText("CRATELYNX")).toBeInTheDocument();
    expect(screen.getByText("Maintenance")).toBeInTheDocument();
    expect(screen.getAllByText("YouTube Music").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Local Library")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Link proposals/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Streaming relationships/i })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Late Night Drive/i })).toBeInTheDocument();
    expect(within(sidebar).getByText("62")).toBeInTheDocument();
    expect(await screen.findByText("321")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    expect(screen.getByText("YouTube Music")).toBeInTheDocument();
    const topbarActions = screen.getByRole("toolbar", { name: "Topbar actions" });
    expect(within(topbarActions).getByRole("button", { name: "Open app settings" })).toHaveTextContent("");
    expect(screen.queryByRole("button", { name: "Configure sync" })).not.toBeInTheDocument();
    expect(within(topbarActions).getByRole("button", { name: "Sync" })).toHaveTextContent("");

    for (const viewId of [
      "proposals",
      "streaming-relationships",
      "unidentified",
      "missing",
      "playlists",
      "playlist-export",
      "settings-general",
      "settings-sync-youtube-music",
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

  it("renders Library and Maintenance sidebar badges from backend query data", async () => {
    mockPlaylistFetch({
      relationshipSuggestionsHandler: () =>
        jsonResponse({
          ...streamingRelationshipSuggestionsResponse,
          total_count: 27933,
        }),
    });

    renderApp(["/proposals"]);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Link proposals 3" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Streaming relationships 27933" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Unidentified 1" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Missing locally 1" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "All tracks 321" })).toBeInTheDocument();
    });
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
    expect(document.getElementById("proposals")).toHaveAttribute("data-view-active", "true");
    expect(document.getElementById("playlist-12")).toHaveAttribute("data-view-active", "false");

    fireEvent.click(screen.getByRole("button", { name: /Late Night Drive/i }));

    expect(screen.getByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Late Night Drive/i })).toBeInTheDocument();
    expect(screen.getByText("YouTube Music")).toBeInTheDocument();
    const topbarActions = screen.getByRole("toolbar", { name: "Topbar actions" });
    expect(within(topbarActions).getByRole("button", { name: "Open app settings" })).toHaveTextContent("");
    expect(screen.queryByRole("button", { name: "Configure sync" })).not.toBeInTheDocument();
    expect(within(topbarActions).getByRole("button", { name: "Sync" })).toHaveTextContent("");
    expect(within(topbarActions).getByRole("button", { name: "Export M3U" })).toHaveTextContent("");
    expect(document.getElementById("proposals")).toHaveAttribute("data-view-active", "false");
    expect(document.getElementById("playlist-12")).toHaveAttribute("data-view-active", "true");
  });

  it("opens the link proposals routed view from the URL", async () => {
    mockPlaylistFetch();

    renderApp(["/proposals?proposal_id=44"]);

    expect(screen.getByRole("heading", { level: 1, name: "Link proposals" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "Proposal queue" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3, name: "High" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3, name: "Medium" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3, name: "Low" })).not.toBeInTheDocument();
    expect(await screen.findByText("Night Runner.mp3")).toBeInTheDocument();
    expect(screen.getByText("Pending Signal.mp3")).toBeInTheDocument();
    expect(screen.getByText("Loose Cable.mp3")).toBeInTheDocument();
    expect(document.getElementById("proposals")).toHaveAttribute("data-view-active", "true");
    expect(document.getElementById("playlists")).toHaveAttribute("data-view-active", "false");
  });

  it("opens the streaming relationships maintenance routed view from the URL", async () => {
    mockPlaylistFetch();

    renderApp(["/relationships"]);

    expect(screen.getByRole("heading", { level: 1, name: "Streaming relationships" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Relationship queue" })).toBeInTheDocument();
    expect(await screen.findByRole("listitem", { name: "Suggestion 91: Night Runner to Night Runner" })).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: "Suggestion 92: Loose Cable to Loose Cable Live" })).toBeInTheDocument();
    expect(document.getElementById("streaming-relationships")).toHaveAttribute("data-view-active", "true");
    expect(document.getElementById("playlists")).toHaveAttribute("data-view-active", "false");
  });

  it("opens the local library shell from the sidebar without changing playlist workflows", async () => {
    mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /All tracks/i }));

    expect(screen.getByRole("heading", { level: 1, name: "All tracks" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Local library tracks" })).toBeInTheDocument();
    const filters = await screen.findByRole("region", { name: "Library filters" });
    expect(within(filters).getByRole("group", { name: "Library link status filters" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open app settings" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Configure sync" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export M3U" })).not.toBeInTheDocument();
    expect(document.getElementById("library")).toHaveAttribute("data-view-active", "true");
    expect(document.getElementById("playlist-12")).toHaveAttribute("data-view-active", "false");

    await openYoutubeMusicSettings();

    expect(await screen.findByRole("heading", { level: 2, name: "Playlist sync configuration" })).toBeInTheDocument();
    expect(document.getElementById("settings-sync-youtube-music")).toHaveAttribute("data-view-active", "true");
  });

  it("opens the local library routed view from the URL", async () => {
    mockPlaylistFetch();

    renderApp(["/library"]);

    expect(screen.getByRole("heading", { level: 1, name: "All tracks" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Library filters" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Local library tracks" })).toBeInTheDocument();
    expect(document.getElementById("library")).toHaveAttribute("data-view-active", "true");
    expect(document.getElementById("playlists")).toHaveAttribute("data-view-active", "false");
  });

  it("opens the unidentified maintenance routed view from the URL", async () => {
    mockPlaylistFetch();

    renderApp(["/unidentified"]);

    expect(screen.getByRole("heading", { level: 1, name: "Unidentified" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Unidentified tracks" })).toBeInTheDocument();
    expect(await screen.findByText("unknown-import-9a4f.mp3")).toBeInTheDocument();
    expect(screen.getByText("Beets could not identify metadata")).toBeInTheDocument();
    expect(document.getElementById("unidentified")).toHaveAttribute("data-view-active", "true");
    expect(document.getElementById("playlists")).toHaveAttribute("data-view-active", "false");
  });

  it("opens the missing locally maintenance routed view from the URL", async () => {
    mockPlaylistFetch();

    renderApp(["/missing"]);

    expect(screen.getByRole("heading", { level: 1, name: "Missing locally" })).toBeInTheDocument();
    expect(screen.getByLabelText("Missing locally summary")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Missing local tracks" })).toBeInTheDocument();
    expect(await screen.findByText("Open Eye Signal")).toBeInTheDocument();
    expect(screen.getByText("ytm:VLPL_missing_018")).toBeInTheDocument();
    expect(document.getElementById("missing")).toHaveAttribute("data-view-active", "true");
    expect(document.getElementById("playlists")).toHaveAttribute("data-view-active", "false");
  });

  it("renders link proposals together in score order with proposal details", async () => {
    mockPlaylistFetch();

    renderApp(["/proposals"]);

    expect(await screen.findByRole("heading", { level: 2, name: "Proposal queue" })).toBeInTheDocument();

    expect(screen.queryByRole("heading", { level: 3, name: "High" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3, name: "Medium" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3, name: "Low" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Confidence band filters" })).not.toBeInTheDocument();

    const nightRunnerRow = await screen.findByRole("listitem", {
      name: /Proposal 44: Night Runner\.mp3 to Night Runner$/,
    });
    const pendingSignalRow = screen.getByRole("listitem", {
      name: /Proposal 45: Pending Signal\.mp3 to Pending Signal$/,
    });
    const looseCableRow = screen.getByRole("listitem", {
      name: /Proposal 46: Loose Cable\.mp3 to Loose Cable$/,
    });

    expect(nightRunnerRow.compareDocumentPosition(pendingSignalRow)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(pendingSignalRow.compareDocumentPosition(looseCableRow)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(screen.queryByText("Ranked candidates")).not.toBeInTheDocument();
    expect(within(nightRunnerRow).getAllByText("Night Runner")).toHaveLength(2);
    expect(within(nightRunnerRow).getAllByText("Frame Delay")).toHaveLength(2);
    expect(within(nightRunnerRow).getByText("Tag")).toBeInTheDocument();
    expect(within(nightRunnerRow).getByText("92%")).toBeInTheDocument();
    expect(within(nightRunnerRow).getByText("High confidence")).toBeInTheDocument();
    expect(within(pendingSignalRow).getByText("Album unavailable")).toBeInTheDocument();
    expect(within(looseCableRow).getByText("Tag")).toBeInTheDocument();
    expect(
      within(nightRunnerRow)
        .getByText("Local track")
        .compareDocumentPosition(within(nightRunnerRow).getByText("Streaming track")),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("ignores legacy proposal confidence-band URL state", async () => {
    const fetchMock = mockPlaylistFetch({
      linkProposalsHandler: () => {
        return {
          ok: true,
          json: async () => linkProposalsResponse,
        } as Response;
      },
    });

    renderApp(["/proposals?band=high"]);

    expect(await screen.findByText("Night Runner.mp3")).toBeInTheDocument();
    expect(screen.getByText("Pending Signal.mp3")).toBeInTheDocument();
    expect(screen.getByText("Loose Cable.mp3")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/proposals");
    expect(fetchMock).not.toHaveBeenCalledWith("/api/proposals?band=high");
    expect(screen.queryByRole("group", { name: "Confidence band filters" })).not.toBeInTheDocument();
  });

  it("optimistically removes approved and rejected link proposals", async () => {
    let resolveApprove: (response: Response) => void = () => {};
    let resolveReject: (response: Response) => void = () => {};
    const approvePromise = new Promise<Response>((resolve) => {
      resolveApprove = resolve;
    });
    const rejectPromise = new Promise<Response>((resolve) => {
      resolveReject = resolve;
    });
    const fetchMock = mockPlaylistFetch({
      approveProposalHandler: () => approvePromise,
      rejectProposalHandler: () => rejectPromise,
    });

    renderApp(["/proposals"]);

    expect(await screen.findByText("Night Runner.mp3")).toBeInTheDocument();
    fireEvent.click(
      within(screen.getByRole("listitem", { name: /Proposal 44: Night Runner\.mp3/ })).getByRole("button", {
        name: /Approve proposal 44/,
      }),
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/proposals/44/approve", { method: "POST" });
      expect(screen.queryByText("Night Runner.mp3")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Pending Signal.mp3")).toBeInTheDocument();
    expect(screen.getByText("Loose Cable.mp3")).toBeInTheDocument();

    fireEvent.click(
      within(screen.getByRole("listitem", { name: /Proposal 45: Pending Signal\.mp3/ })).getByRole("button", {
        name: /Reject proposal 45/,
      }),
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/proposals/45/reject", { method: "POST" });
      expect(screen.queryByText("Pending Signal.mp3")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Loose Cable.mp3")).toBeInTheDocument();

    resolveApprove({
      ok: true,
      json: async () => ({ final_link_id: 9044, proposal_id: 44, status: "approved" }),
    } as Response);
    resolveReject({
      ok: true,
      json: async () => ({ proposal_id: 45, rejected_at: "2026-05-04T10:00:00Z", status: "rejected" }),
    } as Response);
  });

  it("renders proposal loading state without confidence filters", async () => {
    mockPlaylistFetch({
      linkProposalsHandler: () => new Promise<Response>(() => {}),
    });

    renderApp(["/proposals"]);

    expect(await screen.findByRole("status")).toHaveTextContent("Loading proposals");
    expect(screen.queryByRole("group", { name: "Confidence band filters" })).not.toBeInTheDocument();
  });

  it("renders proposal loading errors without confidence filters", async () => {
    mockPlaylistFetch({
      linkProposalsHandler: () =>
        ({
          ok: false,
          status: 500,
        }) as Response,
    });

    renderApp(["/proposals"]);

    expect(await screen.findByRole("alert")).toHaveTextContent("Proposals unavailable");
    expect(screen.queryByRole("group", { name: "Confidence band filters" })).not.toBeInTheDocument();
  });

  it("renders an empty proposal result without confidence filters", async () => {
    const fetchMock = mockPlaylistFetch({
      linkProposalsHandler: () =>
        ({
          ok: true,
          json: async () => ({ limit: 50, next_cursor: null, proposals: [], returned_count: 0, total_count: 0 }),
        }) as Response,
    });

    renderApp(["/proposals?band=high"]);

    expect(await screen.findByRole("heading", { level: 2, name: "Proposal queue" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Confidence band filters" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/proposals");
  });

  it("opens General settings from the topbar and renders ingest folders", async () => {
    mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Fresh Discoveries/i })).not.toBeInTheDocument();
    const openSettingsButton = screen.getByRole("button", { name: "Open app settings" });
    expect(openSettingsButton.querySelector("svg")).toBeInTheDocument();
    expect(openSettingsButton).toHaveTextContent("");
    fireEvent.click(openSettingsButton);

    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "General" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "YouTube Music sync" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync Settings" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Sync platforms" })).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "General settings" })).toBeInTheDocument();
    expect(screen.getByText("2 ingest folders configured.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Ingest folders" })).toBeInTheDocument();
    expect(screen.getByText("/ingestion")).toBeInTheDocument();
    expect(screen.getByText("/soulseek")).toBeInTheDocument();
    expect(screen.getByLabelText("Add ingest folder")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Sync" })).not.toBeInTheDocument();
    expect(document.getElementById("settings-general")).toHaveAttribute("data-view-active", "true");
    expect(document.getElementById("settings-sync-youtube-music")).toHaveAttribute("data-view-active", "false");
    expect(document.getElementById("playlist-12")).toHaveAttribute("data-view-active", "false");
    expect(screen.queryByRole("button", { name: "Configure sync" })).not.toBeInTheDocument();
    const returnButton = screen.getByRole("button", { name: "Return to Link proposals" });
    expect(returnButton.querySelector("svg")).toBeInTheDocument();
    expect(returnButton).toHaveTextContent("");
  });

  it("navigates from General settings to YouTube Music sync settings", async () => {
    mockPlaylistFetch();

    renderApp(["/settings"]);

    expect(await screen.findByRole("heading", { level: 2, name: "General settings" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "YouTube Music sync" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Playlist sync configuration" })).toBeInTheDocument();
    expect(await screen.findByText("2 discovered")).toBeInTheDocument();
    expect(screen.getByText("1 full sync")).toBeInTheDocument();
    expect(screen.getByText("0 match only")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Late Night Drive" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Fresh Discoveries" })).toBeInTheDocument();
    expect(
      within(screen.getByRole("group", { name: "Sync mode for Late Night Drive" })).getByRole("button", {
        name: "Full sync",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(screen.getByRole("group", { name: "Sync mode for Fresh Discoveries" })).getByRole("button", {
        name: "Off",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Refresh playlist metadata" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Provider ID/ })).toBeInTheDocument();
    expect(screen.getByText("PL31")).toBeInTheDocument();
    expect(screen.getByText("Malformed playlist payload")).toBeInTheDocument();
    expect(document.getElementById("settings-general")).toHaveAttribute("data-view-active", "false");
    expect(document.getElementById("settings-sync-youtube-music")).toHaveAttribute("data-view-active", "true");
  });

  it("adds ingest folders from General settings and refreshes settings", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp(["/settings"]);

    expect(await screen.findByText("/ingestion")).toBeInTheDocument();
    const pathInput = screen.getByLabelText("Add ingest folder");
    const generalFetchesBeforeAdd = fetchMock.mock.calls.filter(([input]) => String(input) === "/api/settings/general").length;
    fireEvent.change(pathInput, { target: { value: " /downloads " } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/settings/ingest-folders", {
        body: JSON.stringify({ path: "/downloads" }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "POST",
      });
    });
    expect(await screen.findByText("The folder was saved and added to the active watcher.")).toBeInTheDocument();
    await waitFor(() => {
      expect(pathInput).toHaveValue("");
    });
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/settings/general").length).toBeGreaterThan(
        generalFetchesBeforeAdd,
      );
    });
  });

  it("removes ingest folders from General settings and refreshes settings", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp(["/settings"]);

    expect(await screen.findByText("/soulseek")).toBeInTheDocument();

    const generalFetchesBeforeDelete = fetchMock.mock.calls.filter(([input]) => String(input) === "/api/settings/general").length;
    fireEvent.click(screen.getByRole("button", { name: "Remove ingest folder /soulseek" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/settings/ingest-folders/2", {
        method: "DELETE",
      });
    });
    expect(await screen.findByText("The folder was removed from the active watcher.")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/settings/general").length).toBeGreaterThan(
        generalFetchesBeforeDelete,
      );
    });
  });

  it("switches the main sidebar into settings navigation on settings routes", async () => {
    mockPlaylistFetch();

    renderApp(["/settings/sync/youtube-music"]);

    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "Playlist sync configuration" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /CRATELYNX/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "General" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "YouTube Music sync" })).toBeInTheDocument();
    expect(screen.queryByText("Maintenance")).not.toBeInTheDocument();
    expect(screen.queryByText("Local Library")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Late Night Drive/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "YouTube Music" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Sync platforms" })).not.toBeInTheDocument();
  });

  it("returns from settings to Link proposals through the brand and topbar home button", async () => {
    mockPlaylistFetch();

    renderApp(["/settings/sync/youtube-music"]);

    expect(await screen.findByRole("heading", { level: 2, name: "Playlist sync configuration" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /CRATELYNX/i }));

    expect(await screen.findByRole("heading", { level: 1, name: "Link proposals" })).toBeInTheDocument();
    expect(screen.getByText("Maintenance")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open app settings" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Return to Link proposals" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Link proposals" })).toBeInTheDocument();
    expect(document.getElementById("proposals")).toHaveAttribute("data-view-active", "true");
  });

  it.each([
    ["/settings", "settings-general", "General settings"],
    ["/settings/sync", "settings-sync-youtube-music", "Playlist sync configuration"],
    ["/settings/sync/youtube-music", "settings-sync-youtube-music", "Playlist sync configuration"],
  ])(
    "lands on the expected settings page for %s",
    async (route, activeViewId, heading) => {
      mockPlaylistFetch();

      renderApp([route]);

      expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
      expect(await screen.findByRole("heading", { level: 2, name: heading })).toBeInTheDocument();
      expect(document.getElementById(activeViewId)).toHaveAttribute("data-view-active", "true");
    },
  );

  it("updates playlist sync modes without refetching sidebar and config queries", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    await openYoutubeMusicSettings();

    const playlistListFetchesBeforeToggle = countFetches(fetchMock, "/api/streaming/playlists");
    const configFetchesBeforeToggle = countFetches(fetchMock, "/api/streaming/playlists/config");
    const missingLocallyFetchesBeforeToggle = countFetches(fetchMock, "/api/maintenance/missing-locally");

    fireEvent.click(
      within(await screen.findByRole("group", { name: "Sync mode for Late Night Drive" })).getByRole("button", {
        name: "Off",
      }),
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists/12", {
        body: JSON.stringify({ sync_mode: "off" }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "PATCH",
      });
    });
    await waitFor(() => {
      const modeControl = screen.getByRole("group", { name: "Sync mode for Late Night Drive" });
      expect(within(modeControl).getByRole("button", { name: "Off" })).toHaveAttribute("aria-pressed", "true");
    });

    fireEvent.click(
      within(await screen.findByRole("group", { name: "Sync mode for Fresh Discoveries" })).getByRole("button", {
        name: "Match only",
      }),
    );

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
      const modeControl = screen.getByRole("group", { name: "Sync mode for Fresh Discoveries" });
      expect(within(modeControl).getByRole("button", { name: "Match only" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(countFetches(fetchMock, "/api/streaming/playlists")).toBe(playlistListFetchesBeforeToggle);
      expect(countFetches(fetchMock, "/api/streaming/playlists/config")).toBe(configFetchesBeforeToggle);
      expect(countFetches(fetchMock, "/api/maintenance/missing-locally")).toBeGreaterThan(
        missingLocallyFetchesBeforeToggle,
      );
    });
  });

  it("queues a playlist metadata refresh without immediate sidebar or config refetch", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    await openYoutubeMusicSettings();
    vi.useFakeTimers();

    const playlistListFetchesBeforeRefresh = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/streaming/playlists",
    ).length;
    const configFetchesBeforeRefresh = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/streaming/playlists/config",
    ).length;

    fireEvent.click(screen.getByRole("button", { name: "Refresh playlist metadata" }));
    await flushAsyncWork();

    expect(fetchMock).toHaveBeenCalledWith(metadataRefreshEndpoint, {
      method: "POST",
    });
    expect(screen.getByText("Metadata refresh queued.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/streaming/playlists").length).toBe(
      playlistListFetchesBeforeRefresh,
    );
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/streaming/playlists/config").length).toBe(
      configFetchesBeforeRefresh,
    );

    await advanceTimers(3000);
    await flushAsyncWork();

    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/streaming/playlists").length).toBeGreaterThan(
      playlistListFetchesBeforeRefresh,
    );
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/streaming/playlists/config").length).toBeGreaterThan(
      configFetchesBeforeRefresh,
    );
  });

  it("shows success state when active playlist sync is queued", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    await openYoutubeMusicSettings();
    fireEvent.click(await screen.findByRole("button", { name: "Sync Full + Match" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(selectedPlaylistSyncEndpoint, {
        method: "POST",
      });
    });
    expect(await screen.findByText("Full + Match playlist sync queued.")).toBeInTheDocument();
  });

  it("shows pending state while active playlist sync is running", async () => {
    let resolveSync: (response: Response) => void = () => {};
    const syncPromise = new Promise<Response>((resolve) => {
      resolveSync = resolve;
    });
    mockPlaylistFetch({
      selectedSyncHandler: () => syncPromise,
    });

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    await openYoutubeMusicSettings();
    fireEvent.click(await screen.findByRole("button", { name: "Sync Full + Match" }));

    expect(await screen.findByRole("button", { name: "Syncing Full + Match..." })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Syncing Full + Match playlists...");

    resolveSync({
      ok: true,
      json: async () => selectedPlaylistSyncResponse,
    } as Response);

    expect(await screen.findByText("Full + Match playlist sync queued.")).toBeInTheDocument();
  });

  it("shows an error state when active playlist sync fails", async () => {
    mockPlaylistFetch({
      selectedSyncHandler: () =>
        ({
          ok: false,
          status: 500,
        }) as Response,
    });

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    await openYoutubeMusicSettings();
    fireEvent.click(await screen.findByRole("button", { name: "Sync Full + Match" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Active playlist sync failed.");
    expect(screen.getByRole("button", { name: "Sync Full + Match" })).toBeEnabled();
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
    await openYoutubeMusicSettings();
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
    await openYoutubeMusicSettings();
    fireEvent.click(await screen.findByRole("button", { name: "Refresh playlist metadata" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Metadata refresh failed.");
    expect(screen.getByRole("button", { name: "Refresh playlist metadata" })).toBeEnabled();
  });

  it("opens the first synced playlist by default", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Playlist toolbar" })).toBeInTheDocument();
    expect(document.getElementById("playlist-12")).toHaveAttribute("data-view-active", "true");
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12");
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12/tracks");
  });

  it("renders the playlist view inside the active playlist shell", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    const playlistToolbar = await screen.findByRole("region", { name: "Playlist toolbar" });
    expect(playlistToolbar).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Late Night Drive" })).toBeInTheDocument();
    expect(within(playlistToolbar).getByText("58")).toBeInTheDocument();
    expect(within(playlistToolbar).getByText("Linked")).toBeInTheDocument();
    expect(screen.getByText("Night Runner")).toBeInTheDocument();
    expect(screen.getByText("Pending Signal")).toBeInTheDocument();
    expect(screen.getByText("Loose Cable")).toBeInTheDocument();
    expect(screen.getByText("Showing 3 of 3 tracks")).toBeInTheDocument();
    expect(document.getElementById("playlist-12")).toHaveClass("min-h-0", "overflow-hidden");
    expect(screen.getByRole("region", { name: "Playlist tracks" })).toHaveClass(
      "min-h-0",
      "flex-1",
      "overflow-y-auto",
      "pb-1",
    );
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12");
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12/tracks");
  });

  it("keeps the playlist sync header fixed while configuration rows scroll", async () => {
    mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();
    await openYoutubeMusicSettings();

    expect(await screen.findByRole("heading", { level: 2, name: "Playlist sync configuration" })).toBeInTheDocument();
    expect(document.getElementById("settings-sync-youtube-music")).toHaveClass("min-h-0", "overflow-hidden");
    expect(screen.getByRole("region", { name: "Playlist sync configuration list" })).toHaveClass(
      "min-h-0",
      "flex-1",
      "overflow-y-auto",
      "pb-1",
    );
    expect(screen.getByRole("button", { name: "Sync Full + Match" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Late Night Drive" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Fresh Discoveries" })).toBeInTheDocument();
  });

  it("renders secondary playlist shells with their configured playlist resources", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    for (const playlist of secondaryPlaylistFixtures) {
      fireEvent.click(await screen.findByRole("button", { name: new RegExp(playlist.name, "i") }));

      expect(await screen.findByRole("region", { name: "Playlist toolbar" })).toBeInTheDocument();
      expect(screen.getByRole("heading", { level: 2, name: playlist.name })).toBeInTheDocument();
      expect(screen.getByText(playlist.trackTitle)).toBeInTheDocument();
      expect(screen.getByText("Showing 1 of 1 tracks")).toBeInTheDocument();
      expect(document.getElementById(playlist.viewId)).toHaveAttribute("data-view-active", "true");
      expect(fetchMock).toHaveBeenCalledWith(`/api/playlists/${playlist.id}`);
      expect(fetchMock).toHaveBeenCalledWith(`/api/playlists/${playlist.id}/tracks`);
    }
  });

  it("routes users to configure sync when no full-sync playlists exist", async () => {
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
          json: async () => streamingPlaylistConfigResponse,
        } as Response;
      }

      return failUnexpectedFetch(url);
    });

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "Playlist sync configuration" })).toBeInTheDocument();
    expect(screen.getByText("2 discovered")).toBeInTheDocument();
    expect(screen.getByText("1 full sync")).toBeInTheDocument();
    expect(
      within(screen.getByRole("group", { name: "Sync mode for Late Night Drive" })).getByRole("button", {
        name: "Full sync",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(screen.getByRole("group", { name: "Sync mode for Fresh Discoveries" })).getByRole("button", {
        name: "Off",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Sync" })).not.toBeInTheDocument();
    expect(document.getElementById("settings-sync-youtube-music")).toHaveAttribute("data-view-active", "true");
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

  it("delays playlist refetches after the active playlist sync queues", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /Static Bloom/i }));

    const syncButton = await screen.findByRole("button", { name: "Sync" });
    await waitFor(() => {
      expect(syncButton).toBeEnabled();
    });
    vi.useFakeTimers();

    fireEvent.click(syncButton);
    await flushAsyncWork();

    expect(screen.getByText("Playlist sync queued.")).toBeInTheDocument();
    const playlistListFetchesAfterQueued = countFetches(fetchMock, "/api/streaming/playlists");
    const playlistDetailFetchesAfterQueued = countFetches(fetchMock, "/api/playlists/9");
    const playlistTrackFetchesAfterQueued = countFetches(fetchMock, "/api/playlists/9/tracks");

    await advanceTimers(3000);

    expect(countFetches(fetchMock, "/api/streaming/playlists")).toBeGreaterThan(playlistListFetchesAfterQueued);
    expect(countFetches(fetchMock, "/api/playlists/9")).toBeGreaterThan(playlistDetailFetchesAfterQueued);
    expect(countFetches(fetchMock, "/api/playlists/9/tracks")).toBeGreaterThan(playlistTrackFetchesAfterQueued);

    const playlistListFetchesAfterFirstDelay = countFetches(fetchMock, "/api/streaming/playlists");
    const playlistDetailFetchesAfterFirstDelay = countFetches(fetchMock, "/api/playlists/9");
    const playlistTrackFetchesAfterFirstDelay = countFetches(fetchMock, "/api/playlists/9/tracks");

    await advanceTimers(7000);

    expect(countFetches(fetchMock, "/api/streaming/playlists")).toBeGreaterThan(playlistListFetchesAfterFirstDelay);
    expect(countFetches(fetchMock, "/api/playlists/9")).toBeGreaterThan(playlistDetailFetchesAfterFirstDelay);
    expect(countFetches(fetchMock, "/api/playlists/9/tracks")).toBeGreaterThan(playlistTrackFetchesAfterFirstDelay);
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
    expect(screen.getByRole("button", { name: "Syncing playlist" })).toBeDisabled();

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
    expect(screen.getByRole("heading", { level: 3, name: "Playlist sync failed" })).toBeInTheDocument();
    expect(screen.getByText("The playlist sync request failed before the job could be queued.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync" })).toBeEnabled();
  });

  it("opens the M3U export journey from the active playlist topbar", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /Late Night Drive/i }));

    const exportButton = await screen.findByRole("button", { name: "Export M3U" });
    fireEvent.click(exportButton);

    expect(await screen.findByRole("heading", { level: 1, name: "M3U export" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "M3U export" })).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Playlist export selection" })).getByRole("button", {
        name: /Late Night Drive/i,
      }),
    ).toBeInTheDocument();
    expect(document.getElementById("playlist-export")).toHaveAttribute("data-view-active", "true");
    expect(fetchMock).not.toHaveBeenCalledWith("/api/playlists/12/m3u");
  });

  it("previews and downloads a batch M3U ZIP", async () => {
    const fetchMock = mockPlaylistFetch();
    const createObjectUrlMock = vi.fn(() => "blob:m3u-export");
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

    renderApp(["/playlists/export?playlist=12"]);

    const previewButton = await screen.findByRole("button", { name: "Preview" });
    await waitFor(() => {
      expect(previewButton).toBeEnabled();
    });
    fireEvent.click(previewButton);

    expect(await screen.findByRole("region", { name: "M3U export preview" })).toBeInTheDocument();
    expect(screen.getByText("file://localhost/mnt/music/Frame%20Delay/Night%20Runner.flac")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/m3u/export/preview", {
      body: JSON.stringify({
        formats: ["m3u", "m3u8"],
        path_format: "file_url",
        playlist_ids: [12],
        profile_id: 1,
      }),
      headers: {
        "Content-Type": "application/json",
      },
      method: "POST",
    });

    fireEvent.click(screen.getByRole("button", { name: "Download ZIP" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/m3u/export", {
        body: JSON.stringify({
          formats: ["m3u", "m3u8"],
          path_format: "file_url",
          playlist_ids: [12],
          profile_id: 1,
        }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "POST",
      });
    });
    expect(createObjectUrlMock).toHaveBeenCalledWith(expect.any(Blob));
    expect(clickMock).toHaveBeenCalled();
    expect(revokeObjectUrlMock).toHaveBeenCalledWith("blob:m3u-export");
  });

  it("uses the selected M3U export formats for preview and download", async () => {
    let previewRequestBody: unknown = null;
    let exportRequestBody: unknown = null;
    const createObjectUrlMock = vi.fn(() => "blob:m3u8-export");
    const revokeObjectUrlMock = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    Object.defineProperty(window.URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrlMock,
    });
    Object.defineProperty(window.URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectUrlMock,
    });

    mockPlaylistFetch({
      m3uExportHandler: (init) => {
        exportRequestBody = JSON.parse(String(init?.body ?? "{}"));
        return blobResponse(new Blob(["zip"], { type: "application/zip" }), {
          headers: {
            "Content-Disposition": 'attachment; filename="m3u-export.zip"',
          },
        });
      },
      m3uExportPreviewHandler: (init) => {
        previewRequestBody = JSON.parse(String(init?.body ?? "{}"));
        return jsonResponse({
          ...m3uExportPreviewResponse,
          formats: ["m3u8"],
          path_format: "file_url",
          playlists: [
            {
              ...m3uExportPreviewResponse.playlists[0],
              filenames: ["Late Night Drive [yt].m3u8"],
            },
          ],
        });
      },
    });

    renderApp(["/playlists/export?playlist=12"]);

    const m3uCheckbox = await screen.findByRole("checkbox", { name: ".m3u" });
    const m3u8Checkbox = screen.getByRole("checkbox", { name: ".m3u8" });
    expect(m3uCheckbox).toBeChecked();
    expect(m3u8Checkbox).toBeChecked();
    fireEvent.click(m3uCheckbox);
    expect(m3uCheckbox).not.toBeChecked();
    expect(m3u8Checkbox).toBeChecked();

    const previewButton = screen.getByRole("button", { name: "Preview" });
    await waitFor(() => {
      expect(previewButton).toBeEnabled();
    });
    fireEvent.click(previewButton);

    expect(await screen.findByText("Late Night Drive [yt].m3u8")).toBeInTheDocument();
    expect(previewRequestBody).toEqual({
      formats: ["m3u8"],
      path_format: "file_url",
      playlist_ids: [12],
      profile_id: 1,
    });

    fireEvent.click(screen.getByRole("button", { name: "Download ZIP" }));

    await waitFor(() => {
      expect(exportRequestBody).toEqual({
        formats: ["m3u8"],
        path_format: "file_url",
        playlist_ids: [12],
        profile_id: 1,
      });
    });
    expect(createObjectUrlMock).toHaveBeenCalledWith(expect.any(Blob));
    expect(revokeObjectUrlMock).toHaveBeenCalledWith("blob:m3u8-export");
  });

  it("filters playlist tracks by status", async () => {
    mockPlaylistFetch();

    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: /Late Night Drive/i }));

    expect(await screen.findByText("Night Runner")).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Pending/i }));
    });

    expect(screen.getByText("Pending Signal")).toBeInTheDocument();
    expect(screen.queryByText("Night Runner")).not.toBeInTheDocument();
    expect(screen.queryByText("Loose Cable")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 1 of 3 tracks")).toBeInTheDocument();
  });

  it("fails playlist UI tests on unsupported playlist API routes", async () => {
    const fetchMock = mockPlaylistFetch();

    renderApp();

    expect(await screen.findByRole("heading", { level: 1, name: "Late Night Drive" })).toBeInTheDocument();

    await expect(fetch("/api/playlists")).rejects.toThrow("Unexpected fetch request: GET /api/playlists");
    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists");
  });

  it("maps progress percentages onto the Catppuccin theme gradient", () => {
    expect(getProgressColor(-10)).toBe("var(--color-ctp-overlay0)");
    expect(getProgressColor(25)).toBe(
      "color-mix(in srgb, var(--color-ctp-overlay0) 50%, var(--color-ctp-yellow))",
    );
    expect(getProgressColor(50)).toBe("var(--color-ctp-yellow)");
    expect(getProgressColor(75)).toBe(
      "color-mix(in srgb, var(--color-ctp-yellow) 50%, var(--color-ctp-green))",
    );
    expect(getProgressColor(100)).toBe("var(--color-ctp-green)");
  });
});
