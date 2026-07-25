import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { deleteJson, endpoints, fetchJson, postJson, putJson } from "../../lib/api";
import type { components } from "../../lib/api-types";
import { shellSummaryInvalidationKeys } from "../shell/queries";

type ApiSchemas = components["schemas"];

export type SonicFeatureSummary = ApiSchemas["SonicFeatureSummaryResponse"];
export type SonicBackfillRequest = ApiSchemas["SonicBackfillRequest"];
export type SonicBackfillResponse = ApiSchemas["SonicBackfillResponse"];
export type SonicTagFilter = ApiSchemas["SonicTagFilterRequest"];
export type SonicSourceFilter = ApiSchemas["SonicSourceFilterRequest"];
export type PlaylistGenerationConfig = ApiSchemas["PlaylistGenerationConfigRequest"];
export type CreatePlaylistGenerationRunRequest = ApiSchemas["CreatePlaylistGenerationRunRequest"];
export type CreatePlaylistGenerationRunResponse = ApiSchemas["CreatePlaylistGenerationRunResponse"];
export type PlaylistGenerationProjection = ApiSchemas["PlaylistGenerationProjectionResponse"];
export type PlaylistGenerationRun = ApiSchemas["PlaylistGenerationRunResponse"];
export type PlaylistGenerationRunListResponse = ApiSchemas["PlaylistGenerationRunListResponse"];
export type DeletePlaylistGenerationRunsRequest = ApiSchemas["DeletePlaylistGenerationRunsRequest"];
export type DeletePlaylistGenerationRunsResponse = ApiSchemas["DeletePlaylistGenerationRunsResponse"];
export type GeneratedPlaylist = ApiSchemas["GeneratedPlaylistResponse"];
export type GeneratedPlaylistListResponse = ApiSchemas["GeneratedPlaylistListResponse"];
export type PlaylistGenerationRunDetailResponse = ApiSchemas["PlaylistGenerationRunDetailResponse"];
export type GeneratedPlaylistTrack = ApiSchemas["GeneratedPlaylistTrackResponse"];
export type GeneratedPlaylistTracksResponse = ApiSchemas["GeneratedPlaylistTracksResponse"];

export type SequenceIntent = PlaylistGenerationConfig["sequencing_intent"];
export type SonicPreviewTrack = ApiSchemas["SonicPreviewTrackEvidenceResponse"];
export type SonicPreviewPlaylist = ApiSchemas["SonicGenerationPlaylistPreviewResponse"];
export type SonicGenerationPreview = ApiSchemas["SonicGenerationPreviewResponse"];
export type PlaylistGenerationRecipe = ApiSchemas["PlaylistGenerationRecipeResponse"];
export type PlaylistGenerationRecipeListResponse = ApiSchemas["PlaylistGenerationRecipeListResponse"];
export type SavePlaylistGenerationRecipeRequest = ApiSchemas["PlaylistGenerationRecipeUpsertRequest"];

export type RegeneratePlaylistGenerationRecipeResponse = {
  job_id: string | null;
  run_id: number;
  run_name: string;
};

const nullableStringSchema = z.string().nullable();
const dateStringSchema = z.string();
const runStatusSchema = z.enum(["pending", "running", "completed", "failed"]);
const generationRunPollingIntervalMs = 2_000;
const previewTrackSchema: z.ZodType<SonicPreviewTrack> = z.object({
  artist: nullableStringSchema.optional(),
  distance_from_center: z.number().nullable().optional(),
  local_track_id: z.number(),
  title: nullableStringSchema.optional(),
});

const sonicFeatureSummarySchema: z.ZodType<SonicFeatureSummary> = z.object({
  failed_tracks: z.number(),
  missing_tracks: z.number(),
  pending_tracks: z.number(),
  ready_tracks: z.number(),
  total_tracks: z.number(),
});

const sonicBackfillResponseSchema: z.ZodType<SonicBackfillResponse> = z.object({
  job_id: z.string(),
  limit: z.number(),
});

const playlistGenerationProjectionSchema: z.ZodType<PlaylistGenerationProjection> = z.object({
  config_notes: z.array(z.string()),
  depth_counts: z.record(z.string(), z.number()),
  leaf_playlist_count: z.number(),
  mode: z.string(),
  playlist_count: z.number(),
  sample_names: z.array(z.string()),
  size_max: z.number(),
  size_median: z.number(),
  size_min: z.number(),
});

const sonicPreviewPlaylistSchema: z.ZodType<SonicPreviewPlaylist> = z.object({
  boundary_tracks: z.array(previewTrackSchema),
  client_key: z.string(),
  cohesion: z.number(),
  confidence: z.number(),
  coverage: z.number(),
  depth: z.number(),
  export_default: z.boolean(),
  name: z.string(),
  outlier_tracks: z.array(previewTrackSchema),
  parent_key: nullableStringSchema,
  representative_tracks: z.array(previewTrackSchema),
  sequencing: z.record(z.string(), z.unknown()),
  sequencing_intent: z.string(),
  size: z.number(),
  skipped_reasons: z.record(z.string(), z.number()),
  warnings: z.array(z.string()),
});

const sonicGenerationPreviewSchema: z.ZodType<SonicGenerationPreview> = z.object({
  analyzer_evidence: z.record(z.string(), z.unknown()).optional(),
  analyzer_key: z.string(),
  analyzer_version: z.string(),
  can_generate: z.boolean(),
  confidence: z.number(),
  coverage: z.number(),
  current_feature_count: z.number(),
  failed_feature_count: z.number(),
  feature_profile: z.string(),
  legacy_descriptor_feature_count: z.number(),
  missing_feature_count: z.number(),
  pending_feature_count: z.number(),
  playlists: z.array(sonicPreviewPlaylistSchema).optional(),
  projection: playlistGenerationProjectionSchema.nullable(),
  ready_track_count: z.number(),
  readiness: z.record(z.string(), z.unknown()).optional(),
  skipped_reasons: z.record(z.string(), z.number()).optional(),
  skipped_track_count: z.number(),
  source_track_count: z.number(),
  warnings: z.array(z.string()).optional(),
});

const playlistGenerationRecipeSchema: z.ZodType<PlaylistGenerationRecipe> = z.object({
  created_at: dateStringSchema,
  enabled: z.boolean(),
  export_config: z.record(z.string(), z.unknown()).nullable().default(null),
  generation_config: z.record(z.string(), z.unknown()),
  id: z.number(),
  last_regenerated_at: nullableStringSchema.default(null),
  last_run_id: z.number().nullable().default(null),
  name: z.string(),
  regenerate_on_change: z.boolean(),
  source_filter: z.record(z.string(), z.unknown()),
  updated_at: dateStringSchema,
});

const playlistGenerationRecipeListSchema: z.ZodType<PlaylistGenerationRecipeListResponse> = z.object({
  recipes: z.array(playlistGenerationRecipeSchema),
});

const playlistGenerationRunSchema: z.ZodType<PlaylistGenerationRun> = z.object({
  analyzer_evidence: z.record(z.string(), z.unknown()).nullable().optional(),
  completed_at: nullableStringSchema,
  created_at: dateStringSchema,
  error_detail: nullableStringSchema,
  generation_config: z.record(z.string(), z.unknown()),
  generation_number: z.number(),
  id: z.number(),
  playlist_count: z.number(),
  readiness_summary: z.record(z.string(), z.unknown()).nullable().optional(),
  recipe_id: z.number().nullable().optional(),
  run_name: z.string(),
  source_filter: z.record(z.string(), z.unknown()),
  status: runStatusSchema,
  track_count: z.number(),
  trigger: z.string(),
  updated_at: dateStringSchema,
});

const regeneratePlaylistGenerationRecipeSchema: z.ZodType<RegeneratePlaylistGenerationRecipeResponse> = z
  .object({
    job_id: z.string(),
    recipe: playlistGenerationRecipeSchema,
    run: playlistGenerationRunSchema,
  })
  .transform((response) =>
    ({
      job_id: response.job_id,
      run_id: response.run.id,
      run_name: response.run.run_name,
    }),
  );

const generatedPlaylistSchema: z.ZodType<GeneratedPlaylist> = z.object({
  created_at: dateStringSchema,
  depth: z.number(),
  id: z.number(),
  name: z.string(),
  parent_playlist_id: z.number().nullable(),
  position: z.number(),
  run_id: z.number(),
  summary: z.record(z.string(), z.unknown()),
  track_count: z.number(),
});

const sonicRunsResponseSchema: z.ZodType<PlaylistGenerationRunListResponse> = z.object({
  runs: z.array(playlistGenerationRunSchema),
});

const deletePlaylistGenerationRunsResponseSchema: z.ZodType<DeletePlaylistGenerationRunsResponse> = z.object({
  deleted_run_ids: z.array(z.number()),
  missing_run_ids: z.array(z.number()),
  skipped_active_run_ids: z.array(z.number()),
});

const generatedPlaylistsResponseSchema: z.ZodType<GeneratedPlaylistListResponse> = z.object({
  playlists: z.array(generatedPlaylistSchema),
});

const sonicRunDetailResponseSchema: z.ZodType<PlaylistGenerationRunDetailResponse> = z.object({
  playlists: z.array(generatedPlaylistSchema),
  run: playlistGenerationRunSchema,
});

const generatedPlaylistTrackSchema: z.ZodType<GeneratedPlaylistTrack> = z.object({
  album: nullableStringSchema,
  artist: nullableStringSchema,
  duration_ms: z.number().nullable(),
  file_path: z.string(),
  id: z.number(),
  library_root_rel_path: z.string(),
  local_track_id: z.number(),
  position: z.number(),
  title: z.string(),
});

const generatedPlaylistTracksResponseSchema: z.ZodType<GeneratedPlaylistTracksResponse> = z.object({
  tracks: z.array(generatedPlaylistTrackSchema),
});

export const sonicQueryKeys = {
  all: ["sonic"] as const,
  featureSummary: () => ["sonic", "features", "summary"] as const,
  generatedPlaylists: () => ["sonic", "generated-playlists"] as const,
  playlistTracks: (playlistId: number | string) => ["sonic", "generated-playlists", playlistId, "tracks"] as const,
  preview: (payload: CreatePlaylistGenerationRunRequest) => ["sonic", "runs", "preview", payload] as const,
  recipe: (recipeId: number | string) => ["sonic", "recipes", recipeId] as const,
  recipes: () => ["sonic", "recipes"] as const,
  run: (runId: number | string) => ["sonic", "runs", runId] as const,
  runs: () => ["sonic", "runs"] as const,
};

function isGenerationRunActive(run: PlaylistGenerationRun | undefined) {
  return run?.status === "pending" || run?.status === "running";
}

export async function fetchSonicFeatureSummary(): Promise<SonicFeatureSummary> {
  return fetchJson(endpoints.api("/sonic/features/summary"), sonicFeatureSummarySchema);
}

export async function backfillSonicFeatures(payload: SonicBackfillRequest): Promise<SonicBackfillResponse> {
  return postJson(endpoints.api("/sonic/features/backfill"), {
    body: payload,
    schema: sonicBackfillResponseSchema,
  });
}

export async function fetchSonicGenerationPreview(
  payload: CreatePlaylistGenerationRunRequest,
): Promise<SonicGenerationPreview> {
  return postJson(endpoints.api("/sonic/runs/preview"), {
    body: payload,
    schema: sonicGenerationPreviewSchema,
  });
}

export async function fetchSonicRuns(): Promise<PlaylistGenerationRunListResponse> {
  return fetchJson(endpoints.api("/sonic/runs"), sonicRunsResponseSchema);
}

export async function fetchPlaylistGenerationRecipes(): Promise<PlaylistGenerationRecipeListResponse> {
  return fetchJson(endpoints.api("/sonic/recipes"), playlistGenerationRecipeListSchema);
}

export async function createPlaylistGenerationRecipe(
  payload: SavePlaylistGenerationRecipeRequest,
): Promise<PlaylistGenerationRecipe> {
  return postJson(endpoints.api("/sonic/recipes"), {
    body: payload,
    errorMessage: "Generation recipe create request failed",
    schema: playlistGenerationRecipeSchema,
  });
}

export async function updatePlaylistGenerationRecipe(
  recipeId: number | string,
  payload: SavePlaylistGenerationRecipeRequest,
): Promise<PlaylistGenerationRecipe> {
  return putJson(endpoints.api(`/sonic/recipes/${encodeURIComponent(String(recipeId))}`), {
    body: payload,
    errorMessage: "Generation recipe update request failed",
    schema: playlistGenerationRecipeSchema,
  });
}

export async function deletePlaylistGenerationRecipe(recipeId: number | string): Promise<void> {
  await deleteJson<void>(endpoints.api(`/sonic/recipes/${encodeURIComponent(String(recipeId))}`), {
    errorMessage: "Generation recipe delete request failed",
  });
}

export async function regeneratePlaylistGenerationRecipe(
  recipeId: number | string,
): Promise<RegeneratePlaylistGenerationRecipeResponse> {
  return postJson(endpoints.api(`/sonic/recipes/${encodeURIComponent(String(recipeId))}/regenerate`), {
    body: {},
    errorMessage: "Generation recipe regeneration request failed",
    schema: regeneratePlaylistGenerationRecipeSchema,
  });
}

export async function createPlaylistGenerationRun(
  payload: CreatePlaylistGenerationRunRequest,
): Promise<CreatePlaylistGenerationRunResponse> {
  return postJson(endpoints.api("/sonic/runs"), {
    body: payload,
  });
}

export async function fetchSonicRunDetail(runId: number | string): Promise<PlaylistGenerationRunDetailResponse> {
  return fetchJson(endpoints.api(`/sonic/runs/${runId}`), sonicRunDetailResponseSchema);
}

export async function deletePlaylistGenerationRun(runId: number | string): Promise<void> {
  await deleteJson<void>(endpoints.api(`/sonic/runs/${encodeURIComponent(String(runId))}`), {
    errorMessage: "Playlist generation run delete request failed",
  });
}

export async function deleteSelectedPlaylistGenerationRuns(
  payload: DeletePlaylistGenerationRunsRequest,
): Promise<DeletePlaylistGenerationRunsResponse> {
  return postJson(endpoints.api("/sonic/runs/delete-selected"), {
    body: payload,
    errorMessage: "Playlist generation run bulk delete request failed",
    schema: deletePlaylistGenerationRunsResponseSchema,
  });
}

export async function fetchGeneratedPlaylists(): Promise<GeneratedPlaylistListResponse> {
  return fetchJson(endpoints.api("/sonic/generated-playlists"), generatedPlaylistsResponseSchema);
}

export async function fetchGeneratedPlaylistTracks(
  playlistId: number | string,
): Promise<GeneratedPlaylistTracksResponse> {
  return fetchJson(endpoints.api(`/sonic/generated-playlists/${playlistId}/tracks`), generatedPlaylistTracksResponseSchema);
}

export function useSonicFeatureSummaryQuery() {
  return useQuery({
    queryKey: sonicQueryKeys.featureSummary(),
    queryFn: fetchSonicFeatureSummary,
  });
}

export function useSonicGenerationPreviewQuery(
  payload: CreatePlaylistGenerationRunRequest,
  enabled: boolean,
) {
  return useQuery({
    enabled,
    queryKey: sonicQueryKeys.preview(payload),
    queryFn: () => fetchSonicGenerationPreview(payload),
    placeholderData: (previousData) => previousData,
  });
}

export function useSonicRunsQuery() {
  return useQuery({
    queryKey: sonicQueryKeys.runs(),
    queryFn: fetchSonicRuns,
    refetchInterval: (query) =>
      query.state.data?.runs.some((run) => isGenerationRunActive(run)) ? generationRunPollingIntervalMs : false,
  });
}

export function usePlaylistGenerationRecipesQuery() {
  return useQuery({
    queryKey: sonicQueryKeys.recipes(),
    queryFn: fetchPlaylistGenerationRecipes,
  });
}

export function useCreatePlaylistGenerationRecipeMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createPlaylistGenerationRecipe,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sonicQueryKeys.recipes() }),
  });
}

export function useUpdatePlaylistGenerationRecipeMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      payload,
      recipeId,
    }: {
      payload: SavePlaylistGenerationRecipeRequest;
      recipeId: number | string;
    }) => updatePlaylistGenerationRecipe(recipeId, payload),
    onSuccess: (recipe) => {
      queryClient.setQueryData(sonicQueryKeys.recipe(recipe.id), recipe);
      return queryClient.invalidateQueries({ queryKey: sonicQueryKeys.recipes() });
    },
  });
}

export function useDeletePlaylistGenerationRecipeMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deletePlaylistGenerationRecipe,
    onSuccess: async (_data, recipeId) => {
      queryClient.removeQueries({ queryKey: sonicQueryKeys.recipe(recipeId) });
      await queryClient.invalidateQueries({ queryKey: sonicQueryKeys.recipes() });
    },
  });
}

export function useRegeneratePlaylistGenerationRecipeMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: regeneratePlaylistGenerationRecipe,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: sonicQueryKeys.recipes() }),
        queryClient.invalidateQueries({ queryKey: sonicQueryKeys.runs() }),
        ...shellSummaryInvalidationKeys().map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      ]);
    },
  });
}

export function useSonicRunDetailQuery(runId: number | string | null) {
  return useQuery({
    queryKey: sonicQueryKeys.run(runId ?? "missing"),
    queryFn: () => fetchSonicRunDetail(runId ?? "missing"),
    enabled: runId !== null,
    refetchInterval: (query) =>
      isGenerationRunActive(query.state.data?.run) ? generationRunPollingIntervalMs : false,
  });
}

export function useDeletePlaylistGenerationRunMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deletePlaylistGenerationRun,
    onSuccess: async (_data, runId) => {
      queryClient.removeQueries({ queryKey: sonicQueryKeys.run(runId) });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: sonicQueryKeys.runs() }),
        queryClient.invalidateQueries({ queryKey: sonicQueryKeys.generatedPlaylists() }),
        ...shellSummaryInvalidationKeys().map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      ]);
    },
  });
}

export function useDeleteSelectedPlaylistGenerationRunsMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteSelectedPlaylistGenerationRuns,
    onSuccess: async (response) => {
      for (const runId of response.deleted_run_ids) {
        queryClient.removeQueries({ queryKey: sonicQueryKeys.run(runId) });
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: sonicQueryKeys.runs() }),
        queryClient.invalidateQueries({ queryKey: sonicQueryKeys.generatedPlaylists() }),
        ...shellSummaryInvalidationKeys().map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      ]);
    },
  });
}

export function useGeneratedPlaylistsQuery() {
  return useQuery({
    queryKey: sonicQueryKeys.generatedPlaylists(),
    queryFn: fetchGeneratedPlaylists,
  });
}

export function useGeneratedPlaylistTracksQuery(playlistId: number | string | null) {
  return useQuery({
    queryKey: sonicQueryKeys.playlistTracks(playlistId ?? "missing"),
    queryFn: () => fetchGeneratedPlaylistTracks(playlistId ?? "missing"),
    enabled: playlistId !== null,
  });
}
