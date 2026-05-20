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

const relationshipSuggestionsResponse: StreamingRelationshipSuggestionsResponse = {
  suggestions: [relatedSuggestion, equivalentSuggestion],
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
    .get("/api/streaming/relationships/suggestions", () => jsonResponse(response))
    .post("/api/streaming/relationships/suggestions/generate", () =>
      generateHandler?.() ?? jsonResponse({ created_count: 2 }),
    )
    .post(/^\/api\/streaming\/relationships\/suggestions\/(\d+)\/accept$/, ({ init, match }) =>
      acceptHandler?.(match![1], init) ??
      jsonResponse({
        accepted_at: "2026-05-18T12:30:00Z",
        detached_final_link_ids: [],
        relationship_id: 81,
        relationship_type: match![1] === "92" ? "related" : "equivalent",
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
    mockRelationshipFetch({ response: { suggestions: [] } });

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

    expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions");
    expect(nightRunnerRow.compareDocumentPosition(looseCableRow)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(within(nightRunnerRow).getByText("99%")).toBeInTheDocument();
    expect(within(nightRunnerRow).getAllByText("Equivalent")).toHaveLength(2);
    expect(within(nightRunnerRow).getAllByText("ISRC")).toHaveLength(3);
    expect(within(nightRunnerRow).getByText("High confidence")).toBeInTheDocument();
    expect(within(nightRunnerRow).getAllByText("GBABC2400001")).toHaveLength(2);
    expect(within(nightRunnerRow).getAllByText("3:34")).toHaveLength(2);
    expect(within(nightRunnerRow).getAllByText("No local link")).toHaveLength(2);
    expect(within(looseCableRow).getByText("73%")).toBeInTheDocument();
    expect(within(looseCableRow).getAllByText("Related")).toHaveLength(2);
    expect(within(looseCableRow).getByText("fuzzy")).toBeInTheDocument();
    expect(within(looseCableRow).getByText("Medium confidence")).toBeInTheDocument();
    expect(within(looseCableRow).getAllByText("Unavailable")).toHaveLength(4);
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
      generateHandler: () => jsonResponse({ created_count: 4 }),
    });

    renderStreamingRelationshipsView();

    expect(await screen.findByRole("listitem", { name: "Suggestion 92: Loose Cable to Loose Cable Live" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions/generate", { method: "POST" });
    });
    expect(await screen.findByText("4 created.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Related suggestion 92" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions/92/accept", { method: "POST" });
    });
    expect(relatedAcceptInit?.body).toBeUndefined();
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

  it("shows winner selection only for equivalent conflicts and submits the chosen link", async () => {
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
      response: { suggestions: [conflictingEquivalentSuggestion, relatedSuggestion] },
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

    const alternateWinner = within(conflictRow).getByRole("radio", { name: /Night Runner Alt\.flac/ });
    fireEvent.click(alternateWinner);
    fireEvent.click(within(conflictRow).getByRole("button", { name: "Equivalent suggestion 93" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/suggestions/93/accept", {
        body: JSON.stringify({ winning_final_link_id: 7002 }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "POST",
      });
      expect(screen.queryByRole("listitem", { name: "Suggestion 93: Night Runner to Night Runner" })).not.toBeInTheDocument();
    });
    expect(acceptInit?.body).toBe(JSON.stringify({ winning_final_link_id: 7002 }));

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
