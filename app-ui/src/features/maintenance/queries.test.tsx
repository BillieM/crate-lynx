import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import {
  fetchMissingLocallyTracks,
  fetchSoulseekCandidates,
  fetchUnidentifiedTracks,
  ignoreUnidentifiedTrack,
  maintenanceQueryKeys,
  rematchLocalTrack,
  rescueLocalTrackMetadata,
  restoreUnidentifiedTrack,
  searchMissingTrack,
  searchSelectedMissingTracks,
  enqueueSoulseekCandidate,
  refreshSoulseekAcquisition,
  retryUnidentifiedTrack,
  useMissingLocallyTracksQuery,
  useSoulseekCandidatesQuery,
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
    expect(maintenanceQueryKeys.soulseekCandidates("acq-1")).toEqual([
      "maintenance",
      "missing-locally",
      "soulseek",
      "acq-1",
    ]);
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
            playlist_ids: [11, 12],
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
          playlist_ids: [11, 12],
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
      }),
    } as Response);

    await expect(fetchUnidentifiedTracks()).resolves.toEqual({
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

  it("posts re-match to the API-prefixed local-track endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: "matching-job-1",
        local_track_id: 4001,
      }),
    } as Response);

    await expect(rematchLocalTrack(4001)).resolves.toEqual({
      job_id: "matching-job-1",
      local_track_id: 4001,
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/local-tracks/4001/rematch", {
      method: "POST",
    });
  });

  it("posts unidentified retry to the durable maintenance endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 4001,
        job_id: "ingestion-job-1",
        source_path: "ingestion/failed/unknown-import-9a4f.mp3",
      }),
    } as Response);

    await expect(retryUnidentifiedTrack(4001)).resolves.toEqual({
      id: 4001,
      job_id: "ingestion-job-1",
      source_path: "ingestion/failed/unknown-import-9a4f.mp3",
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/unidentified/4001/retry", {
      method: "POST",
    });
  });

  it("posts unidentified ignore to the durable maintenance endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 4001,
        ignored_at: "2026-05-03T11:00:00Z",
        source_path: "ingestion/failed/unknown-import-9a4f.mp3",
      }),
    } as Response);

    await expect(ignoreUnidentifiedTrack(4001)).resolves.toEqual({
      id: 4001,
      ignored_at: "2026-05-03T11:00:00Z",
      source_path: "ingestion/failed/unknown-import-9a4f.mp3",
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/unidentified/4001/ignore", {
      method: "POST",
    });
  });

  it("posts unidentified restore to the durable maintenance endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 4001,
        ignored_at: null,
        source_path: "ingestion/failed/unknown-import-9a4f.mp3",
      }),
    } as Response);

    await expect(restoreUnidentifiedTrack(4001)).resolves.toEqual({
      id: 4001,
      ignored_at: null,
      source_path: "ingestion/failed/unknown-import-9a4f.mp3",
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/unidentified/4001/restore", {
      method: "POST",
    });
  });

  it("calls Soulseek search, candidate, enqueue, and refresh endpoints", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      if (url === "/api/soulseek/missing-tracks/5001/search" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            acquisition: soulseekAcquisition("acq-1", "searching"),
            job_id: "search-job-1",
          }),
        } as Response;
      }

      if (url === "/api/soulseek/missing-tracks/search-selected" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            jobs: [{ acquisition: soulseekAcquisition("acq-1", "searching"), job_id: "search-job-1", streaming_track_id: 5001 }],
          }),
        } as Response;
      }

      if (url === "/api/soulseek/acquisitions/acq-1/candidates") {
        return {
          ok: true,
          json: async () => ({
            acquisition: soulseekAcquisition("acq-1", "candidates_found"),
            candidates: [
              {
                acquisition_id: "acq-1",
                bit_depth: 16,
                bit_rate: null,
                created_at: "2026-05-25T10:00:00Z",
                duration_seconds: 270,
                extension: ".flac",
                filename: "Jon Hopkins - Open Eye Signal.flac",
                has_free_upload_slot: true,
                id: "candidate-1",
                is_variable_bit_rate: null,
                queue_length: 0,
                sample_rate: 44100,
                score: 0.91,
                size: 30000000,
                slskd_search_id: "search-1",
                upload_speed: 500000,
                username: "peer",
              },
            ],
          }),
        } as Response;
      }

      if (url === "/api/soulseek/candidates/candidate-1/enqueue" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({ acquisition: soulseekAcquisition("acq-1", "queued"), job_id: "enqueue-job-1" }),
        } as Response;
      }

      if (url === "/api/soulseek/acquisitions/acq-1/refresh" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({ acquisition: soulseekAcquisition("acq-1", "downloading"), job_id: "refresh-job-1" }),
        } as Response;
      }

      throw new Error(`Unexpected request: ${String(url)}`);
    });

    await expect(searchMissingTrack(5001)).resolves.toMatchObject({ job_id: "search-job-1" });
    await expect(searchSelectedMissingTracks([5001])).resolves.toMatchObject({ jobs: [{ streaming_track_id: 5001 }] });
    await expect(fetchSoulseekCandidates("acq-1")).resolves.toMatchObject({
      candidates: [{ id: "candidate-1", username: "peer" }],
    });
    await expect(enqueueSoulseekCandidate("candidate-1")).resolves.toMatchObject({ job_id: "enqueue-job-1" });
    await expect(refreshSoulseekAcquisition("acq-1")).resolves.toMatchObject({ job_id: "refresh-job-1" });

    expect(fetchMock).toHaveBeenCalledWith("/api/soulseek/missing-tracks/search-selected", {
      body: JSON.stringify({ streaming_track_ids: [5001] }),
      headers: { "Content-Type": "application/json" },
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

  it("throws status-coded errors when row actions fail", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 409,
    } as Response);

    await expect(retryUnidentifiedTrack(4001)).rejects.toThrow("Unidentified retry request failed with status 409");
    await expect(ignoreUnidentifiedTrack(4001)).rejects.toThrow("Unidentified ignore request failed with status 409");
    await expect(restoreUnidentifiedTrack(4001)).rejects.toThrow("Unidentified restore request failed with status 409");
    await expect(rematchLocalTrack(4001)).rejects.toThrow("Re-match request failed with status 409");
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
            playlist_ids: [13],
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
            attempt_count: 2,
            can_rematch_local_track: true,
            can_rescue_metadata: false,
            failed_at: "2026-05-02T22:03:00Z",
            failure_reason: "Multiple low-confidence candidates",
            filename: "side-b-live-rip.flac",
            first_failed_at: "2026-05-02T21:58:00Z",
            id: 4002,
            ignored_at: null,
            local_track_id: 1004,
            source_mtime_ns: 1746218080000000000,
            source_path: "ingestion/failed/side-b-live-rip.flac",
            source_size: 9812,
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

  it("runs the Soulseek candidates hook", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        acquisition: soulseekAcquisition("acq-1", "candidates_found"),
        candidates: [],
      }),
    } as Response);

    const { result } = renderHook(() => useSoulseekCandidatesQuery("acq-1"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data?.acquisition.id).toBe("acq-1");
  });
});

function soulseekAcquisition(id: string, status: string) {
  return {
    candidate_count: status === "candidates_found" ? 1 : 0,
    enqueue_job_id: null,
    error_detail: null,
    id,
    job_id: null,
    refresh_job_id: null,
    selected_candidate_id: null,
    slskd_batch_id: null,
    status,
  };
}
