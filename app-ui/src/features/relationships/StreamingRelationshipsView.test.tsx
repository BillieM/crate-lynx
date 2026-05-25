import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import { createMockApi, jsonResponse } from "../../test/mockApi";
import { StreamingRelationshipsView } from "./StreamingRelationshipsView";
import type { StreamingRelationshipSuggestion, StreamingRelationshipSuggestionsResponse } from "./queries";

const equivalentSuggestion: StreamingRelationshipSuggestion = {
  id: 91,
  confidence: "high",
  conflict: null,
  conflict_state: "none",
  created_at: "2026-05-18T12:00:00Z",
  first_link: null,
  first_track: {
    album: "Late Night Drive",
    artist: "Frame Delay",
    duration_ms: 214000,
    id: 901,
    isrc: "GBABC2400001",
    provider_track_id: "ytm:first-901",
    title: "Night Runner",
    year: 2024,
  },
  match_method: "isrc",
  relationship_type: "equivalent",
  score: 0.99,
  second_link: null,
  second_track: {
    album: "Private Archive",
    artist: "Frame Delay",
    duration_ms: 214400,
    id: 902,
    isrc: "GBABC2400001",
    provider_track_id: "ytm:second-902",
    title: "Night Runner",
    year: null,
  },
  status: "pending",
};

const relatedSuggestion: StreamingRelationshipSuggestion = {
  id: 92,
  confidence: "medium",
  conflict: null,
  conflict_state: "none",
  created_at: "2026-05-18T12:05:00Z",
  first_link: null,
  first_track: {
    album: "Maintenance Window",
    artist: "Patch Bay",
    duration_ms: null,
    id: 903,
    isrc: null,
    provider_track_id: "ytm:first-903",
    title: "Loose Cable",
    year: null,
  },
  match_method: "fuzzy",
  relationship_type: "related",
  score: 0.73,
  second_link: null,
  second_track: {
    album: "Live Diagnostics",
    artist: "Patch Bay",
    duration_ms: 232000,
    id: 904,
    isrc: null,
    provider_track_id: "ytm:second-904",
    title: "Loose Cable Live",
    year: null,
  },
  status: "pending",
};

const conflictingEquivalentSuggestion: StreamingRelationshipSuggestion = {
  ...equivalentSuggestion,
  id: 93,
  conflict_state: "different_local_links",
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
};

const conflictingRelatedSuggestion: StreamingRelationshipSuggestion = {
  ...relatedSuggestion,
  id: 94,
  conflict_state: "different_local_links",
  first_link: {
    approved_at: "2026-05-18T12:03:00Z",
    final_link_id: 8001,
    local_album: "Maintenance Window",
    local_artist: "Patch Bay",
    local_file_path: "Patch Bay/Loose Cable.flac",
    local_title: "Loose Cable",
    local_track_id: 503,
    resolution_source: "direct",
    source_streaming_track_id: 903,
    streaming_track_id: 903,
  },
  second_link: {
    approved_at: "2026-05-18T12:04:00Z",
    final_link_id: 8002,
    local_album: "Live Diagnostics",
    local_artist: "Patch Bay",
    local_file_path: "Patch Bay/Loose Cable Live.flac",
    local_title: "Loose Cable Live",
    local_track_id: 504,
    resolution_source: "direct",
    source_streaming_track_id: 904,
    streaming_track_id: 904,
  },
  conflict: {
    final_links: [
      {
        approved_at: "2026-05-18T12:03:00Z",
        final_link_id: 8001,
        local_album: "Maintenance Window",
        local_artist: "Patch Bay",
        local_file_path: "Patch Bay/Loose Cable.flac",
        local_title: "Loose Cable",
        local_track_id: 503,
        resolution_source: "direct",
        source_streaming_track_id: 903,
        streaming_track_id: 903,
      },
      {
        approved_at: "2026-05-18T12:04:00Z",
        final_link_id: 8002,
        local_album: "Live Diagnostics",
        local_artist: "Patch Bay",
        local_file_path: "Patch Bay/Loose Cable Live.flac",
        local_title: "Loose Cable Live",
        local_track_id: 504,
        resolution_source: "direct",
        source_streaming_track_id: 904,
        streaming_track_id: 904,
      },
    ],
    first_group_track_ids: [903],
    local_track_ids: [503, 504],
    second_group_track_ids: [904],
  },
};

const conflictingFinalLinksDifferentSuggestion: StreamingRelationshipSuggestion = {
  ...conflictingEquivalentSuggestion,
  id: 95,
  first_link: {
    ...conflictingEquivalentSuggestion.first_link!,
    final_link_id: 7101,
    local_file_path: "Frame Delay/Resolved Night Runner.flac",
    local_title: "Resolved Night Runner",
    local_track_id: 601,
  },
  second_link: {
    ...conflictingEquivalentSuggestion.second_link!,
    final_link_id: 7102,
    local_file_path: "Frame Delay/Resolved Night Runner Alt.flac",
    local_title: "Resolved Night Runner Alt",
    local_track_id: 602,
  },
  conflict: {
    ...conflictingEquivalentSuggestion.conflict!,
    final_links: [
      {
        ...conflictingEquivalentSuggestion.conflict!.final_links[0],
        final_link_id: 7201,
        local_file_path: "Frame Delay/Conflict Winner A.flac",
        local_title: "Conflict Winner A",
        local_track_id: 701,
      },
      {
        ...conflictingEquivalentSuggestion.conflict!.final_links[1],
        final_link_id: 7202,
        local_file_path: "Frame Delay/Conflict Winner B.flac",
        local_title: "Conflict Winner B",
        local_track_id: 702,
      },
    ],
    local_track_ids: [701, 702],
  },
};

const relationshipSuggestionsResponse: StreamingRelationshipSuggestionsResponse = {
  limit: 50,
  next_cursor: null,
  returned_count: 2,
  suggestions: [relatedSuggestion, equivalentSuggestion],
  total_count: 2,
};

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

function renderStreamingRelationshipsView() {
  return render(<StreamingRelationshipsView />, { wrapper: createWrapper() });
}

type MockRelationshipFetchOptions = {
  acceptHandler?: (suggestionId: string, init?: RequestInit) => Promise<Response> | Response;
  generateHandler?: () => Promise<Response> | Response;
  rejectHandler?: (suggestionId: string) => Promise<Response> | Response;
  response?: StreamingRelationshipSuggestionsResponse;
};

function mockRelationshipFetch({
  acceptHandler,
  generateHandler,
  rejectHandler,
  response = relationshipSuggestionsResponse,
}: MockRelationshipFetchOptions = {}) {
  return createMockApi()
    .get(/^\/api\/streaming\/relationships\/suggestions(?:\?.*)?$/, () => jsonResponse(response))
    .post("/api/streaming/relationships/suggestions/generate", () =>
      generateHandler?.() ?? jsonResponse({ created_count: 2, pruned_count: 0 }),
    )
    .post(/^\/api\/streaming\/relationships\/suggestions\/(\d+)\/accept$/, ({ init, match }) =>
      acceptHandler?.(match![1], init) ??
      jsonResponse({
        accepted_at: "2026-05-18T12:30:00Z",
        detached_final_link_ids: [],
        relationship_id: 81,
        relationship_type:
          typeof init?.body === "string"
            ? JSON.parse(init.body).relationship_type
            : match![1] === "92"
              ? "related"
              : "equivalent",
        status: "accepted",
        suggestion_id: Number(match![1]),
      }),
    )
    .post(/^\/api\/streaming\/relationships\/suggestions\/(\d+)\/reject$/, ({ match }) =>
      rejectHandler?.(match![1]) ??
      jsonResponse({
        rejected_at: "2026-05-18T12:35:00Z",
        status: "rejected",
        suggestion_id: Number(match![1]),
      }),
    )
    .mockFetch();
}

describe("StreamingRelationshipsView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the loading state", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>(() => {}));

    renderStreamingRelationshipsView();

    expect(await screen.findByRole("status")).toHaveTextContent("Loading relationships");
    expect(screen.getByRole("button", { name: "Generate" })).toBeInTheDocument();
  });

  it("renders the error state", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 500,
    } as Response);

    renderStreamingRelationshipsView();

    expect(await screen.findByRole("alert")).toHaveTextContent("Relationships unavailable");
  });

  it("renders the empty state with the manual generate action", async () => {
    mockRelationshipFetch({
      response: { limit: 50, next_cursor: null, returned_count: 0, suggestions: [], total_count: 0 },
    });

    renderStreamingRelationshipsView();

    expect(await screen.findByText("Pending streaming-to-streaming relationship suggestions will appear here after generation.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate" })).toBeInTheDocument();
  });

  it("renders score-sorted streaming track comparisons with relationship cues", async () => {
    const fetchMock = mockRelationshipFetch();

    renderStreamingRelationshipsView();

    const nightRunnerRow = await screen.findByRole("listitem", {
      name: "Suggestion 91: Night Runner to Night Runner",
    });
    const looseCableRow = screen.getByRole("listitem", {
      name: "Suggestion 92: Loose Cable to Loose Cable Live",
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions?limit=50");
    expect(nightRunnerRow.compareDocumentPosition(looseCableRow)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(within(nightRunnerRow).getByText("99%")).toBeInTheDocument();
    expect(within(nightRunnerRow).getByText("Recommended Equivalent")).toBeInTheDocument();
    expect(within(nightRunnerRow).getByRole("button", { name: "Equivalent suggestion 91" })).toBeInTheDocument();
    expect(within(nightRunnerRow).getByRole("button", { name: "Related suggestion 91" })).toBeInTheDocument();
    expect(within(nightRunnerRow).getByRole("button", { name: "Reject suggestion 91" })).toBeInTheDocument();
    expect(within(nightRunnerRow).getAllByText("ISRC")).toHaveLength(3);
    expect(within(nightRunnerRow).getByText("High confidence")).toBeInTheDocument();
    expect(within(nightRunnerRow).getAllByText("GBABC2400001")).toHaveLength(2);
    expect(within(nightRunnerRow).getAllByText("3:34")).toHaveLength(2);
    expect(within(nightRunnerRow).getAllByText("No local link")).toHaveLength(2);
    fireEvent.click(within(nightRunnerRow).getByRole("button", { name: "Inspect suggestion 91" }));
    expect(within(nightRunnerRow).getAllByRole("link", { name: "Open" })).toHaveLength(2);
    fireEvent.click(within(nightRunnerRow).getAllByRole("button", { name: "Preview" })[0]);
    expect(within(nightRunnerRow).getByTitle("YouTube preview for Night Runner").getAttribute("src")).toContain(
      "https://www.youtube.com/embed/ytm%3Afirst-901",
    );
    expect(within(looseCableRow).getByText("73%")).toBeInTheDocument();
    expect(within(looseCableRow).getByText("Recommended Related")).toBeInTheDocument();
    expect(within(looseCableRow).getByRole("button", { name: "Equivalent suggestion 92" })).toBeInTheDocument();
    expect(within(looseCableRow).getByRole("button", { name: "Related suggestion 92" })).toBeInTheDocument();
    expect(within(looseCableRow).getByRole("button", { name: "Reject suggestion 92" })).toBeInTheDocument();
    expect(within(looseCableRow).getByText("fuzzy")).toBeInTheDocument();
    expect(within(looseCableRow).getByText("Medium confidence")).toBeInTheDocument();
    expect(within(looseCableRow).getAllByText("Unavailable")).toHaveLength(4);
  });

  it("renders a unified relationship queue without type filters", async () => {
    mockRelationshipFetch();

    renderStreamingRelationshipsView();

    expect(await screen.findByRole("listitem", { name: "Suggestion 91: Night Runner to Night Runner" })).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: "Suggestion 92: Loose Cable to Loose Cable Live" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Relationship suggestion filter" })).not.toBeInTheDocument();
  });

  it("shows when only the top pending suggestions are returned", async () => {
    mockRelationshipFetch({
      response: {
        ...relationshipSuggestionsResponse,
        total_count: 27933,
      },
    });

    renderStreamingRelationshipsView();

    expect(
      await screen.findByText("Showing 2 of 27933 pending streaming-to-streaming suggestions sorted by confidence."),
    ).toBeInTheDocument();
  });

  it("loads more suggestions with cursor pagination", async () => {
    const thirdSuggestion: StreamingRelationshipSuggestion = {
      ...relatedSuggestion,
      id: 94,
      first_track: {
        ...relatedSuggestion.first_track,
        id: 905,
        provider_track_id: "ytm:first-905",
        title: "Loose Cable Demo",
      },
      second_track: {
        ...relatedSuggestion.second_track,
        id: 906,
        provider_track_id: "ytm:second-906",
        title: "Loose Cable Demo",
      },
    };
    const fetchMock = createMockApi()
      .get(/^\/api\/streaming\/relationships\/suggestions(?:\?.*)?$/, ({ url }) => {
        const params = new URL(url, "http://localhost").searchParams;
        const cursor = params.get("cursor");

        if (cursor === "page-2") {
          return jsonResponse({
            limit: 50,
            next_cursor: null,
            returned_count: 1,
            suggestions: [thirdSuggestion],
            total_count: 75,
          });
        }

        return jsonResponse({
          ...relationshipSuggestionsResponse,
          next_cursor: "page-2",
          total_count: 75,
        });
      })
      .mockFetch();

    renderStreamingRelationshipsView();

    expect(
      await screen.findByText("Showing 2 of 75 pending streaming-to-streaming suggestions sorted by confidence."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions?limit=50&cursor=page-2");
    });
    expect(
      await screen.findByText("Showing 3 of 75 pending streaming-to-streaming suggestions sorted by confidence."),
    ).toBeInTheDocument();
  });

  it("generates suggestions and accepts related suggestions", async () => {
    let relatedAcceptInit: RequestInit | undefined;
    const fetchMock = mockRelationshipFetch({
      acceptHandler: (suggestionId, init) => {
        relatedAcceptInit = init;

        return jsonResponse({
          accepted_at: "2026-05-18T12:30:00Z",
          detached_final_link_ids: [],
          relationship_id: 82,
          relationship_type: suggestionId === "92" ? "related" : "equivalent",
          status: "accepted",
          suggestion_id: Number(suggestionId),
        });
      },
      generateHandler: () => jsonResponse({ created_count: 4, pruned_count: 3 }),
    });

    renderStreamingRelationshipsView();

    expect(await screen.findByRole("listitem", { name: "Suggestion 92: Loose Cable to Loose Cable Live" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions/generate", { method: "POST" });
    });
    expect(await screen.findByText("4 created, 3 pruned.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Related suggestion 92" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions/92/accept", {
        body: JSON.stringify({ relationship_type: "related" }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "POST",
      });
    });
    expect(relatedAcceptInit?.body).toBe(JSON.stringify({ relationship_type: "related" }));
  });

  it("rejects suggestions with optimistic removal", async () => {
    let resolveReject: (response: Response) => void = () => {};
    const rejectPromise = new Promise<Response>((resolve) => {
      resolveReject = resolve;
    });
    const fetchMock = mockRelationshipFetch({
      rejectHandler: () => rejectPromise,
    });

    renderStreamingRelationshipsView();

    const nightRunnerRow = await screen.findByRole("listitem", {
      name: "Suggestion 91: Night Runner to Night Runner",
    });
    fireEvent.click(within(nightRunnerRow).getByRole("button", { name: "Reject suggestion 91" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions/91/reject", { method: "POST" });
      expect(screen.queryByRole("listitem", { name: "Suggestion 91: Night Runner to Night Runner" })).not.toBeInTheDocument();
    });

    resolveReject(
      jsonResponse({
        rejected_at: "2026-05-18T12:35:00Z",
        status: "rejected",
        suggestion_id: 91,
      }),
    );
  });

  it("shows winner selection for equivalent conflicts and submits the chosen equivalent type", async () => {
    let acceptInit: RequestInit | undefined;
    let resolveAccept: (response: Response) => void = () => {};
    const acceptPromise = new Promise<Response>((resolve) => {
      resolveAccept = resolve;
    });
    const fetchMock = mockRelationshipFetch({
      acceptHandler: (_suggestionId, init) => {
        acceptInit = init;

        return acceptPromise;
      },
      response: {
        limit: 50,
        next_cursor: null,
        returned_count: 2,
        suggestions: [conflictingEquivalentSuggestion, relatedSuggestion],
        total_count: 2,
      },
    });

    renderStreamingRelationshipsView();

    const conflictRow = await screen.findByRole("listitem", {
      name: "Suggestion 93: Night Runner to Night Runner",
    });
    const relatedRow = screen.getByRole("listitem", {
      name: "Suggestion 92: Loose Cable to Loose Cable Live",
    });

    expect(within(conflictRow).getByText("Choose winning local link")).toBeInTheDocument();
    expect(within(relatedRow).queryByText("Choose winning local link")).not.toBeInTheDocument();
    expect(within(conflictRow).getByRole("button", { name: "Play Listen to Night Runner.flac" })).toBeInTheDocument();
    expect(within(conflictRow).getByRole("button", { name: "Play Listen to Night Runner Alt.flac" })).toBeInTheDocument();

    const alternateWinner = within(conflictRow).getByRole("radio", { name: /Night Runner Alt\.flac/ });
    fireEvent.click(alternateWinner);
    fireEvent.click(within(conflictRow).getByRole("button", { name: "Equivalent suggestion 93" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions/93/accept", {
        body: JSON.stringify({ relationship_type: "equivalent", winning_final_link_id: 7002 }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "POST",
      });
      expect(screen.queryByRole("listitem", { name: "Suggestion 93: Night Runner to Night Runner" })).not.toBeInTheDocument();
    });
    expect(acceptInit?.body).toBe(JSON.stringify({ relationship_type: "equivalent", winning_final_link_id: 7002 }));

    resolveAccept(
      jsonResponse({
        accepted_at: "2026-05-18T12:30:00Z",
        detached_final_link_ids: [7001],
        relationship_id: 83,
        relationship_type: "equivalent",
        status: "accepted",
        suggestion_id: 93,
      }),
    );
  });

  it("uses conflict final links for inspection audio when they differ from the resolved track links", async () => {
    mockRelationshipFetch({
      response: {
        limit: 50,
        next_cursor: null,
        returned_count: 1,
        suggestions: [conflictingFinalLinksDifferentSuggestion],
        total_count: 1,
      },
    });

    renderStreamingRelationshipsView();

    const conflictRow = await screen.findByRole("listitem", {
      name: "Suggestion 95: Night Runner to Night Runner",
    });

    expect(within(conflictRow).getByRole("button", { name: "Play Listen to Conflict Winner A.flac" })).toBeInTheDocument();
    expect(within(conflictRow).getByRole("button", { name: "Play Listen to Conflict Winner B.flac" })).toBeInTheDocument();

    fireEvent.click(within(conflictRow).getByRole("button", { name: "Inspect suggestion 95" }));

    expect(within(conflictRow).getAllByRole("button", { name: "Play Listen to Conflict Winner A.flac" })).toHaveLength(2);
    expect(within(conflictRow).getAllByRole("button", { name: "Play Listen to Conflict Winner B.flac" })).toHaveLength(2);
    expect(within(conflictRow).queryByRole("button", { name: "Play Listen to Resolved Night Runner.flac" })).not.toBeInTheDocument();
    expect(
      within(conflictRow).queryByRole("button", { name: "Play Listen to Resolved Night Runner Alt.flac" }),
    ).not.toBeInTheDocument();
  });

  it("does not send a conflict winner when the chosen action is related", async () => {
    let acceptInit: RequestInit | undefined;
    const fetchMock = mockRelationshipFetch({
      acceptHandler: (_suggestionId, init) => {
        acceptInit = init;

        return jsonResponse({
          accepted_at: "2026-05-18T12:30:00Z",
          detached_final_link_ids: [],
          relationship_id: 84,
          relationship_type: "related",
          status: "accepted",
          suggestion_id: 94,
        });
      },
      response: {
        limit: 50,
        next_cursor: null,
        returned_count: 1,
        suggestions: [conflictingRelatedSuggestion],
        total_count: 1,
      },
    });

    renderStreamingRelationshipsView();

    const conflictRow = await screen.findByRole("listitem", {
      name: "Suggestion 94: Loose Cable to Loose Cable Live",
    });

    expect(within(conflictRow).getByText("Recommended Related")).toBeInTheDocument();
    expect(within(conflictRow).getByText("Choose winning local link")).toBeInTheDocument();

    fireEvent.click(within(conflictRow).getByRole("button", { name: "Related suggestion 94" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions/94/accept", {
        body: JSON.stringify({ relationship_type: "related" }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "POST",
      });
    });
    expect(acceptInit?.body).toBe(JSON.stringify({ relationship_type: "related" }));
  });

  it("restores rows and shows inline errors when accept or reject mutations fail", async () => {
    mockRelationshipFetch({
      acceptHandler: () => jsonResponse({ detail: "stale" }, { status: 409 }),
      rejectHandler: () => jsonResponse({ detail: "failure" }, { status: 500 }),
    });

    renderStreamingRelationshipsView();

    const equivalentRow = await screen.findByRole("listitem", {
      name: "Suggestion 91: Night Runner to Night Runner",
    });
    fireEvent.click(within(equivalentRow).getByRole("button", { name: "Equivalent suggestion 91" }));

    const restoredEquivalentRow = await screen.findByRole("listitem", {
      name: "Suggestion 91: Night Runner to Night Runner",
    });
    expect(within(restoredEquivalentRow).getByText("Equivalent failed.")).toBeInTheDocument();

    const relatedRow = screen.getByRole("listitem", {
      name: "Suggestion 92: Loose Cable to Loose Cable Live",
    });
    fireEvent.click(within(relatedRow).getByRole("button", { name: "Reject suggestion 92" }));

    const restoredRelatedRow = await screen.findByRole("listitem", {
      name: "Suggestion 92: Loose Cable to Loose Cable Live",
    });
    expect(within(restoredRelatedRow).getByText("Reject failed.")).toBeInTheDocument();
  });
});
