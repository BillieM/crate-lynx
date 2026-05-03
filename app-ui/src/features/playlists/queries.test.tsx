import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import {
  exportPlaylistM3u,
  fetchPlaylistDetail,
  fetchPlaylistTracks,
  playlistQueryKeys,
  usePlaylistDetailQuery,
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

describe("playlist queries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("builds stable query keys per playlist resource", () => {
    expect(playlistQueryKeys.all).toEqual(["playlists"]);
    expect(playlistQueryKeys.detail(12)).toEqual(["playlists", 12, "detail"]);
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
          track_count: 62,
          linked_count: 58,
          pending_count: 3,
          unlinked_count: 1,
          synced_at: "2026-05-01T09:00:00",
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
        track_count: 62,
        linked_count: 58,
        pending_count: 3,
        unlinked_count: 1,
        synced_at: "2026-05-01T09:00:00",
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
          track_count: 41,
          linked_count: 24,
          pending_count: 9,
          unlinked_count: 8,
          synced_at: null,
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
});
