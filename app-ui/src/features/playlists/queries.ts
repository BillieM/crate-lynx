import { type QueryClient, type QueryKey, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { deleteJson, endpoints, fetchBlob, fetchJson, patchJson, postJson } from "../../lib/api";
import type { components } from "../../lib/api-types";
import { invalidateQueryKeys } from "../../lib/queryInvalidation";
import { missingLocallyInvalidationKeys } from "../maintenance/queries";

type ApiSchemas = components["schemas"];

export type PlaylistTrackStatus = "linked" | "pending" | "unlinked";
export type LinkProposalConfidenceBand = ApiSchemas["ConfidenceBand"];

export type PlaylistDetail = ApiSchemas["PlaylistDetail"];
export type StreamingPlaylist = ApiSchemas["StreamingPlaylistResponse"];
export type StreamingPlaylistConfig = ApiSchemas["StreamingPlaylistConfigResponse"];
export type PlaylistSyncMode = StreamingPlaylistConfig["sync_mode"];
export type PlaylistTrack = Omit<ApiSchemas["PlaylistTrackResponse"], "status"> & {
  status: PlaylistTrackStatus;
};

export type PlaylistDetailResponse = ApiSchemas["PlaylistDetailResponse"];
export type StreamingPlaylistsResponse = ApiSchemas["StreamingPlaylistsResponse"];
export type StreamingPlaylistConfigResponse = ApiSchemas["StreamingPlaylistConfigListResponse"];
export type UpdateStreamingPlaylistConfigInput = ApiSchemas["UpdateStreamingPlaylistRequest"] & {
  playlistId: number | string;
};
export type PlaylistTracksResponse = {
  tracks: PlaylistTrack[];
};
export type PlaylistM3uExport = {
  blob: Blob;
  filename: string;
};
export type LinkProposal = ApiSchemas["ProposalResponse"];
export type LinkProposalsResponse = ApiSchemas["ProposalListResponse"];

export type ApproveLinkProposalResponse = {
  final_link_id: number;
  proposal_id: number;
  status: "approved";
};

export type RejectLinkProposalResponse = {
  proposal_id: number;
  rejected_at: string;
  status: "rejected";
};

export type LinkProposalListFilters = {
  confidenceBand?: LinkProposalConfidenceBand | null;
};

export type LinkProposalListQuery = LinkProposalListFilters & {
  cursor?: string | null;
  limit?: number;
};

export type StreamingSyncResponse = ApiSchemas["StreamingSyncResponse"];
export type PlaylistSyncResponse = ApiSchemas["PlaylistSyncResponse"];

export type DeleteFinalLinkResponse = {
  final_link_id: number;
  rejected_at: string;
  rejected_suggestion_id: number;
  status: "rejected";
};

export const DEFAULT_LINK_PROPOSAL_LIMIT = 50;

const nullableStringSchema = z.string().nullable();
const playlistSyncModeSchema = z.enum(["off", "match_only", "full"]);

const playlistDetailSchema: z.ZodType<PlaylistDetail> = z.object({
  account_id: z.number(),
  cover_art_url: nullableStringSchema,
  id: z.number(),
  last_sync_error: nullableStringSchema,
  last_sync_error_at: nullableStringSchema,
  imported_track_count: z.number(),
  linked_count: z.number(),
  metadata_synced_at: nullableStringSchema,
  name: z.string(),
  pending_count: z.number(),
  provider_track_count: z.number().nullable(),
  provider_playlist_id: z.string(),
  sync_mode: playlistSyncModeSchema,
  tracks_synced_at: nullableStringSchema,
  unlinked_count: z.number(),
});

const playlistDetailResponseSchema: z.ZodType<PlaylistDetailResponse> = z.object({
  playlist: playlistDetailSchema,
});

const streamingPlaylistSchema: z.ZodType<StreamingPlaylist> = z.object({
  account_id: z.number(),
  id: z.number(),
  last_sync_error: nullableStringSchema,
  last_sync_error_at: nullableStringSchema,
  imported_track_count: z.number(),
  metadata_synced_at: nullableStringSchema,
  provider_track_count: z.number().nullable(),
  provider_playlist_id: z.string(),
  sync_mode: playlistSyncModeSchema,
  title: z.string(),
  tracks_synced_at: nullableStringSchema,
});

const streamingPlaylistConfigSchema: z.ZodType<StreamingPlaylistConfig> = z.object({
  account_id: z.number(),
  id: z.number(),
  last_sync_error: nullableStringSchema,
  last_sync_error_at: nullableStringSchema,
  imported_track_count: z.number(),
  metadata_synced_at: nullableStringSchema,
  provider_track_count: z.number().nullable(),
  provider_playlist_id: z.string(),
  sync_mode: playlistSyncModeSchema,
  title: z.string(),
  tracks_synced_at: nullableStringSchema,
});

const streamingPlaylistsResponseSchema: z.ZodType<StreamingPlaylistsResponse> = z.object({
  playlists: z.array(streamingPlaylistSchema),
});

const streamingPlaylistConfigResponseSchema: z.ZodType<StreamingPlaylistConfigResponse> = z.object({
  playlists: z.array(streamingPlaylistConfigSchema),
});

const playlistTrackStatusSchema = z.enum(["linked", "pending", "unlinked"]);

const playlistTrackSchema: z.ZodType<PlaylistTrack> = z.object({
  album: nullableStringSchema,
  artist: z.string(),
  duration_ms: z.number().nullable(),
  final_link_id: z.number().nullable(),
  id: z.number(),
  local_track_id: z.number().nullable(),
  position: z.number(),
  proposal_id: z.number().nullable(),
  provider_track_id: z.string(),
  status: playlistTrackStatusSchema,
  title: z.string(),
});

const playlistTracksResponseSchema: z.ZodType<PlaylistTracksResponse> = z.object({
  tracks: z.array(playlistTrackSchema),
});

const linkProposalConfidenceBandSchema = z.enum(["high", "medium", "low"]);

const linkProposalSchema: z.ZodType<LinkProposal> = z.object({
  confidence_band: linkProposalConfidenceBandSchema,
  id: z.number(),
  local_album: nullableStringSchema,
  local_artist: nullableStringSchema,
  local_file_path: z.string(),
  local_title: nullableStringSchema,
  local_track_id: z.number(),
  match_method: z.string(),
  rejected_at: nullableStringSchema,
  score: z.number(),
  status: z.string(),
  streaming_album: nullableStringSchema,
  streaming_artist: z.string(),
  streaming_provider_track_id: z.string(),
  streaming_title: z.string(),
  streaming_track_id: z.number(),
});

const linkProposalsResponseSchema: z.ZodType<LinkProposalsResponse> = z.object({
  limit: z.number(),
  next_cursor: z.string().nullable(),
  proposals: z.array(linkProposalSchema),
  returned_count: z.number(),
  total_count: z.number(),
});

const streamingSyncResponseSchema: z.ZodType<StreamingSyncResponse> = z.object({
  account_id: z.number(),
  job_id: z.string(),
});

const playlistSyncResponseSchema: z.ZodType<PlaylistSyncResponse> = z.object({
  job_id: z.string(),
  playlist_id: z.number(),
});

const deleteFinalLinkResponseSchema: z.ZodType<DeleteFinalLinkResponse> = z.object({
  final_link_id: z.number(),
  rejected_at: z.string(),
  rejected_suggestion_id: z.number(),
  status: z.literal("rejected"),
});

const approveLinkProposalResponseSchema: z.ZodType<ApproveLinkProposalResponse> = z.object({
  final_link_id: z.number(),
  proposal_id: z.number(),
  status: z.literal("approved"),
});

const rejectLinkProposalResponseSchema: z.ZodType<RejectLinkProposalResponse> = z.object({
  proposal_id: z.number(),
  rejected_at: z.string(),
  status: z.literal("rejected"),
});

export const playlistQueryKeys = {
  all: ["playlists"] as const,
  config: () => ["playlists", "config"] as const,
  detail: (playlistId: number | string) => ["playlists", playlistId, "detail"] as const,
  list: () => ["playlists", "list"] as const,
  proposals: (filters: LinkProposalListFilters = {}) =>
    ["playlists", "proposals", "list", { confidenceBand: filters.confidenceBand ?? null }] as const,
  proposalPages: (filters: LinkProposalListFilters = {}) =>
    ["playlists", "proposals", "pages", { confidenceBand: filters.confidenceBand ?? null }] as const,
  tracks: (playlistId: number | string) => ["playlists", playlistId, "tracks"] as const,
};

export function playlistConfigurationInvalidationKeys(): QueryKey[] {
  return [playlistQueryKeys.list(), playlistQueryKeys.config()];
}

export function playlistConfigurationMutationInvalidationKeys(): QueryKey[] {
  return [...playlistConfigurationInvalidationKeys(), ...missingLocallyInvalidationKeys()];
}

export function playlistContentInvalidationKeys(playlistIds: readonly (number | string)[]): QueryKey[] {
  return [
    playlistQueryKeys.list(),
    ...playlistIds.flatMap((playlistId) => [
      playlistQueryKeys.detail(playlistId),
      playlistQueryKeys.tracks(playlistId),
    ]),
  ];
}

export function playlistCollectionJobInvalidationKeys(): QueryKey[] {
  return [...playlistConfigurationInvalidationKeys(), ...missingLocallyInvalidationKeys()];
}

export function playlistSyncJobInvalidationKeys(playlistIds: readonly (number | string)[]): QueryKey[] {
  return [
    ...playlistContentInvalidationKeys(playlistIds),
    playlistQueryKeys.config(),
    ...missingLocallyInvalidationKeys(),
  ];
}

export function playlistLinkInvalidationKeys(): QueryKey[] {
  return [playlistQueryKeys.all];
}

export async function invalidatePlaylistConfigurationQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, playlistConfigurationInvalidationKeys());
}

export async function invalidatePlaylistConfigurationMutationQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, playlistConfigurationMutationInvalidationKeys());
}

export async function invalidatePlaylistContentQueries(
  queryClient: QueryClient,
  playlistIds: readonly (number | string)[],
): Promise<void> {
  await invalidateQueryKeys(queryClient, playlistContentInvalidationKeys(playlistIds));
}

export async function invalidatePlaylistLinkQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, playlistLinkInvalidationKeys());
}

function hasPlaylistId(playlistId: number | string | null | undefined): playlistId is number | string {
  if (typeof playlistId === "number") {
    return Number.isFinite(playlistId);
  }

  return typeof playlistId === "string" && playlistId.trim().length > 0;
}

function getFilenameFromContentDisposition(contentDisposition: string | null) {
  const fallbackFilename = "playlist.m3u";

  if (!contentDisposition) {
    return fallbackFilename;
  }

  const filenameMatch = /filename="?(?<filename>[^";]+)"?/i.exec(contentDisposition);
  return filenameMatch?.groups?.filename ?? fallbackFilename;
}

export async function fetchPlaylistDetail(playlistId: number | string): Promise<PlaylistDetailResponse> {
  return fetchJson(
    endpoints.api(`/playlists/${encodeURIComponent(String(playlistId))}`),
    playlistDetailResponseSchema,
  );
}

export async function fetchStreamingPlaylists(): Promise<StreamingPlaylistsResponse> {
  return fetchJson(endpoints.api("/streaming/playlists"), streamingPlaylistsResponseSchema);
}

export async function fetchStreamingPlaylistConfig(): Promise<StreamingPlaylistConfigResponse> {
  return fetchJson(endpoints.api("/streaming/playlists/config"), streamingPlaylistConfigResponseSchema);
}

export async function updateStreamingPlaylistConfig({
  playlistId,
  sync_mode,
}: UpdateStreamingPlaylistConfigInput): Promise<StreamingPlaylistConfig> {
  return patchJson(endpoints.api(`/streaming/playlists/${encodeURIComponent(String(playlistId))}`), {
    body: { sync_mode },
    errorMessage: "Playlist update request failed",
    schema: streamingPlaylistConfigSchema,
  });
}

export async function refreshStreamingAccountMetadata(accountId: number | string): Promise<StreamingSyncResponse> {
  return postJson(endpoints.api(`/streaming/accounts/${encodeURIComponent(String(accountId))}/refresh-metadata`), {
    errorMessage: "Metadata refresh request failed",
    schema: streamingSyncResponseSchema,
  });
}

export async function syncStreamingAccount(accountId: number | string): Promise<StreamingSyncResponse> {
  return postJson(endpoints.api(`/streaming/accounts/${encodeURIComponent(String(accountId))}/sync`), {
    errorMessage: "Sync request failed",
    schema: streamingSyncResponseSchema,
  });
}

export async function syncStreamingPlaylist(playlistId: number | string): Promise<PlaylistSyncResponse> {
  return postJson(endpoints.api(`/streaming/playlists/${encodeURIComponent(String(playlistId))}/sync`), {
    errorMessage: "Playlist sync request failed",
    schema: playlistSyncResponseSchema,
  });
}

export async function deleteFinalLink(finalLinkId: number | string): Promise<DeleteFinalLinkResponse> {
  return deleteJson(endpoints.api(`/final-links/${encodeURIComponent(String(finalLinkId))}`), {
    errorMessage: "Final link delete request failed",
    schema: deleteFinalLinkResponseSchema,
  });
}

export async function fetchPlaylistTracks(playlistId: number | string): Promise<PlaylistTracksResponse> {
  return fetchJson(
    endpoints.api(`/playlists/${encodeURIComponent(String(playlistId))}/tracks`),
    playlistTracksResponseSchema,
  );
}

export async function fetchLinkProposals(query: LinkProposalListQuery = {}): Promise<LinkProposalsResponse> {
  const params = new URLSearchParams();

  if (query.confidenceBand) {
    params.set("band", query.confidenceBand);
  }
  if (query.cursor !== null && query.cursor !== undefined) {
    params.set("cursor", query.cursor);
  }
  if (query.limit !== undefined) {
    params.set("limit", String(query.limit));
  }

  const queryString = params.toString();
  return fetchJson(
    endpoints.api(`/proposals${queryString ? `?${queryString}` : ""}`),
    linkProposalsResponseSchema,
  );
}

export async function approveLinkProposal(proposalId: number | string): Promise<ApproveLinkProposalResponse> {
  return postJson(endpoints.api(`/proposals/${encodeURIComponent(String(proposalId))}/approve`), {
    errorMessage: "Proposal approve request failed",
    schema: approveLinkProposalResponseSchema,
  });
}

export async function rejectLinkProposal(proposalId: number | string): Promise<RejectLinkProposalResponse> {
  return postJson(endpoints.api(`/proposals/${encodeURIComponent(String(proposalId))}/reject`), {
    errorMessage: "Proposal reject request failed",
    schema: rejectLinkProposalResponseSchema,
  });
}

export async function exportPlaylistM3u(playlistId: number | string): Promise<PlaylistM3uExport> {
  const { blob, response } = await fetchBlob(
    endpoints.api(`/playlists/${encodeURIComponent(String(playlistId))}/m3u`),
    "M3U export request failed",
  );

  return {
    blob,
    filename: getFilenameFromContentDisposition(response.headers.get("Content-Disposition")),
  };
}

export function usePlaylistDetailQuery(playlistId: number | string | null | undefined) {
  const queryPlaylistId = hasPlaylistId(playlistId) ? playlistId : null;

  return useQuery({
    queryKey: queryPlaylistId === null ? playlistQueryKeys.detail("idle") : playlistQueryKeys.detail(queryPlaylistId),
    queryFn: () => {
      if (queryPlaylistId === null) {
        throw new Error("Playlist detail query requires a playlist id");
      }

      return fetchPlaylistDetail(queryPlaylistId);
    },
    enabled: queryPlaylistId !== null,
  });
}

export function useStreamingPlaylistsQuery() {
  return useQuery({
    queryKey: playlistQueryKeys.list(),
    queryFn: fetchStreamingPlaylists,
  });
}

export function useStreamingPlaylistConfigQuery() {
  return useQuery({
    queryKey: playlistQueryKeys.config(),
    queryFn: fetchStreamingPlaylistConfig,
  });
}

export function usePlaylistTracksQuery(playlistId: number | string | null | undefined) {
  const queryPlaylistId = hasPlaylistId(playlistId) ? playlistId : null;

  return useQuery({
    queryKey: queryPlaylistId === null ? playlistQueryKeys.tracks("idle") : playlistQueryKeys.tracks(queryPlaylistId),
    queryFn: () => {
      if (queryPlaylistId === null) {
        throw new Error("Playlist tracks query requires a playlist id");
      }

      return fetchPlaylistTracks(queryPlaylistId);
    },
    enabled: queryPlaylistId !== null,
  });
}

export function useLinkProposalsQuery(filters: LinkProposalListFilters = {}) {
  return useQuery({
    queryKey: playlistQueryKeys.proposals(filters),
    queryFn: () => fetchLinkProposals(filters),
  });
}

export function useLinkProposalsInfiniteQuery(filters: LinkProposalListFilters = {}) {
  return useInfiniteQuery({
    queryKey: playlistQueryKeys.proposalPages(filters),
    queryFn: ({ pageParam }) =>
      fetchLinkProposals({
        ...filters,
        cursor: pageParam,
        limit: DEFAULT_LINK_PROPOSAL_LIMIT,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
}
