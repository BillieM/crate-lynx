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
  failed_at: string;
  failure_reason: string;
  filename: string;
  id: number;
  local_track_id: number | null;
  source_path: string;
};

export type UnidentifiedResponse = {
  tracks: UnidentifiedTrack[];
};

export type RescuedLocalTrack = {
  beets_id: number | null;
  file_path: string;
  id: number;
  library_root_rel_path: string | null;
};

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
  const response = await fetch(`/api/local-tracks/${encodeURIComponent(String(localTrackId))}/rescue`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Metadata rescue request failed with status ${response.status}`);
  }

  return (await response.json()) as RescuedLocalTrack;
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
