import { useQuery } from "@tanstack/react-query";

export type MissingLocallyTrack = {
  album: string | null;
  artist: string;
  duration_ms: number | null;
  id: number;
  playlist_count: number;
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

async function fetchJson<T>(input: RequestInfo | URL): Promise<T> {
  const response = await fetch(input);

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}

export async function fetchMissingLocallyTracks(): Promise<MissingLocallyResponse> {
  return fetchJson<MissingLocallyResponse>("/api/maintenance/missing-locally");
}

export async function fetchUnidentifiedTracks(): Promise<UnidentifiedResponse> {
  return fetchJson<UnidentifiedResponse>("/api/maintenance/unidentified");
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
