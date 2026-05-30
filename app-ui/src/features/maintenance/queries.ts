import { type QueryClient, type QueryKey, useQuery } from "@tanstack/react-query";

import { ApiRequestError, endpoints, fetchJson, postJson } from "../../lib/api";
import { invalidateQueryKeys } from "../../lib/queryInvalidation";
import {
  rematchLocalTrack,
  rescueLocalTrackMetadata,
  type RematchLocalTrackResponse,
  type RescuedLocalTrack,
} from "../localTracks/queries";

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

export { rematchLocalTrack, rescueLocalTrackMetadata };
export type { RematchLocalTrackResponse, RescuedLocalTrack };

export function getMaintenanceRequestStatus(error: unknown): number | null {
  return error instanceof ApiRequestError ? error.status : null;
}

export const maintenanceQueryKeys = {
  all: ["maintenance"] as const,
  unidentified: () => ["maintenance", "unidentified"] as const,
};

export function unidentifiedInvalidationKeys(): QueryKey[] {
  return [maintenanceQueryKeys.unidentified()];
}

export async function invalidateUnidentifiedQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, unidentifiedInvalidationKeys());
}

export async function fetchUnidentifiedTracks(): Promise<UnidentifiedResponse> {
  return fetchJson<UnidentifiedResponse>(endpoints.api("/maintenance/unidentified"));
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

export function useUnidentifiedTracksQuery({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    enabled,
    queryKey: maintenanceQueryKeys.unidentified(),
    queryFn: fetchUnidentifiedTracks,
  });
}
