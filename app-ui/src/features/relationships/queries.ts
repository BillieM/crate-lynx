import { type QueryClient, type QueryKey, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { endpoints, fetchJson, postJson } from "../../lib/api";
import type { components } from "../../lib/api-types";
import { invalidateQueryKeys } from "../../lib/queryInvalidation";
import { playlistLinkInvalidationKeys } from "../playlists/queries";
import { shellSummaryInvalidationKeys } from "../shell/queries";
import { soulseekQueueInvalidationKeys } from "../soulseek/queryKeys";

type ApiSchemas = components["schemas"];

export type StreamingRelationshipSuggestion = ApiSchemas["StreamingRelationshipSuggestionResponse"];
export type StreamingRelationshipSuggestionsResponse = ApiSchemas["StreamingRelationshipSuggestionListResponse"];
export type GenerateStreamingRelationshipSuggestionsResponse =
  ApiSchemas["GenerateStreamingRelationshipSuggestionsResponse"];
export type AcceptStreamingRelationshipSuggestionRequest =
  ApiSchemas["AcceptStreamingRelationshipSuggestionRequest"];
export type AcceptStreamingRelationshipSuggestionResponse =
  ApiSchemas["AcceptStreamingRelationshipSuggestionResponse"];
export type RejectStreamingRelationshipSuggestionResponse =
  ApiSchemas["RejectStreamingRelationshipSuggestionResponse"];
export type AcceptStreamingRelationshipSuggestionInput = AcceptStreamingRelationshipSuggestionRequest & {
  suggestionId: number | string;
};
export type StreamingRelationshipSuggestionType = StreamingRelationshipSuggestion["relationship_type"];

export type StreamingRelationshipSuggestionsQuery = {
  cursor?: string | null;
  limit?: number;
  relationshipType?: StreamingRelationshipSuggestionType;
};

export const DEFAULT_STREAMING_RELATIONSHIP_SUGGESTION_LIMIT = 50;

const nullableStringSchema = z.string().nullable();
const relationshipTypeSchema = z.enum(["equivalent", "related"]);
const relationshipStatusSchema = z.enum(["pending", "accepted", "rejected"]);
const relationshipConflictStateSchema = z.enum(["none", "different_local_links"]);
const relationshipResolutionSourceSchema = z.enum(["direct", "equivalent"]);

const streamingRelationshipTrackSchema: z.ZodType<ApiSchemas["StreamingRelationshipTrackResponse"]> = z.object({
  album: nullableStringSchema,
  artist: z.string(),
  duration_ms: z.number().nullable(),
  id: z.number(),
  isrc: nullableStringSchema,
  provider_track_id: z.string(),
  title: z.string(),
  year: z.number().nullable(),
});

const streamingRelationshipLocalLinkSchema: z.ZodType<ApiSchemas["StreamingRelationshipLocalLinkResponse"]> =
  z.object({
    approved_at: z.string(),
    final_link_id: z.number(),
    local_album: nullableStringSchema,
    local_artist: nullableStringSchema,
    local_file_path: nullableStringSchema,
    local_title: nullableStringSchema,
    local_track_id: z.number(),
    resolution_source: relationshipResolutionSourceSchema,
    source_streaming_track_id: z.number(),
    streaming_track_id: z.number(),
  });

const streamingRelationshipConflictSchema: z.ZodType<ApiSchemas["StreamingRelationshipConflictResponse"]> =
  z.object({
    final_links: z.array(streamingRelationshipLocalLinkSchema),
    first_group_track_ids: z.array(z.number()),
    local_track_ids: z.array(z.number()),
    second_group_track_ids: z.array(z.number()),
  });

const streamingRelationshipSuggestionSchema: z.ZodType<StreamingRelationshipSuggestion> = z.object({
  confidence: z.string(),
  conflict: streamingRelationshipConflictSchema.nullable(),
  conflict_state: relationshipConflictStateSchema,
  created_at: z.string(),
  first_link: streamingRelationshipLocalLinkSchema.nullable(),
  first_track: streamingRelationshipTrackSchema,
  id: z.number(),
  match_method: z.string(),
  relationship_type: relationshipTypeSchema,
  score: z.number(),
  second_link: streamingRelationshipLocalLinkSchema.nullable(),
  second_track: streamingRelationshipTrackSchema,
  status: relationshipStatusSchema,
});

const streamingRelationshipSuggestionsResponseSchema: z.ZodType<StreamingRelationshipSuggestionsResponse> =
  z.object({
    limit: z.number(),
    next_cursor: z.string().nullable(),
    returned_count: z.number(),
    suggestions: z.array(streamingRelationshipSuggestionSchema),
    total_count: z.number(),
  });

const generateStreamingRelationshipSuggestionsResponseSchema: z.ZodType<GenerateStreamingRelationshipSuggestionsResponse> =
  z.object({
    created_count: z.number(),
    pruned_count: z.number(),
  });

const acceptStreamingRelationshipSuggestionResponseSchema: z.ZodType<AcceptStreamingRelationshipSuggestionResponse> =
  z.object({
    accepted_at: z.string(),
    detached_final_link_ids: z.array(z.number()),
    relationship_id: z.number(),
    relationship_type: relationshipTypeSchema,
    status: z.literal("accepted"),
    suggestion_id: z.number(),
  });

const rejectStreamingRelationshipSuggestionResponseSchema: z.ZodType<RejectStreamingRelationshipSuggestionResponse> =
  z.object({
    rejected_at: z.string(),
    status: z.literal("rejected"),
    suggestion_id: z.number(),
  });

export const streamingRelationshipQueryKeys = {
  all: ["streaming-relationships"] as const,
  suggestions: (query?: StreamingRelationshipSuggestionsQuery) =>
    query === undefined
      ? (["streaming-relationships", "suggestions"] as const)
      : (["streaming-relationships", "suggestions", query] as const),
  suggestionPages: (query?: Omit<StreamingRelationshipSuggestionsQuery, "cursor">) =>
    query === undefined
      ? (["streaming-relationships", "suggestion-pages"] as const)
      : (["streaming-relationships", "suggestion-pages", query] as const),
};

export function streamingRelationshipSuggestionInvalidationKeys(): QueryKey[] {
  return [
    streamingRelationshipQueryKeys.suggestions(),
    streamingRelationshipQueryKeys.suggestionPages(),
    ...shellSummaryInvalidationKeys(),
  ];
}

export function streamingRelationshipMutationInvalidationKeys(): QueryKey[] {
  return [
    ...streamingRelationshipSuggestionInvalidationKeys(),
    ...playlistLinkInvalidationKeys(),
    ...soulseekQueueInvalidationKeys(),
  ];
}

export async function invalidateStreamingRelationshipSuggestionQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, streamingRelationshipSuggestionInvalidationKeys());
}

export async function invalidateStreamingRelationshipMutationQueries(queryClient: QueryClient): Promise<void> {
  await invalidateQueryKeys(queryClient, streamingRelationshipMutationInvalidationKeys());
}

function relationshipSuggestionsUrl({
  cursor,
  limit = DEFAULT_STREAMING_RELATIONSHIP_SUGGESTION_LIMIT,
  relationshipType,
}: StreamingRelationshipSuggestionsQuery = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor !== null && cursor !== undefined) {
    params.set("cursor", cursor);
  }
  if (relationshipType !== undefined) {
    params.set("relationship_type", relationshipType);
  }

  return endpoints.api(`/streaming/relationships/suggestions?${params.toString()}`);
}

export async function fetchStreamingRelationshipSuggestions(
  query: StreamingRelationshipSuggestionsQuery = {},
): Promise<StreamingRelationshipSuggestionsResponse> {
  return fetchJson(
    relationshipSuggestionsUrl(query),
    streamingRelationshipSuggestionsResponseSchema,
  );
}

export async function generateStreamingRelationshipSuggestions(): Promise<GenerateStreamingRelationshipSuggestionsResponse> {
  return postJson(endpoints.api("/streaming/relationships/suggestions/generate"), {
    errorMessage: "Relationship suggestion generation request failed",
    schema: generateStreamingRelationshipSuggestionsResponseSchema,
  });
}

export async function acceptStreamingRelationshipSuggestion({
  relationship_type,
  suggestionId,
  winning_final_link_id,
}: AcceptStreamingRelationshipSuggestionInput): Promise<AcceptStreamingRelationshipSuggestionResponse> {
  const body: AcceptStreamingRelationshipSuggestionRequest = {};
  if (relationship_type !== undefined) {
    body.relationship_type = relationship_type;
  }
  if (winning_final_link_id !== undefined) {
    body.winning_final_link_id = winning_final_link_id;
  }

  return postJson(
    endpoints.api(`/streaming/relationships/suggestions/${encodeURIComponent(String(suggestionId))}/accept`),
    {
      body: Object.keys(body).length === 0 ? undefined : body,
      errorMessage: "Relationship suggestion accept request failed",
      schema: acceptStreamingRelationshipSuggestionResponseSchema,
    },
  );
}

export async function rejectStreamingRelationshipSuggestion(
  suggestionId: number | string,
): Promise<RejectStreamingRelationshipSuggestionResponse> {
  return postJson(
    endpoints.api(`/streaming/relationships/suggestions/${encodeURIComponent(String(suggestionId))}/reject`),
    {
      errorMessage: "Relationship suggestion reject request failed",
      schema: rejectStreamingRelationshipSuggestionResponseSchema,
    },
  );
}

export function useStreamingRelationshipSuggestionsQuery(query: StreamingRelationshipSuggestionsQuery = {}) {
  return useQuery({
    queryKey: streamingRelationshipQueryKeys.suggestions(query),
    queryFn: () => fetchStreamingRelationshipSuggestions(query),
  });
}

export function useStreamingRelationshipSuggestionsInfiniteQuery(
  query: Omit<StreamingRelationshipSuggestionsQuery, "cursor"> = {},
) {
  return useInfiniteQuery({
    queryKey: streamingRelationshipQueryKeys.suggestionPages(query),
    queryFn: ({ pageParam }) =>
      fetchStreamingRelationshipSuggestions({
        ...query,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
}

export function useGenerateStreamingRelationshipSuggestionsMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: generateStreamingRelationshipSuggestions,
    onSuccess: () => invalidateStreamingRelationshipSuggestionQueries(queryClient),
  });
}

export function useAcceptStreamingRelationshipSuggestionMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: acceptStreamingRelationshipSuggestion,
    onSuccess: () => invalidateStreamingRelationshipMutationQueries(queryClient),
  });
}

export function useRejectStreamingRelationshipSuggestionMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: rejectStreamingRelationshipSuggestion,
    onSuccess: () => invalidateStreamingRelationshipMutationQueries(queryClient),
  });
}
