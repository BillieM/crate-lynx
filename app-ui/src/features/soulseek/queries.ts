import { type QueryClient, type QueryKey, useQuery } from "@tanstack/react-query";

import { endpoints, fetchJson, postJson } from "../../lib/api";
import { invalidateQueryKeys } from "../../lib/queryInvalidation";
import { missingLocallyInvalidationKeys } from "../maintenance/queries";
import { playlistLinkInvalidationKeys } from "../playlists/queries";

export type SoulseekQueueFilter = "all" | "needs_search" | "review" | "active" | "failed" | "linked";

export type SoulseekAcquisitionSummary = {
  candidate_count: number;
  completed_source_path: string | null;
  enqueue_job_id: string | null;
  error_detail: string | null;
  final_link_id: number | null;
  id: string;
  job_id: string | null;
  link_error_detail: string | null;
  local_track_id: number | null;
  refresh_job_id: string | null;
  selected_candidate_id: string | null;
  slskd_batch_id: string | null;
  slskd_completed_event_id: string | null;
  slskd_transfer_id: string | null;
  status: string;
};

export type SoulseekAcquisitionDetail = SoulseekAcquisitionSummary & {
  completed_at: string | null;
  created_at: string;
  destination: string | null;
  failed_at: string | null;
  fallback_search_text: string | null;
  ingested_at: string | null;
  linked_at: string | null;
  proposal_available_at: string | null;
  queued_at: string | null;
  searched_at: string | null;
  search_text: string | null;
  slskd_fallback_search_id: string | null;
  slskd_search_id: string | null;
  streaming_track_id: number;
  updated_at: string;
};

export type SoulseekCandidate = {
  acquisition_id: string;
  bit_depth: number | null;
  bit_rate: number | null;
  created_at: string;
  duration_seconds: number | null;
  extension: string | null;
  filename: string;
  has_free_upload_slot: boolean;
  id: string;
  is_variable_bit_rate: boolean | null;
  queue_length: number | null;
  sample_rate: number | null;
  score: number;
  size: number;
  slskd_search_id: string;
  upload_speed: number | null;
  username: string;
};

export type SoulseekStreamingTrack = {
  album: string | null;
  artist: string;
  duration_ms: number | null;
  id: number;
  title: string;
};

export type SoulseekQueueItem = {
  acquisition: SoulseekAcquisitionDetail | null;
  candidates: SoulseekCandidate[];
  playlist_count: number;
  playlist_ids: number[];
  playlist_titles: string[];
  selected_candidate: SoulseekCandidate | null;
  streaming_track: SoulseekStreamingTrack;
};

export type SoulseekQueueResponse = {
  filter: SoulseekQueueFilter;
  items: SoulseekQueueItem[];
  total_count: number;
};

export type SoulseekSearchResponse = {
  acquisition: SoulseekAcquisitionSummary;
  job_id: string;
};

export type SoulseekEnqueueResponse = {
  acquisition: SoulseekAcquisitionSummary;
  job_id: string | null;
};

export type SoulseekRefreshResponse = {
  acquisition: SoulseekAcquisitionSummary;
  job_id: string;
};

export const soulseekQueryKeys = {
  all: ["soulseek"] as const,
  acquisition: (acquisitionId: number | string | null) => ["soulseek", "acquisition", acquisitionId] as const,
  queue: () => ["soulseek", "queue"] as const,
};

export function soulseekInvalidationKeys(): QueryKey[] {
  return [soulseekQueryKeys.all, ...missingLocallyInvalidationKeys(), ...playlistLinkInvalidationKeys()];
}

export async function invalidateSoulseekJourneyQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, soulseekInvalidationKeys());
}

export async function fetchSoulseekQueue(): Promise<SoulseekQueueResponse> {
  return fetchJson<SoulseekQueueResponse>(endpoints.api("/soulseek/queue"));
}

export async function fetchSoulseekAcquisition(acquisitionId: number | string): Promise<SoulseekQueueItem> {
  return fetchJson<SoulseekQueueItem>(endpoints.api(`/soulseek/acquisitions/${encodeURIComponent(String(acquisitionId))}`));
}

export async function searchSoulseekTrack(streamingTrackId: number | string): Promise<SoulseekSearchResponse> {
  return postJson<SoulseekSearchResponse>(
    endpoints.api(`/soulseek/missing-tracks/${encodeURIComponent(String(streamingTrackId))}/search`),
    { errorMessage: "Soulseek search request failed" },
  );
}

export async function approveSoulseekCandidateDownload(candidateId: number | string): Promise<SoulseekEnqueueResponse> {
  return postJson<SoulseekEnqueueResponse>(
    endpoints.api(`/soulseek/candidates/${encodeURIComponent(String(candidateId))}/approve-download`),
    { errorMessage: "Soulseek download approval failed" },
  );
}

export async function refreshSoulseekAcquisition(acquisitionId: number | string): Promise<SoulseekRefreshResponse> {
  return postJson<SoulseekRefreshResponse>(
    endpoints.api(`/soulseek/acquisitions/${encodeURIComponent(String(acquisitionId))}/refresh`),
    { errorMessage: "Soulseek refresh request failed" },
  );
}

export function useSoulseekQueueQuery() {
  return useQuery({
    queryKey: soulseekQueryKeys.queue(),
    queryFn: fetchSoulseekQueue,
    refetchInterval: 8000,
  });
}

export function useSoulseekAcquisitionQuery(acquisitionId: string | null, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    enabled: enabled && acquisitionId !== null,
    queryKey: soulseekQueryKeys.acquisition(acquisitionId),
    queryFn: () => fetchSoulseekAcquisition(acquisitionId ?? ""),
  });
}
