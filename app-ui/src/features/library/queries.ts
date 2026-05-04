import { useQuery } from "@tanstack/react-query";

export type LibraryLinkStatus = "linked" | "pending" | "unlinked";
export type LibraryFileStatus = "available" | "missing" | "beets_failed";
export type LibraryMatchMethod = "isrc" | "tag" | "acoustic" | "manual" | string;

export type LibraryStats = {
  total: number;
  linked: number;
  pending: number;
  unlinked: number;
};

export type LibraryTrack = {
  album: string | null;
  artist: string | null;
  duration_ms: number | null;
  file_path: string;
  file_status: LibraryFileStatus;
  id: number;
  library_root_rel_path: string;
  link_status: LibraryLinkStatus;
  match_method: LibraryMatchMethod | null;
  title: string;
};

export type LibraryTracksResponse = {
  stats: LibraryStats;
  tracks: LibraryTrack[];
};

export const libraryQueryKeys = {
  all: ["library"] as const,
  tracks: () => ["library", "tracks"] as const,
};

async function fetchJson<T>(input: RequestInfo | URL): Promise<T> {
  const response = await fetch(input);

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}

export async function fetchLibraryTracks(): Promise<LibraryTracksResponse> {
  return fetchJson<LibraryTracksResponse>("/api/library/tracks");
}

export function useLibraryTracksQuery() {
  return useQuery({
    queryKey: libraryQueryKeys.tracks(),
    queryFn: fetchLibraryTracks,
  });
}
