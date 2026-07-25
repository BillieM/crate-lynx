import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { endpoints, fetchJson, patchJson, postJson } from "../../lib/api";
import type { components } from "../../lib/api-types";

type ApiSchemas = components["schemas"];

export type AutopilotSettings = ApiSchemas["AutopilotSettingsResponse"];
export type UpdateAutopilotSettingsRequest = ApiSchemas["UpdateAutopilotSettingsRequest"];

export type AutopilotRunItem = {
  detail: string | null;
  id: string | null;
  playlist_id: number | null;
  reason: string | null;
  stage: string | null;
  status: string;
  streaming_track_id: number | null;
};

export type AutopilotRun = {
  completed_at: string | null;
  counts: Record<string, number>;
  created_at: string;
  dry_run: boolean;
  id: string;
  items: AutopilotRunItem[];
  started_at: string | null;
  status: string;
  trigger: string;
};

export type AutopilotRunListResponse = {
  runs: AutopilotRun[];
};

const nullableStringSchema = z.string().nullable();

const autopilotSettingsSchema: z.ZodType<AutopilotSettings> = z.object({
  created_at: z.string(),
  id: z.number(),
  max_concurrent_downloads: z.number().int().min(1),
  max_downloads_per_run: z.number().int().min(0),
  max_searches_per_run: z.number().int().min(0),
  max_storage_bytes_per_run: z.number().int().min(0),
  paused: z.boolean(),
  quiet_period_seconds: z.number().int().min(0),
  retry_base_seconds: z.number().int().min(1),
  retry_max_attempts: z.number().int().min(1),
  retry_max_seconds: z.number().int().min(1),
  schedule_minutes: z.number().int().min(1),
  updated_at: z.string(),
});

const autopilotRunItemSchema: z.ZodType<AutopilotRunItem> = z
  .object({
    detail: nullableStringSchema.default(null),
    id: z.union([z.string(), z.number()]).nullable().default(null),
    playlist_id: z.number().nullable().default(null),
    reason: nullableStringSchema.optional(),
    reason_code: nullableStringSchema.optional(),
    stage: nullableStringSchema.default(null),
    status: z.string(),
    streaming_track_id: z.number().nullable().default(null),
  })
  .transform((item) => ({
    detail: item.detail,
    id: item.id === null ? null : String(item.id),
    playlist_id: item.playlist_id,
    reason: item.reason_code ?? item.reason ?? null,
    stage: item.stage,
    status: item.status,
    streaming_track_id: item.streaming_track_id,
  }));

const autopilotRunSchema: z.ZodType<AutopilotRun> = z
  .object({
    analyzed_tracks: z.number().default(0),
    completed_at: nullableStringSchema.optional(),
    counts: z.record(z.string(), z.number()).optional(),
    created_at: z.string(),
    downloaded_tracks: z.number().default(0),
    dry_run: z.boolean(),
    failed_items: z.number().default(0),
    finished_at: nullableStringSchema.optional(),
    id: z.union([z.string(), z.number()]),
    ingested_tracks: z.number().default(0),
    items: z.array(autopilotRunItemSchema).default([]),
    queued_downloads: z.number().default(0),
    refreshed_exports: z.number().default(0),
    refreshed_playlists: z.number().default(0),
    regenerated_recipes: z.number().default(0),
    review_items: z.number().default(0),
    searched_tracks: z.number().default(0),
    started_at: nullableStringSchema.default(null),
    status: z.string(),
    trigger: z.string(),
  })
  .transform((run) => ({
    completed_at: run.finished_at ?? run.completed_at ?? null,
    counts: {
      analyzed_tracks: run.analyzed_tracks,
      downloaded_tracks: run.downloaded_tracks,
      failed_items: run.failed_items,
      ingested_tracks: run.ingested_tracks,
      queued_downloads: run.queued_downloads,
      refreshed_exports: run.refreshed_exports,
      refreshed_playlists: run.refreshed_playlists,
      regenerated_recipes: run.regenerated_recipes,
      review_items: run.review_items,
      searched_tracks: run.searched_tracks,
      ...run.counts,
    },
    created_at: run.created_at,
    dry_run: run.dry_run,
    id: String(run.id),
    items: run.items,
    started_at: run.started_at,
    status: run.status,
    trigger: run.trigger,
  }));

const autopilotRunListSchema: z.ZodType<AutopilotRunListResponse> = z.object({
  runs: z.array(autopilotRunSchema),
});

const autopilotRunMutationSchema: z.ZodType<AutopilotRun> = z
  .union([autopilotRunSchema, z.object({ run: autopilotRunSchema })])
  .transform((response) => ("run" in response ? response.run : response));

export const autopilotQueryKeys = {
  all: ["autopilot"] as const,
  run: (runId: string) => ["autopilot", "runs", runId] as const,
  runs: () => ["autopilot", "runs"] as const,
  settings: () => ["autopilot", "settings"] as const,
};

export async function fetchAutopilotSettings(): Promise<AutopilotSettings> {
  return fetchJson(endpoints.api("/autopilot/settings"), autopilotSettingsSchema);
}

export async function updateAutopilotSettings(
  payload: UpdateAutopilotSettingsRequest,
): Promise<AutopilotSettings> {
  return patchJson(endpoints.api("/autopilot/settings"), {
    body: payload,
    errorMessage: "Autopilot settings update request failed",
    schema: autopilotSettingsSchema,
  });
}

export async function fetchAutopilotRuns(): Promise<AutopilotRunListResponse> {
  return fetchJson(endpoints.api("/autopilot/runs"), autopilotRunListSchema);
}

export async function fetchAutopilotRun(runId: string): Promise<AutopilotRun> {
  return fetchJson(
    endpoints.api(`/autopilot/runs/${encodeURIComponent(String(runId))}`),
    autopilotRunSchema,
  );
}

export async function runAutopilotDryRun(): Promise<AutopilotRun> {
  return postJson(endpoints.api("/autopilot/runs"), {
    body: { dry_run: true },
    errorMessage: "Autopilot dry-run request failed",
    schema: autopilotRunMutationSchema,
  });
}

export function useAutopilotSettingsQuery() {
  return useQuery({
    queryKey: autopilotQueryKeys.settings(),
    queryFn: fetchAutopilotSettings,
  });
}

export function useAutopilotRunsQuery() {
  return useQuery({
    queryKey: autopilotQueryKeys.runs(),
    queryFn: fetchAutopilotRuns,
    refetchInterval: (query) =>
      query.state.data?.runs.some((run) => ["pending", "planning", "running"].includes(run.status))
        ? 2_000
        : false,
  });
}

export function useAutopilotRunQuery(runId: string | null) {
  return useQuery({
    enabled: runId !== null,
    queryKey: autopilotQueryKeys.run(runId ?? "latest"),
    queryFn: () => fetchAutopilotRun(runId ?? "latest"),
    refetchInterval: (query) =>
      query.state.data && ["pending", "planning", "running"].includes(query.state.data.status) ? 2_000 : false,
  });
}

export function useUpdateAutopilotSettingsMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: updateAutopilotSettings,
    onSuccess: (settings) => {
      queryClient.setQueryData(autopilotQueryKeys.settings(), settings);
    },
  });
}

export function useRunAutopilotDryRunMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: runAutopilotDryRun,
    onSuccess: async (run) => {
      queryClient.setQueryData(autopilotQueryKeys.run(run.id), run);
      await queryClient.invalidateQueries({ queryKey: autopilotQueryKeys.runs() });
    },
  });
}
