import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import {
  approveLinkProposal,
  exportPlaylistM3u,
  fetchLinkProposals,
  fetchPlaylistDetail,
  fetchStreamingPlaylistConfig,
  fetchStreamingPlaylists,
  fetchPlaylistTracks,
  playlistQueryKeys,
  rejectLinkProposal,
  refreshStreamingAccountMetadata,
  updateStreamingPlaylistConfig,
  useLinkProposalsQuery,
  usePlaylistDetailQuery,
  useStreamingPlaylistConfigQuery,
  useStreamingPlaylistsQuery,
  usePlaylistTracksQuery,
} from "./queries";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function failUnexpectedFetch(url: string, init?: RequestInit): never {
  throw new Error(`Unexpected fetch request: ${init?.method ?? "GET"} ${url}`);
}

describe("playlist queries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("builds stable query keys per playlist resource", () => {
    expect(playlistQueryKeys.all).toEqual(["playlists"]);
    expect(playlistQueryKeys.config()).toEqual(["playlists", "config"]);
    expect(playlistQueryKeys.detail(12)).toEqual(["playlists", 12, "detail"]);
    expect(playlistQueryKeys.list()).toEqual(["playlists", "list"]);
    expect(playlistQueryKeys.proposals()).toEqual(["playlists", "proposals", { confidenceBand: null }]);
    expect(playlistQueryKeys.proposals({ confidenceBand: "high" })).toEqual([
      "playlists",
      "proposals",
      { confidenceBand: "high" },
    ]);
    expect(playlistQueryKeys.tracks(12)).toEqual(["playlists", 12, "tracks"]);
  });

  it("fetches playlist detail metadata from the playlist detail endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        playlist: {
          id: 12,
          account_id: 4,
          provider_playlist_id: "PL12",
          name: "Late Night Drive",
          cover_art_url: "https://cdn.example.test/cover.jpg",
          sync_mode: "full",
          provider_track_count: 70,
          imported_track_count: 62,
          linked_count: 58,
          pending_count: 3,
          unlinked_count: 1,
          metadata_synced_at: "2026-05-01T08:55:00",
          tracks_synced_at: "2026-05-01T09:00:00",
          last_sync_error: "Malformed playlist payload",
          last_sync_error_at: "2026-05-02T10:30:00",
        },
      }),
    } as Response);

    await expect(fetchPlaylistDetail(12)).resolves.toEqual({
      playlist: {
        id: 12,
        account_id: 4,
        provider_playlist_id: "PL12",
        name: "Late Night Drive",
        cover_art_url: "https://cdn.example.test/cover.jpg",
        sync_mode: "full",
        provider_track_count: 70,
        imported_track_count: 62,
        linked_count: 58,
        pending_count: 3,
        unlinked_count: 1,
        metadata_synced_at: "2026-05-01T08:55:00",
        tracks_synced_at: "2026-05-01T09:00:00",
        last_sync_error: "Malformed playlist payload",
        last_sync_error_at: "2026-05-02T10:30:00",
      },
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12");
  });

  it("fetches playlist track rows from the playlist tracks endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        tracks: [
          {
            id: 77,
            provider_track_id: "trk-77",
            position: 1,
            title: "Open Road",
            artist: "Frame Delay",
            album: "Late Night Drive",
            duration_ms: 215000,
            status: "linked",
            local_track_id: 101,
            proposal_id: null,
            final_link_id: 55,
          },
        ],
      }),
    } as Response);

    await expect(fetchPlaylistTracks(12)).resolves.toEqual({
      tracks: [
        {
          id: 77,
          provider_track_id: "trk-77",
          position: 1,
          title: "Open Road",
          artist: "Frame Delay",
          album: "Late Night Drive",
          duration_ms: 215000,
          status: "linked",
          local_track_id: 101,
          proposal_id: null,
          final_link_id: 55,
        },
      ],
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12/tracks");
  });

  it("rejects playlist tracks with unknown status values", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        tracks: [
          {
            id: 77,
            provider_track_id: "trk-77",
            position: 1,
            title: "Open Road",
            artist: "Frame Delay",
            album: "Late Night Drive",
            duration_ms: 215000,
            status: "archived",
            local_track_id: 101,
            proposal_id: null,
            final_link_id: 55,
          },
        ],
      }),
    } as Response);

    await expect(fetchPlaylistTracks(12)).rejects.toThrow();
  });

  it("fetches link proposals without a confidence-band filter", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        proposals: [
          {
            id: 44,
            local_track_id: 8,
            local_album: "Local Drive",
            local_artist: "Frame Delay",
            local_file_path: "Frame Delay/Open Road.flac",
            local_title: "Open Road Local",
            streaming_track_id: 77,
            streaming_title: "Open Road",
            streaming_artist: "Frame Delay",
            streaming_album: "Late Night Drive",
            match_method: "tags",
            score: 0.88,
            status: "pending",
            confidence_band: "medium",
            rejected_at: null,
          },
        ],
      }),
    } as Response);

    await expect(fetchLinkProposals()).resolves.toEqual({
      proposals: [
        {
          id: 44,
          local_track_id: 8,
          local_album: "Local Drive",
          local_artist: "Frame Delay",
          local_file_path: "Frame Delay/Open Road.flac",
          local_title: "Open Road Local",
          streaming_track_id: 77,
          streaming_title: "Open Road",
          streaming_artist: "Frame Delay",
          streaming_album: "Late Night Drive",
          match_method: "tags",
          score: 0.88,
          status: "pending",
          confidence_band: "medium",
          rejected_at: null,
        },
      ],
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/proposals");
  });

  it("fetches link proposals with a confidence-band filter", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ proposals: [] }),
    } as Response);

    await expect(fetchLinkProposals({ confidenceBand: "high" })).resolves.toEqual({ proposals: [] });
    expect(fetchMock).toHaveBeenCalledWith("/api/proposals?band=high");
  });

  it("approves a link proposal", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        proposal_id: 44,
        final_link_id: 21,
        status: "approved",
      }),
    } as Response);

    await expect(approveLinkProposal(44)).resolves.toEqual({
      proposal_id: 44,
      final_link_id: 21,
      status: "approved",
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/proposals/44/approve", {
      method: "POST",
    });
  });

  it("rejects a link proposal", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        proposal_id: 44,
        status: "rejected",
        rejected_at: "2026-05-03T12:00:00+00:00",
      }),
    } as Response);

    await expect(rejectLinkProposal(44)).resolves.toEqual({
      proposal_id: 44,
      status: "rejected",
      rejected_at: "2026-05-03T12:00:00+00:00",
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/proposals/44/reject", {
      method: "POST",
    });
  });

  it("fetches synced streaming playlists from the backend sidebar endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url === "/api/streaming/playlists") {
        return {
          ok: true,
          json: async () => ({
            playlists: [
              {
                id: 12,
                account_id: 4,
                provider_playlist_id: "PL12",
                title: "Late Night Drive",
                sync_mode: "full",
                provider_track_count: 70,
                imported_track_count: 62,
                metadata_synced_at: "2026-05-01T08:55:00",
                tracks_synced_at: "2026-05-01T09:00:00",
                last_sync_error: null,
                last_sync_error_at: null,
              },
            ],
          }),
        } as Response;
      }

      failUnexpectedFetch(url);
    });

    await expect(fetchStreamingPlaylists()).resolves.toEqual({
      playlists: [
        {
          id: 12,
          account_id: 4,
          provider_playlist_id: "PL12",
          title: "Late Night Drive",
          sync_mode: "full",
          provider_track_count: 70,
          imported_track_count: 62,
          metadata_synced_at: "2026-05-01T08:55:00",
          tracks_synced_at: "2026-05-01T09:00:00",
          last_sync_error: null,
          last_sync_error_at: null,
        },
      ],
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists");
    expect(fetchMock).not.toHaveBeenCalledWith("/api/playlists");
  });

  it("fetches all discovered streaming playlists from the config endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url === "/api/streaming/playlists/config") {
        return {
          ok: true,
          json: async () => ({
            playlists: [
              {
                id: 12,
                account_id: 4,
                provider_playlist_id: "PL12",
                title: "Late Night Drive",
                sync_mode: "full",
                provider_track_count: 70,
                imported_track_count: 62,
                metadata_synced_at: "2026-05-01T08:55:00",
                tracks_synced_at: "2026-05-01T09:00:00",
                last_sync_error: null,
                last_sync_error_at: null,
              },
              {
                id: 13,
                account_id: 4,
                provider_playlist_id: "PL13",
                title: "Fresh Discoveries",
                sync_mode: "off",
                provider_track_count: null,
                imported_track_count: 0,
                metadata_synced_at: null,
                tracks_synced_at: null,
                last_sync_error: "Malformed playlist payload",
                last_sync_error_at: "2026-05-02T10:30:00",
              },
            ],
          }),
        } as Response;
      }

      failUnexpectedFetch(url);
    });

    await expect(fetchStreamingPlaylistConfig()).resolves.toEqual({
      playlists: [
        {
          id: 12,
          account_id: 4,
          provider_playlist_id: "PL12",
          title: "Late Night Drive",
          sync_mode: "full",
          provider_track_count: 70,
          imported_track_count: 62,
          metadata_synced_at: "2026-05-01T08:55:00",
          tracks_synced_at: "2026-05-01T09:00:00",
          last_sync_error: null,
          last_sync_error_at: null,
        },
        {
          id: 13,
          account_id: 4,
          provider_playlist_id: "PL13",
          title: "Fresh Discoveries",
          sync_mode: "off",
          provider_track_count: null,
          imported_track_count: 0,
          metadata_synced_at: null,
          tracks_synced_at: null,
          last_sync_error: "Malformed playlist payload",
          last_sync_error_at: "2026-05-02T10:30:00",
        },
      ],
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists/config");
    expect(fetchMock).not.toHaveBeenCalledWith("/api/streaming/playlists");
  });

  it("updates a streaming playlist sync mode", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url === "/api/streaming/playlists/13" && init?.method === "PATCH") {
        return {
          ok: true,
          json: async () => ({
            id: 13,
            account_id: 4,
            provider_playlist_id: "PL13",
            title: "Fresh Discoveries",
            sync_mode: "match_only",
            provider_track_count: 12,
            imported_track_count: 0,
            metadata_synced_at: null,
            tracks_synced_at: null,
            last_sync_error: null,
            last_sync_error_at: null,
          }),
        } as Response;
      }

      failUnexpectedFetch(url, init);
    });

    await expect(
      updateStreamingPlaylistConfig({
        playlistId: 13,
        sync_mode: "match_only",
      }),
    ).resolves.toMatchObject({
      id: 13,
      sync_mode: "match_only",
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists/13", {
      body: JSON.stringify({ sync_mode: "match_only" }),
      headers: {
        "Content-Type": "application/json",
      },
      method: "PATCH",
    });
  });

  it("queues a streaming account metadata refresh", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url === "/api/streaming/accounts/4/refresh-metadata" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            account_id: 4,
            job_id: "metadata-refresh-job-4",
          }),
        } as Response;
      }

      failUnexpectedFetch(url, init);
    });

    await expect(refreshStreamingAccountMetadata(4)).resolves.toEqual({
      account_id: 4,
      job_id: "metadata-refresh-job-4",
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/accounts/4/refresh-metadata", {
      method: "POST",
    });
  });

  it("exports a playlist M3U blob and filename", async () => {
    const blob = new Blob(["#EXTM3U\n/library/open-road.flac\n"], { type: "audio/x-mpegurl" });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      blob: async () => blob,
      headers: new Headers({
        "Content-Disposition": 'attachment; filename="Late Night Drive.m3u"',
      }),
    } as Response);

    await expect(exportPlaylistM3u(12)).resolves.toEqual({
      blob,
      filename: "Late Night Drive.m3u",
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/playlists/12/m3u");
  });

  it("does not run the detail query without a playlist id", () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const { result } = renderHook(() => usePlaylistDetailQuery(null), {
      wrapper: createWrapper(),
    });

    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.status).toBe("pending");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("runs the detail hook once a playlist id is available", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        playlist: {
          id: 9,
          account_id: 1,
          provider_playlist_id: "PL9",
          name: "Static Bloom",
          cover_art_url: null,
          sync_mode: "full",
          provider_track_count: 42,
          imported_track_count: 41,
          linked_count: 24,
          pending_count: 9,
          unlinked_count: 8,
          metadata_synced_at: null,
          tracks_synced_at: null,
          last_sync_error: null,
          last_sync_error_at: null,
        },
      }),
    } as Response);

    const { result } = renderHook(() => usePlaylistDetailQuery(9), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data?.playlist.name).toBe("Static Bloom");
  });

  it("runs the streaming playlists hook and returns sidebar playlist rows", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        playlists: [
          {
            id: 9,
            account_id: 1,
            provider_playlist_id: "PL9",
            title: "Static Bloom",
            sync_mode: "full",
            provider_track_count: 42,
            imported_track_count: 41,
            metadata_synced_at: null,
            tracks_synced_at: null,
            last_sync_error: null,
            last_sync_error_at: null,
          },
        ],
      }),
    } as Response);

    const { result } = renderHook(() => useStreamingPlaylistsQuery(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data?.playlists[0]).toMatchObject({
      id: 9,
      title: "Static Bloom",
      imported_track_count: 41,
    });
  });

  it("runs the streaming playlist config hook and returns selectable playlist rows", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        playlists: [
          {
            id: 9,
            account_id: 1,
            provider_playlist_id: "PL9",
            title: "Static Bloom",
            sync_mode: "match_only",
            provider_track_count: 42,
            imported_track_count: 41,
            metadata_synced_at: null,
            tracks_synced_at: null,
            last_sync_error: null,
            last_sync_error_at: null,
          },
        ],
      }),
    } as Response);

    const { result } = renderHook(() => useStreamingPlaylistConfigQuery(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data?.playlists[0]).toMatchObject({
      id: 9,
      title: "Static Bloom",
      sync_mode: "match_only",
    });
  });

  it("runs the tracks hook and returns playlist rows", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        tracks: [
          {
            id: 88,
            provider_track_id: "trk-88",
            position: 2,
            title: "Signal Loss",
            artist: "Phase Memory",
            album: null,
            duration_ms: 193000,
            status: "pending",
            local_track_id: null,
            proposal_id: 303,
            final_link_id: null,
          },
        ],
      }),
    } as Response);

    const { result } = renderHook(() => usePlaylistTracksQuery("9"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data?.tracks[0]).toMatchObject({
      id: 88,
      title: "Signal Loss",
      status: "pending",
      proposal_id: 303,
    });
  });

  it("runs the link proposals hook with confidence-band query state", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        proposals: [
          {
            id: 90,
            local_track_id: 12,
            local_album: null,
            local_artist: "Phase Memory",
            local_file_path: "Phase Memory/Signal Loss.flac",
            local_title: "Signal Loss",
            streaming_track_id: 88,
            streaming_title: "Signal Loss",
            streaming_artist: "Phase Memory",
            streaming_album: null,
            match_method: "isrc",
            score: 0.98,
            status: "pending",
            confidence_band: "high",
            rejected_at: null,
          },
        ],
      }),
    } as Response);

    const { result } = renderHook(() => useLinkProposalsQuery({ confidenceBand: "high" }), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data?.proposals[0]).toMatchObject({
      id: 90,
      confidence_band: "high",
      match_method: "isrc",
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/proposals?band=high");
  });
});
