import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import {
  acceptStreamingRelationshipSuggestion,
  fetchStreamingRelationshipSuggestions,
  generateStreamingRelationshipSuggestions,
  rejectStreamingRelationshipSuggestion,
  streamingRelationshipMutationInvalidationKeys,
  streamingRelationshipQueryKeys,
  streamingRelationshipSuggestionInvalidationKeys,
  type StreamingRelationshipSuggestionsResponse,
  useStreamingRelationshipSuggestionsQuery,
} from "./queries";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

const relationshipSuggestionsResponse: StreamingRelationshipSuggestionsResponse = {
  limit: 50,
  next_cursor: null,
  returned_count: 1,
  suggestions: [
    {
      id: 91,
      confidence: "high",
      conflict_state: "different_local_links",
      created_at: "2026-05-18T12:00:00Z",
      match_method: "isrc",
      relationship_type: "equivalent",
      score: 0.99,
      status: "pending",
      first_track: {
        id: 901,
        provider_track_id: "ytm:first-901",
        title: "Night Runner",
        artist: "Frame Delay",
        album: "Late Night Drive",
        year: 2024,
        isrc: "GBABC2400001",
        duration_ms: 214000,
      },
      second_track: {
        id: 902,
        provider_track_id: "ytm:second-902",
        title: "Night Runner",
        artist: "Frame Delay",
        album: "Private Archive",
        year: null,
        isrc: "GBABC2400001",
        duration_ms: 214400,
      },
      first_link: {
        approved_at: "2026-05-18T12:03:00Z",
        final_link_id: 7001,
        local_album: "Late Night Drive",
        local_artist: "Frame Delay",
        local_file_path: "Frame Delay/Night Runner.flac",
        local_title: "Night Runner",
        local_track_id: 501,
        resolution_source: "direct",
        source_streaming_track_id: 901,
        streaming_track_id: 901,
      },
      second_link: {
        approved_at: "2026-05-18T12:04:00Z",
        final_link_id: 7002,
        local_album: "Private Archive",
        local_artist: "Frame Delay",
        local_file_path: "Frame Delay/Night Runner Alt.flac",
        local_title: "Night Runner Alt",
        local_track_id: 502,
        resolution_source: "direct",
        source_streaming_track_id: 902,
        streaming_track_id: 902,
      },
      conflict: {
        final_links: [
          {
            approved_at: "2026-05-18T12:03:00Z",
            final_link_id: 7001,
            local_album: "Late Night Drive",
            local_artist: "Frame Delay",
            local_file_path: "Frame Delay/Night Runner.flac",
            local_title: "Night Runner",
            local_track_id: 501,
            resolution_source: "direct",
            source_streaming_track_id: 901,
            streaming_track_id: 901,
          },
          {
            approved_at: "2026-05-18T12:04:00Z",
            final_link_id: 7002,
            local_album: "Private Archive",
            local_artist: "Frame Delay",
            local_file_path: "Frame Delay/Night Runner Alt.flac",
            local_title: "Night Runner Alt",
            local_track_id: 502,
            resolution_source: "direct",
            source_streaming_track_id: 902,
            streaming_track_id: 902,
          },
        ],
        first_group_track_ids: [901],
        local_track_ids: [501, 502],
        second_group_track_ids: [902],
      },
    },
  ],
  total_count: 1,
};

describe("streaming relationship queries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("builds stable query and invalidation keys", () => {
    expect(streamingRelationshipQueryKeys.all).toEqual(["streaming-relationships"]);
    expect(streamingRelationshipQueryKeys.suggestions()).toEqual(["streaming-relationships", "suggestions"]);
    expect(streamingRelationshipQueryKeys.suggestionPages()).toEqual(["streaming-relationships", "suggestion-pages"]);
    expect(streamingRelationshipSuggestionInvalidationKeys()).toEqual([
      ["streaming-relationships", "suggestions"],
      ["streaming-relationships", "suggestion-pages"],
    ]);
    expect(streamingRelationshipMutationInvalidationKeys()).toEqual([
      ["streaming-relationships", "suggestions"],
      ["streaming-relationships", "suggestion-pages"],
      ["playlists"],
      ["maintenance", "missing-locally"],
    ]);
  });

  it("fetches streaming relationship suggestions from the backend endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => relationshipSuggestionsResponse,
    } as Response);

    await expect(fetchStreamingRelationshipSuggestions()).resolves.toEqual(relationshipSuggestionsResponse);
    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions?limit=50");
  });

  it("fetches filtered streaming relationship suggestions from the backend endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => relationshipSuggestionsResponse,
    } as Response);

    await expect(
      fetchStreamingRelationshipSuggestions({
        limit: 100,
        relationshipType: "related",
      }),
    ).resolves.toEqual(relationshipSuggestionsResponse);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/streaming/relationships/suggestions?limit=100&relationship_type=related",
    );
  });

  it("rejects relationship suggestions with unsupported enum values", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        ...relationshipSuggestionsResponse,
        suggestions: [
          {
            ...relationshipSuggestionsResponse.suggestions[0],
            relationship_type: "duplicate",
          },
        ],
      }),
    } as Response);

    await expect(fetchStreamingRelationshipSuggestions()).rejects.toThrow();
  });

  it("generates streaming relationship suggestions", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        created_count: 4,
        pruned_count: 3,
      }),
    } as Response);

    await expect(generateStreamingRelationshipSuggestions()).resolves.toEqual({ created_count: 4, pruned_count: 3 });
    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions/generate", {
      method: "POST",
    });
  });

  it("accepts a streaming relationship suggestion with a chosen type and optional conflict winner", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        accepted_at: "2026-05-18T12:30:00Z",
        detached_final_link_ids: [7002],
        relationship_id: 81,
        relationship_type: "equivalent",
        status: "accepted",
        suggestion_id: 91,
      }),
    } as Response);

    await expect(
      acceptStreamingRelationshipSuggestion({
        relationship_type: "equivalent",
        suggestionId: 91,
        winning_final_link_id: 7001,
      }),
    ).resolves.toEqual({
      accepted_at: "2026-05-18T12:30:00Z",
      detached_final_link_ids: [7002],
      relationship_id: 81,
      relationship_type: "equivalent",
      status: "accepted",
      suggestion_id: 91,
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions/91/accept", {
      body: JSON.stringify({ relationship_type: "equivalent", winning_final_link_id: 7001 }),
      headers: {
        "Content-Type": "application/json",
      },
      method: "POST",
    });
  });

  it("rejects a streaming relationship suggestion", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        rejected_at: "2026-05-18T12:35:00Z",
        status: "rejected",
        suggestion_id: 91,
      }),
    } as Response);

    await expect(rejectStreamingRelationshipSuggestion(91)).resolves.toEqual({
      rejected_at: "2026-05-18T12:35:00Z",
      status: "rejected",
      suggestion_id: 91,
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions/91/reject", {
      method: "POST",
    });
  });

  it("runs the streaming relationship suggestions hook", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => relationshipSuggestionsResponse,
    } as Response);

    const { result } = renderHook(() => useStreamingRelationshipSuggestionsQuery(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data?.suggestions[0]).toMatchObject({
      id: 91,
      relationship_type: "equivalent",
      conflict_state: "different_local_links",
    });
  });
});
