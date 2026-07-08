import { type QueryKey, useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { endpoints, fetchJson } from "../../lib/api";
import type { StreamingPlaylist } from "../playlists/queries";
import type { PlaylistGenerationRun } from "../sonic/queries";

export type ShellCounts = {
  library_track_total: number;
  link_proposal_count: number;
  relationship_suggestion_count: number;
  soulseek_unlinked_count: number;
  unidentified_active_count: number;
};

export type ShellSummaryResponse = {
  counts: ShellCounts;
  generated_runs: PlaylistGenerationRun[];
  playlists: StreamingPlaylist[];
};

const nullableStringSchema = z.string().nullable();
const nullableNumberSchema = z.number().nullable();

const playlistSyncModeSchema = z.enum(["off", "match_only", "full"]);
const runStatusSchema = z.enum(["pending", "running", "completed", "failed"]);

const shellPlaylistSchema: z.ZodType<StreamingPlaylist> = z.object({
  account_id: z.number(),
  id: z.number(),
  imported_track_count: z.number(),
  last_sync_error: nullableStringSchema,
  last_sync_error_at: nullableStringSchema,
  metadata_synced_at: nullableStringSchema,
  provider_playlist_id: z.string(),
  provider_track_count: nullableNumberSchema,
  sync_mode: playlistSyncModeSchema,
  title: z.string(),
  tracks_synced_at: nullableStringSchema,
});

const shellGeneratedRunSchema: z.ZodType<PlaylistGenerationRun> = z.object({
  completed_at: nullableStringSchema,
  created_at: z.string(),
  error_detail: nullableStringSchema,
  generation_config: z.record(z.string(), z.unknown()),
  generation_number: z.number(),
  id: z.number(),
  playlist_count: z.number(),
  source_filter: z.record(z.string(), z.unknown()),
  status: runStatusSchema,
  track_count: z.number(),
  updated_at: z.string(),
});

const shellSummaryResponseSchema: z.ZodType<ShellSummaryResponse> = z.object({
  counts: z.object({
    library_track_total: z.number(),
    link_proposal_count: z.number(),
    relationship_suggestion_count: z.number(),
    soulseek_unlinked_count: z.number(),
    unidentified_active_count: z.number(),
  }),
  generated_runs: z.array(shellGeneratedRunSchema),
  playlists: z.array(shellPlaylistSchema),
});

export const shellQueryKeys = {
  summary: () => ["shell", "summary"] as const,
};

export function shellSummaryInvalidationKeys(): QueryKey[] {
  return [shellQueryKeys.summary()];
}

function isGenerationRunActive(run: PlaylistGenerationRun | undefined) {
  return run?.status === "pending" || run?.status === "running";
}

export async function fetchShellSummary(): Promise<ShellSummaryResponse> {
  return fetchJson(endpoints.api("/shell/summary"), shellSummaryResponseSchema);
}

export function useShellSummaryQuery() {
  return useQuery({
    queryKey: shellQueryKeys.summary(),
    queryFn: fetchShellSummary,
    refetchInterval: (query) =>
      query.state.data?.generated_runs.some((run) => isGenerationRunActive(run)) ? 2_000 : false,
  });
}
