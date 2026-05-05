import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import {
  fetchMissingLocallyTracks,
  fetchUnidentifiedTracks,
  maintenanceQueryKeys,
  rescueLocalTrackMetadata,
  useMissingLocallyTracksQuery,
  useUnidentifiedTracksQuery,
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

describe("maintenance queries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("builds stable query keys for maintenance reports", () => {
    expect(maintenanceQueryKeys.all).toEqual(["maintenance"]);
    expect(maintenanceQueryKeys.missingLocally()).toEqual(["maintenance", "missing-locally"]);
    expect(maintenanceQueryKeys.unidentified()).toEqual(["maintenance", "unidentified"]);
  });

  it("fetches missing-locally rows from the backend report endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        tracks: [
          {
            album: "Immunity",
            artist: "Jon Hopkins",
            duration_ms: 270000,
            id: 5001,
            playlist_count: 2,
            playlist_titles: ["Late Night Drive", "Focus Queue"],
            provider_track_id: "ytm:track-5001",
            title: "Open Eye Signal",
          },
        ],
      }),
    } as Response);

    await expect(fetchMissingLocallyTracks()).resolves.toEqual({
      tracks: [
        {
          album: "Immunity",
          artist: "Jon Hopkins",
          duration_ms: 270000,
          id: 5001,
          playlist_count: 2,
          playlist_titles: ["Late Night Drive", "Focus Queue"],
          provider_track_id: "ytm:track-5001",
          title: "Open Eye Signal",
        },
      ],
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/missing-locally");
  });

  it("fetches unidentified rows from the chosen durable maintenance route", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        tracks: [
          {
            failed_at: "2026-05-02T21:44:00Z",
            failure_reason: "Beets could not identify metadata",
            filename: "unknown-import-9a4f.mp3",
            id: 4001,
            local_track_id: null,
            source_path: "ingestion/failed/unknown-import-9a4f.mp3",
          },
        ],
      }),
    } as Response);

    await expect(fetchUnidentifiedTracks()).resolves.toEqual({
      tracks: [
        {
          failed_at: "2026-05-02T21:44:00Z",
          failure_reason: "Beets could not identify metadata",
          filename: "unknown-import-9a4f.mp3",
          id: 4001,
          local_track_id: null,
          source_path: "ingestion/failed/unknown-import-9a4f.mp3",
        },
      ],
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/unidentified");
  });

  it("posts metadata rescue to the API-prefixed rescue endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        beets_id: 12,
        file_path: "Artist/rescue.mp3",
        id: 4001,
        library_root_rel_path: "Artist/rescue.mp3",
      }),
    } as Response);

    await expect(rescueLocalTrackMetadata(4001)).resolves.toMatchObject({
      id: 4001,
      library_root_rel_path: "Artist/rescue.mp3",
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/local-tracks/4001/rescue", {
      method: "POST",
    });
  });

  it("throws a status-coded error when a maintenance report request fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 500,
    } as Response);

    await expect(fetchMissingLocallyTracks()).rejects.toThrow("Request failed with status 500");
  });

  it("throws a status-coded error when rescue fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 409,
    } as Response);

    await expect(rescueLocalTrackMetadata(4001)).rejects.toThrow("Metadata rescue request failed with status 409");
  });

  it("runs the missing-locally hook", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        tracks: [
          {
            album: null,
            artist: "Kelly Lee Owens",
            duration_ms: 221000,
            id: 5003,
            playlist_count: 1,
            playlist_titles: ["New Imports"],
            provider_track_id: "ytm:track-5003",
            title: "Melt!",
          },
        ],
      }),
    } as Response);

    const { result } = renderHook(() => useMissingLocallyTracksQuery(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data?.tracks[0]).toMatchObject({
      id: 5003,
      playlist_count: 1,
    });
  });

  it("runs the unidentified hook", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        tracks: [
          {
            failed_at: "2026-05-02T22:03:00Z",
            failure_reason: "Multiple low-confidence candidates",
            filename: "side-b-live-rip.flac",
            id: 4002,
            local_track_id: 1004,
            source_path: "ingestion/failed/side-b-live-rip.flac",
          },
        ],
      }),
    } as Response);

    const { result } = renderHook(() => useUnidentifiedTracksQuery(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data?.tracks[0]).toMatchObject({
      id: 4002,
      local_track_id: 1004,
    });
  });
});
