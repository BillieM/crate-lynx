import { type QueryClient, type QueryKey, useInfiniteQuery } from "@tanstack/react-query";

import { endpoints, fetchJson } from "../../lib/api";
import { invalidateQueryKeys } from "../../lib/queryInvalidation";

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
  next_cursor: number | null;
  stats: LibraryStats;
  tracks: LibraryTrack[];
};

export const libraryQueryKeys = {
  all: ["library"] as const,
  tracks: () => ["library", "tracks"] as const,
};

export function libraryInvalidationKeys(): QueryKey[] {
  return [libraryQueryKeys.all, libraryQueryKeys.tracks()];
}

export async function invalidateLibraryQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, libraryInvalidationKeys());
}

type FetchLibraryTracksOptions = {
  cursor?: number | null;
  limit?: number;
};

type UseLibraryTracksQueryOptions = {
  enabled?: boolean;
};

function libraryTracksUrl({ cursor, limit }: FetchLibraryTracksOptions = {}) {
  const params = new URLSearchParams();

  if (cursor !== null && cursor !== undefined) {
    params.set("cursor", String(cursor));
  }

  if (limit !== undefined) {
    params.set("limit", String(limit));
  }

  const query = params.toString();

  return query ? `${endpoints.api("/library/tracks")}?${query}` : endpoints.api("/library/tracks");
}

export async function fetchLibraryTracks(options: FetchLibraryTracksOptions = {}): Promise<LibraryTracksResponse> {
  return fetchJson<LibraryTracksResponse>(libraryTracksUrl(options));
}

export function useLibraryTracksQuery({ enabled = true }: UseLibraryTracksQueryOptions = {}) {
  return useInfiniteQuery({
    queryKey: libraryQueryKeys.tracks(),
    queryFn: ({ pageParam }) => fetchLibraryTracks({ cursor: pageParam }),
    initialPageParam: null as number | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled,
  });
}
