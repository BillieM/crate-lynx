import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps, ReactNode } from "react";

import { UnidentifiedView } from "./UnidentifiedView";
import type { UnidentifiedResponse } from "./queries";

const unidentifiedResponse: UnidentifiedResponse = {
  tracks: [
    {
      attempt_count: 3,
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
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
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
    expect(within(summary).getByLabelText("Failed sources")).toHaveTextContent("3");
    expect(within(summary).getByLabelText("Total attempts")).toHaveTextContent("6");
    expect(within(summary).getByLabelText("Active")).toHaveTextContent("2");

    const trackList = screen.getByRole("region", { name: "Unidentified tracks" });
    expect(within(trackList).getByRole("heading", { name: "Beets failed source list" })).toBeInTheDocument();
    expect(within(trackList).getByRole("button", { name: /Active/ })).toHaveTextContent("2");
    expect(within(trackList).getByRole("button", { name: /Ignored/ })).toHaveTextContent("1");
    expect(within(trackList).getByText("2 sources")).toBeInTheDocument();
    expect(within(trackList).getAllByLabelText("Active failed source")).toHaveLength(2);
    expect(within(trackList).getByText("unknown-import-9a4f.mp3")).toBeInTheDocument();
    expect(within(trackList).getByText("ingestion/failed/unknown-import-9a4f.mp3")).toBeInTheDocument();
    expect(within(trackList).getByText("side-b-live-rip.flac")).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: "Retry unknown-import-9a4f.mp3" }));

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

  it("posts to the metadata rescue endpoint only for rows with local tracks", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "Rescue side-b-live-rip.flac" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/local-tracks/1004/rescue", {
        method: "POST",
      });
    });
    expect(await screen.findByText("Rescue complete")).toBeInTheDocument();
  });

  it("shows failed row action status when endpoints reject the request", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 409,
    } as Response);

    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    fireEvent.click(screen.getByRole("button", { name: "Retry unknown-import-9a4f.mp3" }));

    expect(await screen.findByText("Retry failed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry unknown-import-9a4f.mp3" })).toBeEnabled();
  });

  it("bulk retries selected visible rows", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      json: async () => ({
        id: 4001,
        job_id: "ingestion-job-1",
        source_path: "ingestion/failed/unknown-import-9a4f.mp3",
      }),
      ok: true,
    } as Response);

    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    fireEvent.click(screen.getByRole("checkbox", { name: "Select all visible rows" }));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/unidentified/4001/retry", {
        method: "POST",
      });
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/unidentified/4002/retry", {
      method: "POST",
    });
    expect(await screen.findByText("Bulk retry queued")).toBeInTheDocument();
    expect(screen.getByText("2 sources were queued for retry.")).toBeInTheDocument();
  });

  it("bulk ignores selected active rows", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      json: async () => ({
        id: 4001,
        ignored_at: "2026-05-03T11:00:00Z",
        source_path: "ingestion/failed/unknown-import-9a4f.mp3",
      }),
      ok: true,
    } as Response);

    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Ignore" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/unidentified/4001/ignore", {
        method: "POST",
      });
    });
    expect(await screen.findByText("Bulk ignore complete")).toBeInTheDocument();
    expect(screen.getByText("1 source was ignored.")).toBeInTheDocument();
  });

  it("disables actions while unidentified review is pending", () => {
    renderUnidentifiedView({ isPending: true, tracksResponse: unidentifiedResponse });

    expect(screen.getByText("Unidentified review in progress")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry unknown-import-9a4f.mp3" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ignore unknown-import-9a4f.mp3" })).toBeDisabled();
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
