import { useQuery } from "@tanstack/react-query";

import { endpoints, fetchJson } from "../../lib/api";

export type LibraryLinkStatus = "linked" | "pending" | "unlinked";
export type LibraryFileStatus = "available" | "missing" | "beets_failed";
export type LibraryMatchMethod = "isrc" | "tag" | "manual" | string;

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
  final_link_id: number | null;
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

export async function fetchLibraryTracks(): Promise<LibraryTracksResponse> {
  return fetchJson<LibraryTracksResponse>(endpoints.api("/library/tracks"));
}

export function useLibraryTracksQuery() {
  return useQuery({
    queryKey: libraryQueryKeys.tracks(),
    queryFn: fetchLibraryTracks,
  });
}
