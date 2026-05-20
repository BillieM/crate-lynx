import { type QueryClient, type QueryKey, useQuery } from "@tanstack/react-query";

import { endpoints, fetchJson } from "../../lib/api";
import { invalidateQueryKeys } from "../../lib/queryInvalidation";

export type MissingLocallyTrack = {
  album: string | null;
  artist: string;
  duration_ms: number | null;
  id: number;
  playlist_count: number;
  playlist_ids: number[];
  playlist_titles: string[];
  provider_track_id: string;
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

export type RescuedLocalTrack = {
  beets_id: number | null;
  file_path: string;
  id: number;
  library_root_rel_path: string | null;
};

export type RematchLocalTrackResponse = {
  job_id: string;
  local_track_id: number;
};

export class MaintenanceRequestError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(`${message} with status ${status}`);
    this.name = "MaintenanceRequestError";
    this.status = status;
  }
}

export function getMaintenanceRequestStatus(error: unknown): number | null {
  return error instanceof MaintenanceRequestError ? error.status : null;
}

async function postMaintenanceJson<T>(url: string, errorMessage: string): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
  });

  if (!response.ok) {
    throw new MaintenanceRequestError(errorMessage, response.status);
  }

  return (await response.json()) as T;
}

export const maintenanceQueryKeys = {
  all: ["maintenance"] as const,
  missingLocally: () => ["maintenance", "missing-locally"] as const,
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

export async function rescueLocalTrackMetadata(localTrackId: number | string): Promise<RescuedLocalTrack> {
  return postMaintenanceJson<RescuedLocalTrack>(
    `/api/local-tracks/${encodeURIComponent(String(localTrackId))}/rescue`,
    "Metadata rescue request failed",
  );
}

export async function rematchLocalTrack(localTrackId: number | string): Promise<RematchLocalTrackResponse> {
  return postMaintenanceJson<RematchLocalTrackResponse>(
    `/api/local-tracks/${encodeURIComponent(String(localTrackId))}/rematch`,
    "Re-match request failed",
  );
}

export async function retryUnidentifiedTrack(attemptId: number | string): Promise<UnidentifiedRetryResponse> {
  return postMaintenanceJson<UnidentifiedRetryResponse>(
    `/api/maintenance/unidentified/${encodeURIComponent(String(attemptId))}/retry`,
    "Unidentified retry request failed",
  );
}

export async function ignoreUnidentifiedTrack(attemptId: number | string): Promise<UnidentifiedIgnoreResponse> {
  return postMaintenanceJson<UnidentifiedIgnoreResponse>(
    `/api/maintenance/unidentified/${encodeURIComponent(String(attemptId))}/ignore`,
    "Unidentified ignore request failed",
  );
}

export async function restoreUnidentifiedTrack(attemptId: number | string): Promise<UnidentifiedRestoreResponse> {
  return postMaintenanceJson<UnidentifiedRestoreResponse>(
    `/api/maintenance/unidentified/${encodeURIComponent(String(attemptId))}/restore`,
    "Unidentified restore request failed",
  );
}

export function useMissingLocallyTracksQuery() {
  return useQuery({
    queryKey: maintenanceQueryKeys.missingLocally(),
    queryFn: fetchMissingLocallyTracks,
  });
}

export function useUnidentifiedTracksQuery({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    enabled,
    queryKey: maintenanceQueryKeys.unidentified(),
    queryFn: fetchUnidentifiedTracks,
  });
}
