import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { PropsWithChildren, ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import { createMockApi, jsonResponse } from "../../test/mockApi";
import { TrackDetailDrawer } from "./TrackDetailDrawer";
import type { LocalTrackDetail, StreamingTrackDetail } from "./queries";

const localDetail: LocalTrackDetail = {
  album: "Nocturnal",
  artist: "The Midnight",
  beets_album: {
    attributes: [{ key: "catalognum", value: "MIDNIGHT-01" }],
    beets_album_id: 301,
    fields: [
      { key: "album", value: "Nocturnal" },
      { key: "artist_sort", value: "The Midnight" },
      { key: "discogs_albumid", value: "0" },
    ],
  },
  beets_id: 201,
  beets_item: {
    attributes: [{ key: "data_source", value: "MusicBrainz" }],
    beets_id: 201,
    fields: [
      { key: "title", value: "Night Shift" },
      { key: "artist", value: "The Midnight" },
      { key: "album", value: "Nocturnal" },
      { key: "genre", value: "Synthwave" },
      { key: "year", value: "2026" },
      { key: "length", value: "245" },
      { key: "format", value: "MP3" },
      { key: "isrc", value: "USMID260001" },
      { key: "added", value: "2026-05-01T08:00:00Z" },
      { key: "comments", value: "2026" },
    ],
  },
  created_at: "2026-05-01T08:00:00Z",
  duration_ms: 245000,
  failed_ingestion_attempts: [],
  file_path: "/library/Synthwave/The Midnight/Nocturnal/Night Shift.mp3",
  final_link: {
    approved_at: "2026-05-01T09:00:00Z",
    id: 9001,
    streaming_track: {
      album: "Nocturnal",
      artist: "The Midnight",
      duration_ms: 245000,
      id: 501,
      isrc: "USMID260001",
      provider_track_id: "ytm-501",
      title: "Night Shift",
      year: 2026,
    },
    streaming_track_id: 501,
  },
  fingerprint: "fp-night-shift-very-long-value-that-should-not-dominate-the-summary",
  id: 1001,
  library_root_rel_path: "Synthwave/The Midnight/Nocturnal/Night Shift.mp3",
  link_status: "linked",
  pending_suggestions: [],
  title: "Night Shift",
  updated_at: "2026-05-01T09:00:00Z",
};

const unlinkedLocalDetail: LocalTrackDetail = {
  ...localDetail,
  final_link: null,
  id: 1002,
  link_status: "unlinked",
  pending_suggestions: [
    {
      created_at: "2026-05-01T09:05:00Z",
      id: 7101,
      match_method: "tags",
      score: 0.87,
      status: "pending",
      streaming_track: {
        album: "Candidates",
        artist: "Candidate Artist",
        duration_ms: 210000,
        id: 801,
        isrc: null,
        provider_track_id: "ytm-801",
        title: "Candidate Track",
        year: null,
      },
      streaming_track_id: 801,
    },
  ],
  title: "Unlinked Night Shift",
};

const streamingDetail: StreamingTrackDetail = {
  album: "Nocturnal",
  artist: "The Midnight",
  duration_ms: 245000,
  equivalent_tracks: [],
  id: 501,
  isrc: null,
  pending_local_suggestions: [],
  playlist_appearances: [
    {
      account_id: 4,
      playlist_id: 12,
      position: 1,
      provider_playlist_id: "PL12",
      sync_mode: "full",
      title: "Late Night Drive",
    },
  ],
  provider_track_id: "ytm-501",
  relationships: [
    {
      accepted_at: "2026-05-01T10:00:00Z",
      id: 77,
      peer_track: {
        album: "Nocturnal",
        artist: "The Midnight",
        duration_ms: 245000,
        id: 502,
        isrc: null,
        provider_track_id: "ytm-502",
        title: "Night Shift Alternate",
        year: null,
      },
      relationship_type: "related",
    },
  ],
  resolved_local_link: null,
  title: "Night Shift",
  year: null,
};

const streamingLinkedDetail: StreamingTrackDetail = {
  ...streamingDetail,
  id: 601,
  provider_track_id: "ytm-601",
  relationships: [],
  resolved_local_link: {
    approved_at: "2026-05-01T09:00:00Z",
    final_link_id: 9001,
    local_track: {
      album: "Nocturnal",
      artist: "The Midnight",
      file_path: "/library/Synthwave/The Midnight/Nocturnal/Night Shift.mp3",
      id: 1001,
      library_root_rel_path: "Synthwave/The Midnight/Nocturnal/Night Shift.mp3",
      title: "Night Shift",
    },
    local_track_id: 1001,
    resolution_source: "direct",
    source_streaming_track_id: 601,
  },
};

const streamingPendingLocalSuggestionDetail: StreamingTrackDetail = {
  ...streamingDetail,
  id: 602,
  pending_local_suggestions: [
    {
      created_at: "2026-05-01T09:05:00Z",
      id: 7101,
      local_track: {
        album: unlinkedLocalDetail.album,
        artist: unlinkedLocalDetail.artist,
        file_path: unlinkedLocalDetail.file_path,
        id: unlinkedLocalDetail.id,
        library_root_rel_path: unlinkedLocalDetail.library_root_rel_path,
        title: unlinkedLocalDetail.title,
      },
      local_track_id: unlinkedLocalDetail.id,
      match_method: "tags",
      score: 0.87,
      status: "pending",
    },
  ],
  provider_track_id: "ytm-602",
};

function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: {
        retry: false,
      },
      queries: {
        retry: false,
      },
    },
  });

  function Wrapper({ children }: PropsWithChildren) {
    return (
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </MemoryRouter>
    );
  }

  return render(ui, { wrapper: Wrapper });
}

function mockDrawerApi() {
  return createMockApi()
    .get("/api/local-tracks/1001", () => jsonResponse(localDetail))
    .get("/api/local-tracks/1002", () => jsonResponse(unlinkedLocalDetail))
    .get("/api/local-tracks/search?limit=20&q=Night", () =>
      jsonResponse({
        tracks: [
          {
            album: unlinkedLocalDetail.album,
            artist: unlinkedLocalDetail.artist,
            file_path: unlinkedLocalDetail.file_path,
            final_link_id: null,
            id: unlinkedLocalDetail.id,
            library_root_rel_path: unlinkedLocalDetail.library_root_rel_path,
            link_status: unlinkedLocalDetail.link_status,
            title: unlinkedLocalDetail.title,
          },
        ],
      }),
    )
    .get("/api/streaming/tracks/501", () => jsonResponse(streamingDetail))
    .get("/api/streaming/tracks/601", () => jsonResponse(streamingLinkedDetail))
    .get("/api/streaming/tracks/602", () => jsonResponse(streamingPendingLocalSuggestionDetail))
    .get("/api/streaming/tracks/search?limit=20&q=Candidate", () =>
      jsonResponse({
        tracks: [
          {
            album: "Candidates",
            artist: "Candidate Artist",
            duration_ms: 210000,
            final_link_id: null,
            id: 801,
            isrc: null,
            link_status: "unlinked",
            local_track_id: null,
            provider_track_id: "ytm-801",
            title: "Candidate Track",
            year: null,
          },
        ],
      }),
    )
    .post("/api/final-links", () =>
      jsonResponse({
        approved_at: "2026-05-01T10:00:00Z",
        detached_final_link_ids: [],
        final_link_id: 9201,
        local_track_id: 1002,
        replaced_final_link_id: null,
        status: "approved",
        streaming_track_id: 801,
      }),
    )
    .delete("/api/final-links/9001", () => jsonResponse({ final_link_id: 9001, status: "deleted" }))
    .delete("/api/streaming/relationships/77", () =>
      jsonResponse({
        accepted_at: null,
        detached_final_link_ids: [],
        relationship_id: 77,
        relationship_type: "related",
        status: "deleted",
      }),
    )
    .mockFetch();
}

describe("TrackDetailDrawer", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders summary first and keeps fingerprint out of the summary", async () => {
    mockDrawerApi();

    renderWithProviders(<TrackDetailDrawer open target={{ id: 1001, type: "local" }} onClose={vi.fn()} />);

    const dialog = await screen.findByRole("dialog", { name: "Night Shift" });
    const tabs = within(dialog)
      .getAllByRole("button")
      .filter((button) => ["Summary", "Links", "Activity", "Metadata"].includes(button.textContent ?? ""));

    expect(tabs.map((button) => button.textContent)).toEqual(["Summary", "Links", "Activity", "Metadata"]);
    expect(within(dialog).queryByText("Fingerprint")).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/fp-night-shift/)).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("Listen to Night Shift")).toHaveAttribute(
      "src",
      "/api/local-tracks/1001/audio",
    );

    fireEvent.click(within(dialog).getByRole("button", { name: "Metadata" }));

    expect(await within(dialog).findByText("Fingerprint present")).toBeInTheDocument();
    expect(within(dialog).getByText("Core metadata")).toBeInTheDocument();
    expect(within(dialog).queryByText("comments")).not.toBeInTheDocument();
  });

  it("resets back to summary when the detail target changes", async () => {
    mockDrawerApi();

    const { rerender } = renderWithProviders(
      <TrackDetailDrawer open target={{ id: 1001, type: "local" }} onClose={vi.fn()} />,
    );

    const localDialog = await screen.findByRole("dialog", { name: "Night Shift" });
    fireEvent.click(within(localDialog).getByRole("button", { name: "Links" }));
    expect(await within(localDialog).findByRole("button", { name: "Change streaming link" })).toBeInTheDocument();

    rerender(<TrackDetailDrawer open target={{ id: 501, type: "streaming" }} onClose={vi.fn()} />);

    const streamingDialog = await screen.findByRole("dialog", { name: "Night Shift" });
    expect(await within(streamingDialog).findByText("Provider ID")).toBeInTheDocument();
    expect(within(streamingDialog).queryByRole("button", { name: "Add local link" })).not.toBeInTheDocument();
  });

  it("renders local audio in the local links tab", async () => {
    mockDrawerApi();

    renderWithProviders(<TrackDetailDrawer open target={{ id: 1001, type: "local" }} onClose={vi.fn()} />);

    const dialog = await screen.findByRole("dialog", { name: "Night Shift" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Links" }));

    expect(await within(dialog).findByLabelText("Listen to Night Shift")).toHaveAttribute(
      "src",
      "/api/local-tracks/1001/audio",
    );
  });

  it("renders local audio for a streaming track resolved local link", async () => {
    mockDrawerApi();

    renderWithProviders(<TrackDetailDrawer open target={{ id: 601, type: "streaming" }} onClose={vi.fn()} />);

    const dialog = await screen.findByRole("dialog", { name: "Night Shift" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Links" }));

    expect(await within(dialog).findByLabelText("Listen to Night Shift")).toHaveAttribute(
      "src",
      "/api/local-tracks/1001/audio",
    );
  });

  it("renders local audio for pending local suggestion cards", async () => {
    mockDrawerApi();

    renderWithProviders(<TrackDetailDrawer open target={{ id: 602, type: "streaming" }} onClose={vi.fn()} />);

    const dialog = await screen.findByRole("dialog", { name: "Night Shift" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Links" }));

    expect(await within(dialog).findByLabelText("Listen to Unlinked Night Shift")).toHaveAttribute(
      "src",
      "/api/local-tracks/1002/audio",
    );
  });

  it("stages a search result before creating a final link", async () => {
    const fetchMock = mockDrawerApi();

    renderWithProviders(<TrackDetailDrawer open target={{ id: 1002, type: "local" }} onClose={vi.fn()} />);

    const dialog = await screen.findByRole("dialog", { name: "Unlinked Night Shift" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Links" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Add streaming link" }));
    fireEvent.change(within(dialog).getByLabelText("Search streaming tracks"), { target: { value: "Candidate" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Search" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: /Candidate Track/ }));

    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);

    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm streaming link" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/final-links", {
        body: JSON.stringify({
          local_track_id: 1002,
          replace_final_link_id: null,
          streaming_track_id: 801,
        }),
        headers: {
          "Content-Type": "application/json",
        },
        method: "POST",
      });
    });
  });

  it("renders local audio while selecting a local link candidate", async () => {
    mockDrawerApi();

    renderWithProviders(<TrackDetailDrawer open target={{ id: 501, type: "streaming" }} onClose={vi.fn()} />);

    const dialog = await screen.findByRole("dialog", { name: "Night Shift" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Links" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Add local link" }));
    fireEvent.change(within(dialog).getByLabelText("Search local tracks"), { target: { value: "Night" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Search" }));

    expect(await within(dialog).findByLabelText("Listen to Unlinked Night Shift")).toHaveAttribute(
      "src",
      "/api/local-tracks/1002/audio",
    );

    fireEvent.click(within(dialog).getByRole("button", { name: "Select local track" }));

    expect(within(dialog).getAllByLabelText("Listen to Unlinked Night Shift")).toHaveLength(2);
  });

  it("requires confirmation before removing a final link", async () => {
    const fetchMock = mockDrawerApi();

    renderWithProviders(<TrackDetailDrawer open target={{ id: 1001, type: "local" }} onClose={vi.fn()} />);

    const dialog = await screen.findByRole("dialog", { name: "Night Shift" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Links" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Remove link" }));

    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);

    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm remove link" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/final-links/9001", { method: "DELETE" });
    });
  });

  it("requires confirmation before deleting a streaming relationship", async () => {
    const fetchMock = mockDrawerApi();

    renderWithProviders(<TrackDetailDrawer open target={{ id: 501, type: "streaming" }} onClose={vi.fn()} />);

    const dialog = await screen.findByRole("dialog", { name: "Night Shift" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Links" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Delete relationship" }));

    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);

    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm delete relationship" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/relationships/77", { method: "DELETE" });
    });
  });
});
