import { type QueryClient, type QueryKey, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { deleteJson, endpoints, fetchBlob, fetchJson, patchJson, postBlob, postJson } from "../../lib/api";
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
export type M3uExportProfile = ApiSchemas["M3uExportProfileResponse"];
export type M3uExportProfileListResponse = ApiSchemas["M3uExportProfileListResponse"];
export type CreateM3uExportProfileInput = ApiSchemas["CreateM3uExportProfileRequest"];
export type M3uExportRequest = ApiSchemas["M3uExportRequest"];
export type M3uExportFormat = NonNullable<M3uExportRequest["formats"]>[number];
export type M3uExportPathFormat = NonNullable<M3uExportRequest["path_format"]>;
export type M3uExportPreviewResponse = ApiSchemas["M3uExportPreviewResponse"];
export type M3uExportZip = {
  blob: Blob;
  filename: string;
};
export type RekordboxXmlExport = {
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

const streamingPlaylistBaseSchema = z.object({
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

const streamingPlaylistSchema: z.ZodType<StreamingPlaylist> = streamingPlaylistBaseSchema;
const streamingPlaylistConfigSchema: z.ZodType<StreamingPlaylistConfig> = streamingPlaylistBaseSchema;

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

const m3uExportProfileSchema: z.ZodType<M3uExportProfile> = z.object({
  id: z.number(),
  is_default: z.boolean(),
  library_path: z.string(),
  name: z.string(),
});

const m3uExportProfileListResponseSchema: z.ZodType<M3uExportProfileListResponse> = z.object({
  profiles: z.array(m3uExportProfileSchema),
});

const m3uExportFormatSchema = z.enum(["m3u", "m3u8"]);
const m3uExportPathFormatSchema = z.enum(["absolute", "file_url"]);

const m3uExportPlaylistPreviewSchema = z.object({
  archive_path_m3u: z.string(),
  archive_path_m3u8: z.string(),
  archive_paths: z.array(z.string()),
  exported_track_count: z.number(),
  filename_m3u: z.string(),
  filename_m3u8: z.string(),
  filenames: z.array(z.string()),
  generated_playlist_id: z.number().nullable(),
  generated_run_id: z.number().nullable(),
  playlist_id: z.number().nullable(),
  sample_path: nullableStringSchema,
  skipped_track_count: z.number(),
  source: z.enum(["streaming", "generated"]),
  title: z.string(),
});

const m3uExportPreviewResponseSchema: z.ZodType<M3uExportPreviewResponse> = z.object({
  formats: z.array(m3uExportFormatSchema),
  library_path: z.string(),
  path_format: m3uExportPathFormatSchema,
  playlist_count: z.number(),
  playlists: z.array(m3uExportPlaylistPreviewSchema),
  total_exported_track_count: z.number(),
  total_skipped_track_count: z.number(),
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
  m3uExportProfiles: () => ["playlists", "m3u", "export-profiles"] as const,
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

function getFilenameFromContentDisposition(contentDisposition: string | null, fallbackFilename = "playlist.m3u") {
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

export async function fetchM3uExportProfiles(): Promise<M3uExportProfileListResponse> {
  return fetchJson(endpoints.api("/m3u/export-profiles"), m3uExportProfileListResponseSchema);
}

export async function createM3uExportProfile(input: CreateM3uExportProfileInput): Promise<M3uExportProfile> {
  return postJson(endpoints.api("/m3u/export-profiles"), {
    body: input,
    errorMessage: "M3U export profile create request failed",
    schema: m3uExportProfileSchema,
  });
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

export async function previewM3uExport(input: M3uExportRequest): Promise<M3uExportPreviewResponse> {
  return postJson(endpoints.api("/m3u/export/preview"), {
    body: input,
    errorMessage: "M3U export preview request failed",
    schema: m3uExportPreviewResponseSchema,
  });
}

export async function exportM3uZip(input: M3uExportRequest): Promise<M3uExportZip> {
  const { blob, response } = await postBlob(endpoints.api("/m3u/export"), {
    body: input,
    errorMessage: "M3U export request failed",
  });

  return {
    blob,
    filename: getFilenameFromContentDisposition(response.headers.get("Content-Disposition")),
  };
}

export async function exportRekordboxXml(input: M3uExportRequest): Promise<RekordboxXmlExport> {
  const { blob, response } = await postBlob(endpoints.api("/m3u/export/rekordbox-xml"), {
    body: input,
    errorMessage: "Rekordbox XML export request failed",
  });

  return {
    blob,
    filename: getFilenameFromContentDisposition(response.headers.get("Content-Disposition"), "rekordbox.xml"),
  };
}

export async function exportFullRekordboxXml(input: M3uExportRequest): Promise<RekordboxXmlExport> {
  const { blob, response } = await postBlob(endpoints.api("/m3u/export/rekordbox-xml/full"), {
    body: input,
    errorMessage: "Full Rekordbox XML export request failed",
  });

  return {
    blob,
    filename: getFilenameFromContentDisposition(response.headers.get("Content-Disposition"), "crate-lynx-rekordbox.xml"),
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

export function useM3uExportProfilesQuery() {
  return useQuery({
    queryKey: playlistQueryKeys.m3uExportProfiles(),
    queryFn: fetchM3uExportProfiles,
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
