import { type QueryClient, type QueryKey, useQuery } from "@tanstack/react-query";

import { ApiRequestError, endpoints, fetchJson, postJson } from "../../lib/api";
import { invalidateQueryKeys } from "../../lib/queryInvalidation";
import {
  rematchLocalTrack,
  rescueLocalTrackMetadata,
  type RematchLocalTrackResponse,
  type RescuedLocalTrack,
} from "../localTracks/queries";

export type MissingLocallyTrack = {
  album: string | null;
  artist: string;
  duration_ms: number | null;
  id: number;
  playlist_count: number;
  playlist_ids: number[];
  playlist_titles: string[];
  provider_track_id: string;
  soulseek_acquisition?: SoulseekAcquisitionSummary | null;
  title: string;
};

export type MissingLocallyResponse = {
  tracks: MissingLocallyTrack[];
};

export type UnidentifiedTrack = {
  attempt_count: number;
  can_rematch_local_track: boolean;
  can_rescue_metadata: boolean;
  failed_at: string;
  failure_reason: string;
  filename: string;
  first_failed_at: string;
  id: number;
  ignored_at: string | null;
  local_track_id: number | null;
  source_mtime_ns: number | null;
  source_path: string;
  source_size: number | null;
};

export type UnidentifiedResponse = {
  tracks: UnidentifiedTrack[];
};

export type UnidentifiedRetryResponse = {
  id: number;
  job_id: string | null;
  source_path: string;
};

export type UnidentifiedIgnoreResponse = {
  id: number;
  ignored_at: string;
  source_path: string;
};

export type UnidentifiedRestoreResponse = {
  id: number;
  ignored_at: null;
  source_path: string;
};

export type SoulseekAcquisitionSummary = {
  candidate_count: number;
  completed_source_path?: string | null;
  enqueue_job_id: string | null;
  error_detail: string | null;
  final_link_id?: number | null;
  id: string;
  job_id: string | null;
  link_error_detail?: string | null;
  local_track_id?: number | null;
  refresh_job_id: string | null;
  selected_candidate_id: string | null;
  slskd_batch_id: string | null;
  slskd_completed_event_id?: string | null;
  slskd_transfer_id?: string | null;
  status: string;
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

export type SoulseekCandidatesResponse = {
  acquisition: SoulseekAcquisitionSummary;
  candidates: SoulseekCandidate[];
};

export type SoulseekSearchResponse = {
  acquisition: SoulseekAcquisitionSummary;
  job_id: string;
};

export type SoulseekBulkSearchResponse = {
  jobs: Array<{
    acquisition: SoulseekAcquisitionSummary;
    job_id: string;
    streaming_track_id: number;
  }>;
};

export type SoulseekEnqueueResponse = {
  acquisition: SoulseekAcquisitionSummary;
  job_id: string | null;
};

export type SoulseekRefreshResponse = {
  acquisition: SoulseekAcquisitionSummary;
  job_id: string;
};

export { rematchLocalTrack, rescueLocalTrackMetadata };
export type { RematchLocalTrackResponse, RescuedLocalTrack };

export function getMaintenanceRequestStatus(error: unknown): number | null {
  return error instanceof ApiRequestError ? error.status : null;
}

export const maintenanceQueryKeys = {
  all: ["maintenance"] as const,
  missingLocally: () => ["maintenance", "missing-locally"] as const,
  soulseekCandidates: (acquisitionId: number | string | null) =>
    ["maintenance", "missing-locally", "soulseek", acquisitionId] as const,
  unidentified: () => ["maintenance", "unidentified"] as const,
};

export function missingLocallyInvalidationKeys(): QueryKey[] {
  return [maintenanceQueryKeys.missingLocally()];
}

export function unidentifiedInvalidationKeys(): QueryKey[] {
  return [maintenanceQueryKeys.unidentified()];
}

export async function invalidateMissingLocallyQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, missingLocallyInvalidationKeys());
}

export async function invalidateUnidentifiedQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, unidentifiedInvalidationKeys());
}

export async function fetchMissingLocallyTracks(): Promise<MissingLocallyResponse> {
  return fetchJson<MissingLocallyResponse>(endpoints.api("/maintenance/missing-locally"));
}

export async function fetchUnidentifiedTracks(): Promise<UnidentifiedResponse> {
  return fetchJson<UnidentifiedResponse>(endpoints.api("/maintenance/unidentified"));
}

export async function searchMissingTrack(streamingTrackId: number | string): Promise<SoulseekSearchResponse> {
  return postJson<SoulseekSearchResponse>(
    endpoints.api(`/soulseek/missing-tracks/${encodeURIComponent(String(streamingTrackId))}/search`),
    { errorMessage: "Soulseek search request failed" },
  );
}

export async function searchSelectedMissingTracks(streamingTrackIds: number[]): Promise<SoulseekBulkSearchResponse> {
  return postJson<SoulseekBulkSearchResponse>(endpoints.api("/soulseek/missing-tracks/search-selected"), {
    body: { streaming_track_ids: streamingTrackIds },
    errorMessage: "Soulseek bulk search request failed",
  });
}

export async function fetchSoulseekCandidates(acquisitionId: number | string): Promise<SoulseekCandidatesResponse> {
  return fetchJson<SoulseekCandidatesResponse>(
    endpoints.api(`/soulseek/acquisitions/${encodeURIComponent(String(acquisitionId))}/candidates`),
  );
}

export async function enqueueSoulseekCandidate(candidateId: number | string): Promise<SoulseekEnqueueResponse> {
  return postJson<SoulseekEnqueueResponse>(
    endpoints.api(`/soulseek/candidates/${encodeURIComponent(String(candidateId))}/enqueue`),
    { errorMessage: "Soulseek download request failed" },
  );
}

export async function refreshSoulseekAcquisition(acquisitionId: number | string): Promise<SoulseekRefreshResponse> {
  return postJson<SoulseekRefreshResponse>(
    endpoints.api(`/soulseek/acquisitions/${encodeURIComponent(String(acquisitionId))}/refresh`),
    { errorMessage: "Soulseek refresh request failed" },
  );
}

export async function retryUnidentifiedTrack(attemptId: number | string): Promise<UnidentifiedRetryResponse> {
  return postJson<UnidentifiedRetryResponse>(
    endpoints.api(`/maintenance/unidentified/${encodeURIComponent(String(attemptId))}/retry`),
    { errorMessage: "Unidentified retry request failed" },
  );
}

export async function ignoreUnidentifiedTrack(attemptId: number | string): Promise<UnidentifiedIgnoreResponse> {
  return postJson<UnidentifiedIgnoreResponse>(
    endpoints.api(`/maintenance/unidentified/${encodeURIComponent(String(attemptId))}/ignore`),
    { errorMessage: "Unidentified ignore request failed" },
  );
}

export async function restoreUnidentifiedTrack(attemptId: number | string): Promise<UnidentifiedRestoreResponse> {
  return postJson<UnidentifiedRestoreResponse>(
    endpoints.api(`/maintenance/unidentified/${encodeURIComponent(String(attemptId))}/restore`),
    { errorMessage: "Unidentified restore request failed" },
  );
}

export function useMissingLocallyTracksQuery() {
  return useQuery({
    queryKey: maintenanceQueryKeys.missingLocally(),
    queryFn: fetchMissingLocallyTracks,
  });
}

export function useSoulseekCandidatesQuery(acquisitionId: string | null, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    enabled: enabled && acquisitionId !== null,
    queryKey: maintenanceQueryKeys.soulseekCandidates(acquisitionId),
    queryFn: () => fetchSoulseekCandidates(acquisitionId ?? ""),
  });
}

export function useUnidentifiedTracksQuery({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    enabled,
    queryKey: maintenanceQueryKeys.unidentified(),
    queryFn: fetchUnidentifiedTracks,
  });
}
