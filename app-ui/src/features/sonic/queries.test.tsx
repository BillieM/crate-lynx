import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createPlaylistGenerationRecipe,
  createPlaylistGenerationRun,
  deletePlaylistGenerationRecipe,
  deletePlaylistGenerationRun,
  fetchPlaylistGenerationRecipes,
  fetchGeneratedPlaylistTracks,
  fetchSonicGenerationPreview,
  fetchSonicFeatureSummary,
  fetchSonicRuns,
  regeneratePlaylistGenerationRecipe,
  sonicQueryKeys,
  updatePlaylistGenerationRecipe,
} from "./queries";

describe("sonic queries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("builds stable query keys", () => {
    expect(sonicQueryKeys.featureSummary()).toEqual(["sonic", "features", "summary"]);
    expect(sonicQueryKeys.runs()).toEqual(["sonic", "runs"]);
    expect(sonicQueryKeys.run(12)).toEqual(["sonic", "runs", 12]);
    expect(sonicQueryKeys.recipes()).toEqual(["sonic", "recipes"]);
    expect(sonicQueryKeys.recipe(8)).toEqual(["sonic", "recipes", 8]);
    expect(sonicQueryKeys.generatedPlaylists()).toEqual(["sonic", "generated-playlists"]);
    expect(sonicQueryKeys.playlistTracks(7)).toEqual(["sonic", "generated-playlists", 7, "tracks"]);
    expect(
      sonicQueryKeys.preview({
        generation_config: {
          clustering_method: "kmeans",
          diversity_mode: "balanced_v1",
          feature_profile: "balanced_v1",
          max_children: 4,
          max_depth: 2,
          min_playlist_size: 8,
          naming_strategy: "dj_utility_v1",
          ordering_strategy: "profile_nearest_neighbor_rolling_v2",
          output_scope: "tree_v1",
          preset_key: "dj_crate_tree_v1",
          random_seed: 42,
          semantic_mode: "off",
          semantic_weight: 0.15,
          sequencing_intent: "smooth_mix",
          target_playlist_size: 25,
          tempo_mode: "mixable_v1",
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
          diversity_mode: "balanced_v1",
          feature_profile: "balanced_v1",
          max_children: 4,
          max_depth: 2,
          min_playlist_size: 8,
          naming_strategy: "dj_utility_v1",
          ordering_strategy: "profile_nearest_neighbor_rolling_v2",
          output_scope: "tree_v1",
          preset_key: "dj_crate_tree_v1",
          random_seed: 42,
          semantic_mode: "off",
          semantic_weight: 0.15,
          sequencing_intent: "smooth_mix",
          target_playlist_size: 25,
          tempo_mode: "mixable_v1",
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
              generation_number: 19,
              id: 99,
              playlist_count: 0,
              run_name: "Generation 19",
              source_filter: { source_type: "all_local" },
              status: "pending",
              track_count: 0,
              trigger: "manual",
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
            generation_number: 20,
            id: 100,
            playlist_count: 0,
            run_name: "Generation 20",
            source_filter: { source_type: "all_local" },
            status: "pending",
            track_count: 0,
            trigger: "manual",
            updated_at: "2026-05-24T12:00:00Z",
          },
        },
      ),
    );

    await expect(
      createPlaylistGenerationRun({
        generation_config: {
          clustering_method: "agglomerative",
          diversity_mode: "strict_v1",
          feature_profile: "balanced_v1",
          max_children: 3,
          max_depth: 2,
          min_playlist_size: 4,
          naming_strategy: "crate_label_v1",
          ordering_strategy: "seeded_shuffle_v1",
          output_scope: "leaf_only_v1",
          preset_key: "discovery_sampler_v1",
          random_seed: 9,
          semantic_mode: "off",
          semantic_weight: 0.15,
          sequencing_intent: "varied_listening",
          target_playlist_size: 12,
          tempo_mode: "mixable_v1",
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
          diversity_mode: "strict_v1",
          feature_profile: "balanced_v1",
          max_children: 3,
          max_depth: 2,
          min_playlist_size: 4,
          naming_strategy: "crate_label_v1",
          ordering_strategy: "seeded_shuffle_v1",
          output_scope: "leaf_only_v1",
          preset_key: "discovery_sampler_v1",
          random_seed: 9,
          semantic_mode: "off",
          semantic_weight: 0.15,
          sequencing_intent: "varied_listening",
          target_playlist_size: 12,
          tempo_mode: "mixable_v1",
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
        current_feature_count: 12,
        failed_feature_count: 1,
        feature_profile: "energy_v1",
        missing_feature_count: 2,
        legacy_descriptor_feature_count: 0,
        pending_feature_count: 3,
        confidence: 0.81,
        coverage: 0.9,
        playlists: [
          {
            boundary_tracks: [
              {
                artist: "Night Driver",
                local_track_id: 2,
                title: "Edge Signal",
              },
            ],
            client_key: "uk-garage-rolling",
            cohesion: 0.84,
            confidence: 0.82,
            coverage: 0.92,
            depth: 1,
            export_default: true,
            name: "UK Garage / Rolling / 128–134 BPM",
            outlier_tracks: [],
            parent_key: "rolling",
            representative_tracks: [
              {
                artist: "Frame Delay",
                local_track_id: 1,
                title: "Night Runner",
              },
            ],
            sequencing: { intent: "smooth_mix" },
            sequencing_intent: "smooth_mix",
            size: 12,
            skipped_reasons: {},
            warnings: ["Two tracks used descriptor-only fallback."],
          },
        ],
        projection: {
          config_notes: [],
          depth_counts: { "0": 1, "1": 2 },
          leaf_playlist_count: 2,
          mode: "estimated",
          playlist_count: 3,
          sample_names: ["Peak 128 BPM"],
          size_max: 6,
          size_median: 6,
          size_min: 6,
        },
        ready_track_count: 12,
        skipped_reasons: { awaiting_analysis: 3 },
        skipped_track_count: 6,
        source_track_count: 18,
        warnings: ["Semantic features were unavailable for 2 tracks."],
      }),
    );
    const payload = {
      generation_config: {
        clustering_method: "kmeans" as const,
        diversity_mode: "balanced_v1" as const,
        feature_profile: "energy_v1" as const,
        max_children: 4,
        max_depth: 2,
        min_playlist_size: 8,
        naming_strategy: "dj_utility_v1" as const,
        ordering_strategy: "profile_nearest_neighbor_rolling_v2" as const,
        output_scope: "tree_v1" as const,
        preset_key: "dj_crate_tree_v1" as const,
        random_seed: 42,
        semantic_mode: "off" as const,
        semantic_weight: 0.15,
        sequencing_intent: "smooth_mix" as const,
        target_playlist_size: 25,
        tempo_mode: "mixable_v1" as const,
      },
      source_filter: {
        source_type: "all_local" as const,
        streaming_playlist_ids: [],
        tag_filters: [],
      },
    };

    await expect(fetchSonicGenerationPreview(payload)).resolves.toMatchObject({
      can_generate: true,
      playlists: [
        {
          name: "UK Garage / Rolling / 128–134 BPM",
          representative_tracks: [{ title: "Night Runner" }],
        },
      ],
      projection: { playlist_count: 3 },
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

  it("creates, updates, regenerates, lists, and deletes named generation recipes", async () => {
    const recipe = {
      created_at: "2026-07-25T20:00:00Z",
      enabled: true,
      export_config: {
        enabled: true,
        formats: ["m3u8"],
        path_format: "absolute",
        profile_id: 4,
        scope: "leaf_only",
      },
      generation_config: {
        clustering_method: "dj_hierarchical_v1",
        diversity_mode: "balanced_v1",
        feature_profile: "balanced_v1",
        max_children: 4,
        max_depth: 2,
        min_playlist_size: 8,
        naming_strategy: "dj_utility_v1",
        ordering_strategy: "profile_nearest_neighbor_rolling_v2",
        output_scope: "leaf_only_v1",
        preset_key: "dj_crate_tree_v1",
        random_seed: 42,
        semantic_mode: "off",
        semantic_weight: 0.15,
        sequencing_intent: "smooth_mix",
        target_playlist_size: 25,
        tempo_mode: "mixable_v1",
      },
      id: 8,
      last_regenerated_at: null,
      last_run_id: null,
      name: "Friday warm-up crates",
      regenerate_on_change: true,
      source_filter: { source_type: "all_local" },
      updated_at: "2026-07-25T20:00:00Z",
    };
    const payload = {
      enabled: true,
      export_config: {
        enabled: true,
        formats: ["m3u8"],
        path_format: "absolute",
        profile_id: 4,
        scope: "leaf_only",
      },
      generation_config: {
        clustering_method: "dj_hierarchical_v1" as const,
        diversity_mode: "balanced_v1" as const,
        feature_profile: "balanced_v1" as const,
        max_children: 4,
        max_depth: 2,
        min_playlist_size: 8,
        naming_strategy: "dj_utility_v1" as const,
        ordering_strategy: "profile_nearest_neighbor_rolling_v2" as const,
        output_scope: "leaf_only_v1" as const,
        preset_key: "dj_crate_tree_v1" as const,
        random_seed: 42,
        semantic_mode: "off" as const,
        semantic_weight: 0.15,
        sequencing_intent: "smooth_mix" as const,
        target_playlist_size: 25,
        tempo_mode: "mixable_v1" as const,
      },
      name: "Friday warm-up crates",
      regenerate_on_change: true,
      source_filter: { source_type: "all_local" as const },
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/api/sonic/recipes" && init?.method === undefined) {
        return jsonResponse({ recipes: [recipe] });
      }
      if (url === "/api/sonic/recipes" && init?.method === "POST") {
        return jsonResponse(recipe);
      }
      if (url === "/api/sonic/recipes/8" && init?.method === "PUT") {
        return jsonResponse({ ...recipe, name: "Updated warm-up crates" });
      }
      if (url === "/api/sonic/recipes/8/regenerate" && init?.method === "POST") {
        return jsonResponse({
          job_id: "recipe-job-8",
          recipe,
          run: {
            completed_at: null,
            created_at: "2026-07-25T20:01:00Z",
            error_detail: null,
            generation_config: recipe.generation_config,
            generation_number: 81,
            id: 81,
            playlist_count: 0,
            run_name: "Friday warm-up crates",
            source_filter: recipe.source_filter,
            status: "pending",
            track_count: 0,
            trigger: "recipe",
            updated_at: "2026-07-25T20:01:00Z",
          },
        });
      }
      if (url === "/api/sonic/recipes/8" && init?.method === "DELETE") {
        return jsonResponse(undefined, { status: 204 });
      }
      throw new Error(`Unexpected fetch request: ${init?.method ?? "GET"} ${url}`);
    });

    await expect(fetchPlaylistGenerationRecipes()).resolves.toMatchObject({ recipes: [{ id: 8 }] });
    await expect(createPlaylistGenerationRecipe(payload)).resolves.toMatchObject({ id: 8 });
    await expect(updatePlaylistGenerationRecipe(8, { ...payload, name: "Updated warm-up crates" })).resolves.toMatchObject({
      name: "Updated warm-up crates",
    });
    await expect(regeneratePlaylistGenerationRecipe(8)).resolves.toMatchObject({ run_id: 81 });
    await expect(deletePlaylistGenerationRecipe(8)).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith("/api/sonic/recipes/8/regenerate", {
      body: JSON.stringify({}),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    });
  });

  it("deletes a playlist generation run", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(undefined, { status: 204 }));

    await expect(deletePlaylistGenerationRun(50)).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith("/api/sonic/runs/50", {
      method: "DELETE",
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
