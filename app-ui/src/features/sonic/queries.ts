import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { deleteJson, endpoints, fetchJson, postJson } from "../../lib/api";
import type { components } from "../../lib/api-types";

type ApiSchemas = components["schemas"];

export type SonicFeatureSummary = ApiSchemas["SonicFeatureSummaryResponse"];
export type SonicBackfillRequest = ApiSchemas["SonicBackfillRequest"];
export type SonicBackfillResponse = ApiSchemas["SonicBackfillResponse"];
export type SonicTagFilter = ApiSchemas["SonicTagFilterRequest"];
export type SonicSourceFilter = ApiSchemas["SonicSourceFilterRequest"];
export type PlaylistGenerationConfig = ApiSchemas["PlaylistGenerationConfigRequest"];
export type CreatePlaylistGenerationRunRequest = ApiSchemas["CreatePlaylistGenerationRunRequest"];
export type CreatePlaylistGenerationRunResponse = ApiSchemas["CreatePlaylistGenerationRunResponse"];
export type SonicGenerationPreview = ApiSchemas["SonicGenerationPreviewResponse"];
export type PlaylistGenerationRun = ApiSchemas["PlaylistGenerationRunResponse"];
export type PlaylistGenerationRunListResponse = ApiSchemas["PlaylistGenerationRunListResponse"];
export type DeletePlaylistGenerationRunsRequest = ApiSchemas["DeletePlaylistGenerationRunsRequest"];
export type DeletePlaylistGenerationRunsResponse = ApiSchemas["DeletePlaylistGenerationRunsResponse"];
export type GeneratedPlaylist = ApiSchemas["GeneratedPlaylistResponse"];
export type GeneratedPlaylistListResponse = ApiSchemas["GeneratedPlaylistListResponse"];
export type PlaylistGenerationRunDetailResponse = ApiSchemas["PlaylistGenerationRunDetailResponse"];
export type GeneratedPlaylistTrack = ApiSchemas["GeneratedPlaylistTrackResponse"];
export type GeneratedPlaylistTracksResponse = ApiSchemas["GeneratedPlaylistTracksResponse"];

const nullableStringSchema = z.string().nullable();
const dateStringSchema = z.string();
const runStatusSchema = z.enum(["pending", "running", "completed", "failed"]);
const generationRunPollingIntervalMs = 2_000;

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

const sonicGenerationPreviewSchema: z.ZodType<SonicGenerationPreview> = z.object({
  analyzer_key: z.string(),
  analyzer_version: z.string(),
  can_generate: z.boolean(),
  failed_feature_count: z.number(),
  feature_profile: z.string(),
  missing_feature_count: z.number(),
  pending_feature_count: z.number(),
  ready_track_count: z.number(),
  skipped_track_count: z.number(),
  source_track_count: z.number(),
});

const playlistGenerationRunSchema: z.ZodType<PlaylistGenerationRun> = z.object({
  completed_at: nullableStringSchema,
  created_at: dateStringSchema,
  error_detail: nullableStringSchema,
  generation_config: z.record(z.string(), z.unknown()),
  generation_number: z.number(),
  id: z.number(),
  playlist_count: z.number(),
  source_filter: z.record(z.string(), z.unknown()),
  status: runStatusSchema,
  track_count: z.number(),
  updated_at: dateStringSchema,
});

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
