import { type QueryKey, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteJson, endpoints, fetchJson, patchJson, postJson } from "../../lib/api";
import { invalidateQueryKeys } from "../../lib/queryInvalidation";
import { libraryLinkMutationInvalidationKeys } from "../library/queries";
import { missingLocallyInvalidationKeys } from "../maintenance/queries";
import { playlistLinkInvalidationKeys } from "../playlists/queries";
import { streamingRelationshipMutationInvalidationKeys } from "../relationships/queries";

export type TrackDetailTarget =
  | { id: number | string; type: "local" }
  | { id: number | string; type: "streaming" };

export type MetadataField = {
  key: string;
  value: string | null;
};

export type StreamingTrackSummary = {
  album: string | null;
  artist: string;
  duration_ms: number | null;
  id: number;
  isrc: string | null;
  provider_track_id: string;
  title: string;
  year: number | null;
};

export type LocalTrackSummary = {
  album: string | null;
  artist: string | null;
  file_path: string;
  id: number;
  library_root_rel_path: string;
  title: string | null;
};

export type LocalTrackFinalLink = {
  approved_at: string;
  id: number;
  streaming_track: StreamingTrackSummary;
  streaming_track_id: number;
};

export type LocalTrackSuggestion = {
  created_at: string;
  id: number;
  match_method: string;
  score: number;
  status: string;
  streaming_track: StreamingTrackSummary;
  streaming_track_id: number;
};

export type LocalTrackFailedIngestionAttempt = {
  failed_at: string;
  failure_reason: string;
  filename: string;
  id: number;
  source_path: string;
};

export type BeetsDetail = {
  attributes: MetadataField[];
  fields: MetadataField[];
};

export type BeetsItemDetail = BeetsDetail & {
  beets_id: number;
};

export type BeetsAlbumDetail = BeetsDetail & {
  beets_album_id: number;
};

export type LocalTrackDetail = {
  album: string | null;
  artist: string | null;
  beets_album: BeetsAlbumDetail | null;
  beets_id: number | null;
  beets_item: BeetsItemDetail | null;
  created_at: string;
  duration_ms: number | null;
  failed_ingestion_attempts: LocalTrackFailedIngestionAttempt[];
  file_path: string;
  final_link: LocalTrackFinalLink | null;
  fingerprint: string | null;
  id: number;
  library_root_rel_path: string;
  link_status: "linked" | "pending" | "unlinked" | string;
  pending_suggestions: LocalTrackSuggestion[];
  title: string | null;
  updated_at: string;
};

export type StreamingTrackLocalLink = {
  approved_at: string;
  final_link_id: number;
  local_track: LocalTrackSummary;
  local_track_id: number;
  resolution_source: "direct" | "equivalent" | string;
  source_streaming_track_id: number;
};

export type StreamingTrackRelationship = {
  accepted_at: string;
  id: number;
  peer_track: StreamingTrackSummary;
  relationship_type: "equivalent" | "related" | string;
};

export type StreamingTrackPlaylistAppearance = {
  account_id: number;
  playlist_id: number;
  position: number;
  provider_playlist_id: string;
  sync_mode: "off" | "match_only" | "full";
  title: string;
};

export type StreamingTrackPendingLocalSuggestion = {
  created_at: string;
  id: number;
  local_track: LocalTrackSummary;
  local_track_id: number;
  match_method: string;
  score: number;
  status: string;
};

export type StreamingTrackDetail = StreamingTrackSummary & {
  equivalent_tracks: StreamingTrackSummary[];
  pending_local_suggestions: StreamingTrackPendingLocalSuggestion[];
  playlist_appearances: StreamingTrackPlaylistAppearance[];
  relationships: StreamingTrackRelationship[];
  resolved_local_link: StreamingTrackLocalLink | null;
};

export type LocalTrackSearchResult = {
  album: string | null;
  artist: string | null;
  file_path: string;
  final_link_id: number | null;
  id: number;
  library_root_rel_path: string;
  link_status: string;
  title: string | null;
};

export type StreamingTrackSearchResult = StreamingTrackSummary & {
  final_link_id: number | null;
  link_status: string;
  local_track_id: number | null;
};

export type CreateFinalLinkInput = {
  detach_conflicting_final_link_ids?: number[];
  local_track_id: number;
  replace_final_link_id?: number | null;
  streaming_track_id: number;
};

export type CreateFinalLinkResponse = {
  approved_at: string;
  detached_final_link_ids: number[];
  final_link_id: number;
  local_track_id: number;
  replaced_final_link_id: number | null;
  status: "approved" | string;
  streaming_track_id: number;
};

export type StreamingRelationshipMutationInput = {
  first_track_id?: number;
  relationship_id?: number;
  relationship_type: "equivalent" | "related";
  second_track_id?: number;
  winning_final_link_id?: number | null;
};

export type StreamingRelationshipMutationResponse = {
  accepted_at: string | null;
  detached_final_link_ids: number[];
  relationship_id: number;
  relationship_type: "equivalent" | "related";
  status: "created" | "updated" | "deleted";
};

export const trackDetailQueryKeys = {
  all: ["track-detail"] as const,
  detail: (target: TrackDetailTarget) => ["track-detail", target.type, String(target.id)] as const,
  localSearch: (query: string) => ["track-detail", "local-search", query] as const,
  streamingSearch: (query: string) => ["track-detail", "streaming-search", query] as const,
};

export function trackMutationInvalidationKeys(): QueryKey[] {
  return [
    trackDetailQueryKeys.all,
    ...playlistLinkInvalidationKeys(),
    ...libraryLinkMutationInvalidationKeys(),
    ...streamingRelationshipMutationInvalidationKeys(),
    ...missingLocallyInvalidationKeys(),
  ];
}

export function parseTrackDetailTarget(rawTarget: string | null | undefined): TrackDetailTarget | null {
  if (!rawTarget) {
    return null;
  }

  if (rawTarget.startsWith("streaming:")) {
    const id = rawTarget.slice("streaming:".length);
    return id ? { id, type: "streaming" } : null;
  }

  if (rawTarget.startsWith("local:")) {
    const id = rawTarget.slice("local:".length);
    return id ? { id, type: "local" } : null;
  }

  return { id: rawTarget, type: "local" };
}

export function formatTrackDetailTarget(target: TrackDetailTarget) {
  return `${target.type}:${target.id}`;
}

export async function fetchLocalTrackDetail(localTrackId: number | string): Promise<LocalTrackDetail> {
  return fetchJson<LocalTrackDetail>(endpoints.api(`/local-tracks/${encodeURIComponent(String(localTrackId))}`));
}

export async function fetchStreamingTrackDetail(streamingTrackId: number | string): Promise<StreamingTrackDetail> {
  return fetchJson<StreamingTrackDetail>(
    endpoints.api(`/streaming/tracks/${encodeURIComponent(String(streamingTrackId))}`),
  );
}

export async function fetchTrackDetail(target: TrackDetailTarget): Promise<LocalTrackDetail | StreamingTrackDetail> {
  return target.type === "local" ? fetchLocalTrackDetail(target.id) : fetchStreamingTrackDetail(target.id);
}

export async function searchLocalTracks(query: string): Promise<{ tracks: LocalTrackSearchResult[] }> {
  const params = new URLSearchParams({ limit: "20", q: query });
  return fetchJson<{ tracks: LocalTrackSearchResult[] }>(endpoints.api(`/local-tracks/search?${params.toString()}`));
}

export async function searchStreamingTracks(query: string): Promise<{ tracks: StreamingTrackSearchResult[] }> {
  const params = new URLSearchParams({ limit: "20", q: query });
  return fetchJson<{ tracks: StreamingTrackSearchResult[] }>(
    endpoints.api(`/streaming/tracks/search?${params.toString()}`),
  );
}

export async function createFinalLink(input: CreateFinalLinkInput): Promise<CreateFinalLinkResponse> {
  return postJson<CreateFinalLinkResponse>(endpoints.api("/final-links"), {
    body: input,
    errorMessage: "Final link create request failed",
  });
}

export async function deleteFinalLink(finalLinkId: number | string) {
  return deleteJson(endpoints.api(`/final-links/${encodeURIComponent(String(finalLinkId))}`), {
    errorMessage: "Final link delete request failed",
  });
}

export async function createStreamingRelationship(
  input: StreamingRelationshipMutationInput,
): Promise<StreamingRelationshipMutationResponse> {
  return postJson<StreamingRelationshipMutationResponse>(endpoints.api("/streaming/relationships"), {
    body: {
      first_track_id: input.first_track_id,
      relationship_type: input.relationship_type,
      second_track_id: input.second_track_id,
      winning_final_link_id: input.winning_final_link_id,
    },
    errorMessage: "Streaming relationship create request failed",
  });
}

export async function updateStreamingRelationship(
  input: StreamingRelationshipMutationInput,
): Promise<StreamingRelationshipMutationResponse> {
  return patchJson<StreamingRelationshipMutationResponse>(
    endpoints.api(`/streaming/relationships/${encodeURIComponent(String(input.relationship_id))}`),
    {
      body: {
        relationship_type: input.relationship_type,
        winning_final_link_id: input.winning_final_link_id,
      },
      errorMessage: "Streaming relationship update request failed",
    },
  );
}

export async function deleteStreamingRelationship(
  relationshipId: number | string,
): Promise<StreamingRelationshipMutationResponse> {
  return deleteJson<StreamingRelationshipMutationResponse>(
    endpoints.api(`/streaming/relationships/${encodeURIComponent(String(relationshipId))}`),
    {
      errorMessage: "Streaming relationship delete request failed",
    },
  );
}

export function useTrackDetailQuery(target: TrackDetailTarget | null, enabled = true) {
  return useQuery({
    enabled: enabled && target !== null,
    queryKey: target ? trackDetailQueryKeys.detail(target) : ["track-detail", "idle"],
    queryFn: () => fetchTrackDetail(target as TrackDetailTarget),
  });
}

export function useTrackMutationInvalidation() {
  const queryClient = useQueryClient();

  return async () => {
    await invalidateQueryKeys(queryClient, trackMutationInvalidationKeys());
  };
}

export function useCreateFinalLinkMutation() {
  const invalidate = useTrackMutationInvalidation();

  return useMutation({
    mutationFn: createFinalLink,
    onSuccess: invalidate,
  });
}

export function useDeleteFinalLinkMutation() {
  const invalidate = useTrackMutationInvalidation();

  return useMutation({
    mutationFn: deleteFinalLink,
    onSuccess: invalidate,
  });
}

export function useCreateStreamingRelationshipMutation() {
  const invalidate = useTrackMutationInvalidation();

  return useMutation({
    mutationFn: createStreamingRelationship,
    onSuccess: invalidate,
  });
}

export function useUpdateStreamingRelationshipMutation() {
  const invalidate = useTrackMutationInvalidation();

  return useMutation({
    mutationFn: updateStreamingRelationship,
    onSuccess: invalidate,
  });
}

export function useDeleteStreamingRelationshipMutation() {
  const invalidate = useTrackMutationInvalidation();

  return useMutation({
    mutationFn: deleteStreamingRelationship,
    onSuccess: invalidate,
  });
}
