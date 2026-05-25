import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createPlaylistGenerationRun,
  fetchGeneratedPlaylistTracks,
  fetchSonicGenerationPreview,
  fetchSonicFeatureSummary,
  fetchSonicRuns,
  sonicQueryKeys,
} from "./queries";

describe("sonic queries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("builds stable query keys", () => {
    expect(sonicQueryKeys.featureSummary()).toEqual(["sonic", "features", "summary"]);
    expect(sonicQueryKeys.runs()).toEqual(["sonic", "runs"]);
    expect(sonicQueryKeys.run(12)).toEqual(["sonic", "runs", 12]);
    expect(sonicQueryKeys.generatedPlaylists()).toEqual(["sonic", "generated-playlists"]);
    expect(sonicQueryKeys.playlistTracks(7)).toEqual(["sonic", "generated-playlists", 7, "tracks"]);
    expect(
      sonicQueryKeys.preview({
        generation_config: {
          clustering_method: "kmeans",
          feature_profile: "balanced_v1",
          max_children: 4,
          max_depth: 2,
          min_playlist_size: 8,
          random_seed: 42,
          target_playlist_size: 25,
        },
        source_filter: {
          source_type: "all_local",
          streaming_playlist_ids: [],
          tag_filters: [],
        },
      }),
    ).toEqual([
      "sonic",
      "runs",
      "preview",
      {
        generation_config: {
          clustering_method: "kmeans",
          feature_profile: "balanced_v1",
          max_children: 4,
          max_depth: 2,
          min_playlist_size: 8,
          random_seed: 42,
          target_playlist_size: 25,
        },
        source_filter: {
          source_type: "all_local",
          streaming_playlist_ids: [],
          tag_filters: [],
        },
      },
    ]);
  });

  it("fetches feature summary and generation runs", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/sonic/features/summary") {
        return jsonResponse({
          failed_tracks: 1,
          missing_tracks: 2,
          pending_tracks: 3,
          ready_tracks: 4,
          total_tracks: 10,
        });
      }
      if (url === "/api/sonic/runs") {
        return jsonResponse({
          runs: [
            {
              completed_at: null,
              created_at: "2026-05-24T12:00:00Z",
              error_detail: null,
              generation_config: { clustering_method: "kmeans" },
              id: 99,
              playlist_count: 0,
              source_filter: { source_type: "all_local" },
              status: "pending",
              track_count: 0,
              updated_at: "2026-05-24T12:00:00Z",
            },
          ],
        });
      }
      throw new Error(`Unexpected fetch request: ${url}`);
    });

    await expect(fetchSonicFeatureSummary()).resolves.toMatchObject({ ready_tracks: 4 });
    await expect(fetchSonicRuns()).resolves.toMatchObject({ runs: [{ id: 99, status: "pending" }] });
    expect(fetchMock).toHaveBeenCalledWith("/api/sonic/features/summary");
    expect(fetchMock).toHaveBeenCalledWith("/api/sonic/runs");
  });

  it("creates a playlist generation run", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      jsonResponse(
        {
          job_id: "job-1",
          run: {
            completed_at: null,
            created_at: "2026-05-24T12:00:00Z",
            error_detail: null,
            generation_config: { clustering_method: "agglomerative" },
            id: 100,
            playlist_count: 0,
            source_filter: { source_type: "all_local" },
            status: "pending",
            track_count: 0,
            updated_at: "2026-05-24T12:00:00Z",
          },
        },
      ),
    );

    await expect(
      createPlaylistGenerationRun({
        generation_config: {
          clustering_method: "agglomerative",
          feature_profile: "balanced_v1",
          max_children: 3,
          max_depth: 2,
          min_playlist_size: 4,
          random_seed: 9,
          target_playlist_size: 12,
        },
        source_filter: {
          source_type: "all_local",
          streaming_playlist_ids: [],
          tag_filters: [],
        },
      }),
    ).resolves.toMatchObject({ job_id: "job-1", run: { id: 100 } });

    expect(fetchMock).toHaveBeenCalledWith("/api/sonic/runs", {
      body: JSON.stringify({
        generation_config: {
          clustering_method: "agglomerative",
          feature_profile: "balanced_v1",
          max_children: 3,
          max_depth: 2,
          min_playlist_size: 4,
          random_seed: 9,
          target_playlist_size: 12,
        },
        source_filter: {
          source_type: "all_local",
          streaming_playlist_ids: [],
          tag_filters: [],
        },
      }),
      headers: {
        "Content-Type": "application/json",
      },
      method: "POST",
    });
  });

  it("fetches a playlist generation preview", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      jsonResponse({
        analyzer_key: "librosa_v1",
        analyzer_version: "1",
        can_generate: true,
        failed_feature_count: 1,
        feature_profile: "energy_v1",
        missing_feature_count: 2,
        pending_feature_count: 3,
        ready_track_count: 12,
        skipped_track_count: 6,
        source_track_count: 18,
      }),
    );
    const payload = {
      generation_config: {
        clustering_method: "kmeans" as const,
        feature_profile: "energy_v1" as const,
        max_children: 4,
        max_depth: 2,
        min_playlist_size: 8,
        random_seed: 42,
        target_playlist_size: 25,
      },
      source_filter: {
        source_type: "all_local" as const,
        streaming_playlist_ids: [],
        tag_filters: [],
      },
    };

    await expect(fetchSonicGenerationPreview(payload)).resolves.toMatchObject({
      can_generate: true,
      ready_track_count: 12,
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/sonic/runs/preview", {
      body: JSON.stringify(payload),
      headers: {
        "Content-Type": "application/json",
      },
      method: "POST",
    });
  });

  it("fetches generated playlist tracks", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
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
    );

    await expect(fetchGeneratedPlaylistTracks(7001)).resolves.toMatchObject({
      tracks: [{ local_track_id: 501, title: "Night Runner" }],
    });
  });
});

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return {
    ok: init.status === undefined || (init.status >= 200 && init.status < 300),
    status: init.status ?? 200,
    json: async () => body,
  } as Response;
}
