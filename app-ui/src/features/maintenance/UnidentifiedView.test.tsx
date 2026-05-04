import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps, ReactNode } from "react";

import { UnidentifiedView } from "./UnidentifiedView";
import type { UnidentifiedResponse } from "./queries";

const unidentifiedResponse: UnidentifiedResponse = {
  tracks: [
    {
      failed_at: "2026-05-02T21:44:00Z",
      failure_reason: "Beets could not identify metadata",
      filename: "unknown-import-9a4f.mp3",
      fingerprint: "fp_7d91c2a8e4b0",
      id: 4001,
      local_track_id: null,
      source_path: "ingestion/failed/unknown-import-9a4f.mp3",
    },
    {
      failed_at: "2026-05-02T22:03:00Z",
      failure_reason: "Multiple low-confidence candidates",
      filename: "side-b-live-rip.flac",
      fingerprint: "fp_2c0f88b4aa17",
      id: 4002,
      local_track_id: 1004,
      source_path: "ingestion/failed/side-b-live-rip.flac",
    },
    {
      failed_at: "2026-05-03T09:18:00Z",
      failure_reason: "No Beets match returned",
      filename: "cassette-transfer-03.wav",
      fingerprint: null,
      id: 4003,
      local_track_id: null,
      source_path: "ingestion/failed/cassette-transfer-03.wav",
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

  it("renders Beets-failed tracks with filenames and fingerprint hashes", () => {
    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    const summary = screen.getByLabelText("Unidentified summary");
    expect(within(summary).getByLabelText("Failed imports")).toHaveTextContent("3");
    expect(within(summary).getByLabelText("Fingerprinted")).toHaveTextContent("2");

    const trackList = screen.getByRole("region", { name: "Unidentified tracks" });
    expect(within(trackList).getByRole("heading", { name: "Beets failed track list" })).toBeInTheDocument();
    expect(within(trackList).getByText("3 rows")).toBeInTheDocument();
    expect(within(trackList).getAllByLabelText("Beets failed track")).toHaveLength(3);
    expect(within(trackList).getByText("unknown-import-9a4f.mp3")).toBeInTheDocument();
    expect(within(trackList).getByText("fp_7d91c2a8e4b0")).toBeInTheDocument();
    expect(within(trackList).getByText("ingestion/failed/unknown-import-9a4f.mp3")).toBeInTheDocument();
    expect(within(trackList).getByText("side-b-live-rip.flac")).toBeInTheDocument();
    expect(within(trackList).getByText("fp_2c0f88b4aa17")).toBeInTheDocument();
    expect(within(trackList).getByText("cassette-transfer-03.wav")).toBeInTheDocument();
    expect(within(trackList).getByText("Not captured")).toBeInTheDocument();
  });

  it("posts to the metadata rescue endpoint when a rescue action is clicked", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      json: async () => ({
        beets_id: 91,
        file_path: "Artist/rescue.mp3",
        fingerprint: "fp_7d91c2a8e4b0",
        id: 4001,
        library_root_rel_path: "Artist/rescue.mp3",
      }),
      ok: true,
    } as Response);

    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    fireEvent.click(screen.getByRole("button", { name: "Rescue side-b-live-rip.flac" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/local-tracks/1004/rescue", {
        method: "POST",
      });
    });
    expect(await screen.findByText("Rescue complete")).toBeInTheDocument();
  });

  it("shows a failed rescue status when the endpoint rejects the request", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 409,
    } as Response);

    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    fireEvent.click(screen.getByRole("button", { name: "Rescue side-b-live-rip.flac" }));

    expect(await screen.findByText("Rescue failed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rescue side-b-live-rip.flac" })).toBeEnabled();
  });

  it("disables rescue when the failed ingestion row has no local track id", () => {
    renderUnidentifiedView({ tracksResponse: unidentifiedResponse });

    const unavailableRescue = screen.getByRole("button", { name: "Rescue unknown-import-9a4f.mp3" });
    expect(unavailableRescue).toBeDisabled();
    expect(unavailableRescue).toHaveTextContent("Unavailable");
    expect(screen.getAllByText("No persisted local track available for rescue")).toHaveLength(2);
  });

  it("disables rescue actions while unidentified review is pending", () => {
    renderUnidentifiedView({ isPending: true, tracksResponse: unidentifiedResponse });

    expect(screen.getByText("Unidentified review in progress")).toBeInTheDocument();
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
    expect(screen.getByLabelText("Failed imports")).toHaveTextContent("0");
    expect(screen.getByLabelText("Fingerprinted")).toHaveTextContent("0");
  });
});
