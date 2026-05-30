import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { PropsWithChildren, ReactElement } from "react";

import { LocalDedupeView } from "./LocalDedupeView";
import type { LocalDedupeQueueResponse } from "./queries";

const dedupeQueueResponse: LocalDedupeQueueResponse = {
  groups: [
    {
      group_key: "fingerprint_similar:abc123",
      match_score: 0.87,
      source: "fingerprint_similar",
      tracks: [
        {
          album: "Signals",
          artist: "Local Artist",
          beets_id: 101,
          bitdepth: 16,
          bitrate: 320000,
          duration_ms: 245000,
          file_path: "Local Artist/Signals/Memory Lane.mp3",
          final_link_id: 901,
          fingerprint: "fingerprint-left",
          format: "MP3",
          id: 501,
          isrc: "GBABC2400001",
          library_root_rel_path: "Local Artist/Signals/Memory Lane.mp3",
          link_status: "linked",
          samplerate: 44100,
          title: "Memory Lane",
        },
        {
          album: "Signals",
          artist: "Local Artist",
          beets_id: 102,
          bitdepth: 24,
          bitrate: 900000,
          duration_ms: 245500,
          file_path: "Local Artist/Signals/Memory Lane.flac",
          final_link_id: null,
          fingerprint: "fingerprint-right",
          format: "FLAC",
          id: 502,
          isrc: "GBABC2400001",
          library_root_rel_path: "Local Artist/Signals/Memory Lane.flac",
          link_status: "unlinked",
          samplerate: 48000,
          title: "Memory Lane",
        },
      ],
    },
  ],
  total_count: 1,
};

function renderWithQueryClient(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }

  return render(ui, { wrapper: Wrapper });
}

describe("LocalDedupeView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders duplicate groups with confidence labels and side-by-side inspection", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => dedupeQueueResponse,
    } as Response);

    renderWithQueryClient(<LocalDedupeView />);

    const groups = await screen.findByRole("region", { name: "Duplicate groups" });
    expect(within(groups).getByText("Memory Lane")).toBeInTheDocument();
    expect(within(groups).getByText("Similar fingerprint")).toBeInTheDocument();
    expect(within(groups).getByText("87%")).toBeInTheDocument();

    const detail = screen.getByRole("region", { name: "Duplicate group detail" });
    expect(within(detail).getByText("Keep selected #501")).toBeInTheDocument();
    expect(within(detail).getByText("FLAC")).toBeInTheDocument();
    expect(within(detail).getByText("48000 Hz")).toBeInTheDocument();
    expect(within(detail).getByText("Local Artist/Signals/Memory Lane.flac")).toBeInTheDocument();
  });

  it("resolves the selected keeper and reports quarantined files", async () => {
    let queueResponse = dedupeQueueResponse;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      if (url === "/api/local-dedupe/queue") {
        return {
          ok: true,
          json: async () => queueResponse,
        } as Response;
      }
      if (url === "/api/local-dedupe/groups/fingerprint_similar%3Aabc123/resolve") {
        expect(JSON.parse(String(init?.body))).toEqual({ keeper_local_track_id: 502 });
        queueResponse = { groups: [], total_count: 0 };
        return {
          ok: true,
          json: async () => ({
            affected_playlist_ids: [12],
            decision: {
              action: "resolved",
              created_at: "2026-05-30T10:00:00Z",
              group_key: "fingerprint_similar:abc123",
              id: 1,
              keeper_local_track_id: 502,
              match_score: 0.87,
              quarantine_paths: ["/nas/cratelynx/dedupe-quarantine/local-501.mp3"],
              quarantined_local_track_ids: [501],
              source: "fingerprint_similar",
              track_ids: [501, 502],
            },
          }),
        } as Response;
      }
      throw new Error(`Unexpected fetch request: ${String(url)}`);
    });

    renderWithQueryClient(<LocalDedupeView />);

    const detail = await screen.findByRole("region", { name: "Duplicate group detail" });
    fireEvent.click(within(detail).getAllByRole("button", { name: "Select as keeper" })[0]);
    fireEvent.click(within(detail).getByRole("button", { name: "Keep selected #502" }));

    await waitFor(() => {
      expect(screen.getByText("Duplicate group resolved")).toBeInTheDocument();
    });
    expect(screen.getByText("1 duplicate file was moved to quarantine.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/local-dedupe/groups/fingerprint_similar%3Aabc123/resolve", {
      body: JSON.stringify({ keeper_local_track_id: 502 }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    });
  });

  it("dismisses false positives from the queue", async () => {
    let queueResponse = dedupeQueueResponse;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (url === "/api/local-dedupe/queue") {
        return {
          ok: true,
          json: async () => queueResponse,
        } as Response;
      }
      if (url === "/api/local-dedupe/groups/fingerprint_similar%3Aabc123/dismiss") {
        queueResponse = { groups: [], total_count: 0 };
        return {
          ok: true,
          json: async () => ({
            action: "dismissed",
            created_at: "2026-05-30T10:00:00Z",
            group_key: "fingerprint_similar:abc123",
            id: 2,
            keeper_local_track_id: null,
            match_score: 0.87,
            quarantine_paths: [],
            quarantined_local_track_ids: [],
            source: "fingerprint_similar",
            track_ids: [501, 502],
          }),
        } as Response;
      }
      throw new Error(`Unexpected fetch request: ${String(url)}`);
    });

    renderWithQueryClient(<LocalDedupeView />);

    const detail = await screen.findByRole("region", { name: "Duplicate group detail" });
    fireEvent.click(within(detail).getByRole("button", { name: "Dismiss" }));

    await waitFor(() => {
      expect(screen.getByText("Group dismissed")).toBeInTheDocument();
    });
    expect(screen.getByText("The duplicate group was removed from the review queue.")).toBeInTheDocument();
  });

  it("renders a queue loading error state", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 500,
    } as Response);

    renderWithQueryClient(<LocalDedupeView />);

    expect(await screen.findByText("Dedupe unavailable")).toBeInTheDocument();
    expect(screen.getByText("The duplicate queue could not be loaded.")).toBeInTheDocument();
  });

  it("reports resolve errors without removing the group", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (url === "/api/local-dedupe/queue") {
        return {
          ok: true,
          json: async () => dedupeQueueResponse,
        } as Response;
      }
      if (url === "/api/local-dedupe/groups/fingerprint_similar%3Aabc123/resolve") {
        return {
          ok: false,
          status: 409,
        } as Response;
      }
      throw new Error(`Unexpected fetch request: ${String(url)}`);
    });

    renderWithQueryClient(<LocalDedupeView />);

    const detail = await screen.findByRole("region", { name: "Duplicate group detail" });
    fireEvent.click(within(detail).getByRole("button", { name: "Keep selected #501" }));

    await waitFor(() => {
      expect(screen.getByText("Resolve failed")).toBeInTheDocument();
    });
    expect(screen.getByText("The selected duplicate group could not be quarantined.")).toBeInTheDocument();
    expect(within(detail).getByText(/Memory Lane\.flac/)).toBeInTheDocument();
  });
});
