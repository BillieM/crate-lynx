import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

import { UnidentifiedView } from "./UnidentifiedView";
import type { UnidentifiedResponse } from "./queries";

const unidentifiedResponse: UnidentifiedResponse = {
  tracks: [
    {
      attempt_count: 3,
      can_rematch_local_track: false,
      can_rescue_metadata: false,
      failed_at: "2026-05-02T21:44:00Z",
      failure_reason: "Beets could not identify metadata",
      filename: "unknown-import-9a4f.mp3",
      first_failed_at: "2026-05-01T20:10:00Z",
      id: 4001,
      ignored_at: null,
      local_track_id: null,
      source_mtime_ns: 1_746_217_040_000_000_000,
      source_path: "ingestion/failed/unknown-import-9a4f.mp3",
      source_size: 3210,
    },
    {
      attempt_count: 2,
      can_rematch_local_track: false,
      can_rescue_metadata: true,
      failed_at: "2026-05-02T22:03:00Z",
      failure_reason: "Multiple low-confidence candidates",
      filename: "side-b-live-rip.flac",
      first_failed_at: "2026-05-02T21:58:00Z",
      id: 4002,
      ignored_at: null,
      local_track_id: 1004,
      source_mtime_ns: 1_746_218_080_000_000_000,
      source_path: "ingestion/failed/side-b-live-rip.flac",
      source_size: 9812,
    },
    {
      attempt_count: 1,
      can_rematch_local_track: true,
      can_rescue_metadata: false,
      failed_at: "2026-05-02T22:09:00Z",
      failure_reason: "No confident streaming candidate",
      filename: "unlinked-local-demo.mp3",
      first_failed_at: "2026-05-02T22:07:00Z",
      id: 4004,
      ignored_at: null,
      local_track_id: 1005,
      source_mtime_ns: 1_746_218_540_000_000_000,
      source_path: "ingestion/failed/unlinked-local-demo.mp3",
      source_size: 1101,
    },
    {
      attempt_count: 1,
      can_rematch_local_track: false,
      can_rescue_metadata: false,
      failed_at: "2026-05-03T09:18:00Z",
      failure_reason: "No Beets match returned",
      filename: "cassette-transfer-03.wav",
      first_failed_at: "2026-05-03T09:18:00Z",
      id: 4003,
      ignored_at: "2026-05-03T10:00:00Z",
      local_track_id: null,
      source_mtime_ns: 1_746_258_000_000_000_000,
      source_path: "ingestion/failed/cassette-transfer-03.wav",
      source_size: 4200,
    },
  ],
};

function renderUnidentifiedView(props: ComponentProps<typeof UnidentifiedView> = {}) {
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

  return render(<UnidentifiedView {...props} />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </MemoryRouter>
    ),
  });
}

describe("UnidentifiedView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders active failed sources with attempt totals", () => {
    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    const summary = screen.getByLabelText("Unidentified summary");
    expect(within(summary).getByLabelText("Failed sources")).toHaveTextContent("4");
    expect(within(summary).getByLabelText("Total attempts")).toHaveTextContent("7");
    expect(within(summary).getByLabelText("Active")).toHaveTextContent("3");

    const trackList = screen.getByRole("region", { name: "Unidentified tracks" });
    expect(within(trackList).getByRole("heading", { name: "Beets failed source list" })).toBeInTheDocument();
    expect(within(trackList).getByRole("button", { name: /Active/ })).toHaveTextContent("3");
    expect(within(trackList).getByRole("button", { name: /Ignored/ })).toHaveTextContent("1");
    expect(within(trackList).getByText("3 sources")).toBeInTheDocument();
    expect(within(trackList).getAllByLabelText("Active failed source")).toHaveLength(3);
    expect(within(trackList).getByText("unknown-import-9a4f.mp3")).toBeInTheDocument();
    expect(within(trackList).getByText("ingestion/failed/unknown-import-9a4f.mp3")).toBeInTheDocument();
    expect(within(trackList).getByText("side-b-live-rip.flac")).toBeInTheDocument();
    expect(within(trackList).getByText("unlinked-local-demo.mp3")).toBeInTheDocument();
    expect(within(trackList).getByRole("button", { name: "Retry source unknown-import-9a4f.mp3" })).toBeInTheDocument();
    expect(within(trackList).getByRole("button", { name: "Ignore unknown-import-9a4f.mp3" })).toBeInTheDocument();
    expect(within(trackList).queryByRole("checkbox", { name: "Select all visible rows" })).not.toBeInTheDocument();
    expect(within(trackList).queryByText("cassette-transfer-03.wav")).not.toBeInTheDocument();
  });

  it("switches to ignored failed sources", () => {
    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    fireEvent.click(screen.getByRole("button", { name: /Ignored/ }));

    const trackList = screen.getByRole("region", { name: "Unidentified tracks" });
    expect(within(trackList).getByText("1 source")).toBeInTheDocument();
    expect(within(trackList).getByLabelText("Ignored failed source")).toBeInTheDocument();
    expect(within(trackList).getByText("cassette-transfer-03.wav")).toBeInTheDocument();
    expect(within(trackList).getAllByText("Ignored").length).toBeGreaterThanOrEqual(2);
    expect(within(trackList).getByRole("button", { name: "Restore cassette-transfer-03.wav" })).toBeInTheDocument();
    expect(within(trackList).queryByRole("button", { name: "Retry source cassette-transfer-03.wav" })).not.toBeInTheDocument();
    expect(within(trackList).queryByText("side-b-live-rip.flac")).not.toBeInTheDocument();
  });

  it("posts to retry and ignore endpoints from row actions", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      json: async () => ({
        id: 4001,
        job_id: "ingestion-job-1",
        source_path: "ingestion/failed/unknown-import-9a4f.mp3",
      }),
      ok: true,
    } as Response);

    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    fireEvent.click(screen.getByRole("button", { name: "Retry source unknown-import-9a4f.mp3" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/unidentified/4001/retry", {
        method: "POST",
      });
    });
    expect(await screen.findByText("Retry queued")).toBeInTheDocument();

    fetchMock.mockResolvedValueOnce({
      json: async () => ({
        id: 4001,
        ignored_at: "2026-05-03T11:00:00Z",
        source_path: "ingestion/failed/unknown-import-9a4f.mp3",
      }),
      ok: true,
    } as Response);

    fireEvent.click(screen.getByRole("button", { name: "Ignore unknown-import-9a4f.mp3" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/unidentified/4001/ignore", {
        method: "POST",
      });
    });
    expect(await screen.findByText("Source ignored")).toBeInTheDocument();
  });

  it("posts restore for ignored rows", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      json: async () => ({
        id: 4003,
        ignored_at: null,
        source_path: "ingestion/failed/cassette-transfer-03.wav",
      }),
      ok: true,
    } as Response);

    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    fireEvent.click(screen.getByRole("button", { name: /Ignored/ }));
    fireEvent.click(screen.getByRole("button", { name: "Restore cassette-transfer-03.wav" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/unidentified/4003/restore", {
        method: "POST",
      });
    });
    expect(await screen.findByText("Source restored")).toBeInTheDocument();
  });

  it("opens the local track detail drawer from a row action", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      json: async () => ({
        failed_ingestion_attempts: [],
        file_path: "Artist/side-b-live-rip.flac",
        final_link: {
          approved_at: "2026-05-03T10:00:00Z",
          id: 91,
          streaming_track_id: 7001,
        },
        id: 1004,
        library_root_rel_path: "Artist/side-b-live-rip.flac",
        link_status: "linked",
        pending_suggestions: [],
      }),
      ok: true,
    } as Response);

    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    fireEvent.click(screen.getByRole("button", { name: "Open local track 1004 for side-b-live-rip.flac" }));

    expect(await screen.findByText("Track #1004")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/local-tracks/1004");
    });
  });

  it("posts to the metadata rescue endpoint only when the backend marks the row eligible", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      json: async () => ({
        beets_id: 91,
        file_path: "Artist/rescue.mp3",
        id: 1004,
        library_root_rel_path: "Artist/rescue.mp3",
      }),
      ok: true,
    } as Response);

    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    expect(screen.queryByRole("button", { name: "Rescue unknown-import-9a4f.mp3" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rescue unlinked-local-demo.mp3" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rescue side-b-live-rip.flac" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/local-tracks/1004/rescue", {
        method: "POST",
      });
    });
    expect(await screen.findByText("Rescue complete")).toBeInTheDocument();
  });

  it("posts re-match only when a local track cannot be rescued", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      json: async () => ({
        job_id: "matching-job-1",
        local_track_id: 1005,
      }),
      ok: true,
    } as Response);

    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    expect(screen.queryByRole("button", { name: "Re-match side-b-live-rip.flac" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Re-match unlinked-local-demo.mp3" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/local-tracks/1005/rematch", {
        method: "POST",
      });
    });
    expect(await screen.findByText("Re-match queued")).toBeInTheDocument();
  });

  it("shows failed row action status when endpoints reject the request", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 409,
    } as Response);

    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    fireEvent.click(screen.getByRole("button", { name: "Retry source unknown-import-9a4f.mp3" }));

    expect(await screen.findByText("Retry failed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry source unknown-import-9a4f.mp3" })).toBeEnabled();
  });

  it("does not render row selection controls or bulk actions", () => {
    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    expect(screen.queryByRole("checkbox", { name: "Select all visible rows" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Select row 1" })).not.toBeInTheDocument();
    expect(screen.queryByText(/rows selected/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Bulk retry/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Bulk ignore/i)).not.toBeInTheDocument();
  });

  it("refreshes stale retry rows when the source file was already cleared", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 404,
    } as Response);

    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    fireEvent.click(screen.getByRole("button", { name: "Retry source unknown-import-9a4f.mp3" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/unidentified/4001/retry", {
        method: "POST",
      });
    });
    expect(await screen.findByText("Source file missing; row refreshed")).toBeInTheDocument();
  });

  it("disables actions while unidentified review is pending", () => {
    renderUnidentifiedView({ isPending: true, tracksResponse: unidentifiedResponse });

    expect(screen.getByText("Unidentified review in progress")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry source unknown-import-9a4f.mp3" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ignore unknown-import-9a4f.mp3" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Open local track 1004 for side-b-live-rip.flac" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Re-match unlinked-local-demo.mp3" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Rescue side-b-live-rip.flac" })).toBeDisabled();
  });

  it("renders unidentified loading, error, and empty states", () => {
    const { rerender } = renderUnidentifiedView({ state: "loading" });

    expect(screen.getByRole("status")).toHaveTextContent("Loading unidentified tracks");
    expect(screen.queryByText("unknown-import-9a4f.mp3")).not.toBeInTheDocument();

    rerender(<UnidentifiedView state="error" />);

    expect(screen.getByRole("alert")).toHaveTextContent("Unidentified queue unavailable");

    rerender(<UnidentifiedView tracksResponse={{ tracks: [] }} />);

    expect(screen.getByRole("heading", { name: "No unidentified tracks" })).toBeInTheDocument();
    expect(screen.getByLabelText("Failed sources")).toHaveTextContent("0");
    expect(screen.getByLabelText("Total attempts")).toHaveTextContent("0");
  });
});
