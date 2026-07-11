import { keepPreviousData, type QueryClient, type QueryKey, useInfiniteQuery } from "@tanstack/react-query";

import { endpoints, fetchJson } from "../../lib/api";
import { invalidateQueryKeys } from "../../lib/queryInvalidation";
import { playlistLinkInvalidationKeys } from "../playlists/queries";
import { shellSummaryInvalidationKeys } from "../shell/queries";

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
  filtered_total: number;
  limit: number;
  next_cursor: string | null;
  returned_count: number;
  stats: LibraryStats;
  tracks: LibraryTrack[];
};

export type LibrarySortField = "album" | "artist" | "duration_ms" | "id" | "link_status" | "title";
export type LibrarySortDirection = "asc" | "desc";

export type LibraryQueryOptions = {
  direction?: LibrarySortDirection;
  linkStatus?: LibraryLinkStatus | null;
  limit?: number;
  query?: string;
  sort?: LibrarySortField;
};

export const libraryQueryKeys = {
  all: ["library"] as const,
  tracks: (options?: LibraryQueryOptions) =>
    options === undefined ? (["library", "tracks"] as const) : (["library", "tracks", options] as const),
};

export function libraryInvalidationKeys(): QueryKey[] {
  return [libraryQueryKeys.all, ["library", "tracks"], ...shellSummaryInvalidationKeys()];
}

export function libraryLinkMutationInvalidationKeys(): QueryKey[] {
  return [...libraryInvalidationKeys(), ...playlistLinkInvalidationKeys()];
}

export async function invalidateLibraryQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, libraryInvalidationKeys());
}

export async function invalidateLibraryLinkMutationQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, libraryLinkMutationInvalidationKeys());
}

type FetchLibraryTracksOptions = {
  cursor?: string | null;
  enabled?: boolean;
} & LibraryQueryOptions;

function libraryTracksUrl({ cursor, direction, linkStatus, limit, query: searchQuery, sort }: FetchLibraryTracksOptions = {}) {
  const params = new URLSearchParams();

  if (cursor !== null && cursor !== undefined) {
    params.set("cursor", String(cursor));
  }

  if (limit !== undefined) {
    params.set("limit", String(limit));
  }

  if (searchQuery?.trim()) {
    params.set("q", searchQuery.trim());
  }

  if (linkStatus) {
    params.set("link_status", linkStatus);
  }

  if (sort && sort !== "id") {
    params.set("sort", sort);
  }

  if (direction && direction !== "asc") {
    params.set("direction", direction);
  }

  const query = params.toString();

  return query ? `${endpoints.api("/library/tracks")}?${query}` : endpoints.api("/library/tracks");
}

export async function fetchLibraryTracks(options: FetchLibraryTracksOptions = {}): Promise<LibraryTracksResponse> {
  return fetchJson<LibraryTracksResponse>(libraryTracksUrl(options));
}

export function useLibraryTracksQuery({ enabled = true, ...options }: FetchLibraryTracksOptions = {}) {
  return useInfiniteQuery({
    queryKey: libraryQueryKeys.tracks(options),
    queryFn: ({ pageParam }) => fetchLibraryTracks({ ...options, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled,
    placeholderData: keepPreviousData,
  });
}
