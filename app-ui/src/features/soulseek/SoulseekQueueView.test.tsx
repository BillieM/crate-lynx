import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { PropsWithChildren, ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import { SoulseekQueueView } from "./SoulseekQueueView";
import type { SoulseekQueueResponse } from "./queries";

const queueResponse: SoulseekQueueResponse = {
  filter: "all",
  items: [
    {
      acquisition: {
        candidate_count: 1,
        completed_at: null,
        completed_source_path: null,
        created_at: "2026-05-25T10:00:00Z",
        destination: null,
        enqueue_job_id: null,
        error_detail: null,
        failed_at: null,
        fallback_search_text: null,
        final_link_id: null,
        id: "acq-1",
        ingested_at: null,
        job_id: "search-job-1",
        link_error_detail: null,
        linked_at: null,
        local_track_id: null,
        proposal_available_at: null,
        queued_at: null,
        refresh_job_id: null,
        searched_at: "2026-05-25T10:00:00Z",
        search_text: "Jon Hopkins Open Eye Signal",
        selected_candidate_id: null,
        slskd_batch_id: null,
        slskd_completed_event_id: null,
        slskd_fallback_search_id: null,
        slskd_search_id: "search-1",
        slskd_transfer_id: null,
        status: "candidates_found",
        streaming_track_id: 5001,
        updated_at: "2026-05-25T10:00:00Z",
      },
      candidates: [
        {
          acquisition_id: "acq-1",
          bit_depth: 16,
          bit_rate: null,
          created_at: "2026-05-25T10:00:00Z",
          duration_seconds: 270,
          extension: ".flac",
          filename: "Jon Hopkins - Open Eye Signal.flac",
          has_free_upload_slot: true,
          id: "candidate-1",
          is_variable_bit_rate: null,
          queue_length: 0,
          sample_rate: 44100,
          score: 0.91,
          size: 30000000,
          slskd_search_id: "search-1",
          upload_speed: 500000,
          username: "peer",
        },
      ],
      playlist_count: 1,
      playlist_ids: [11],
      playlist_titles: ["Late Night Drive"],
      selected_candidate: null,
      streaming_track: {
        album: "Immunity",
        artist: "Jon Hopkins",
        duration_ms: 270000,
        id: 5001,
        title: "Open Eye Signal",
      },
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
    return (
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </MemoryRouter>
    );
  }

  return render(ui, { wrapper: Wrapper });
}

describe("SoulseekQueueView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows needs search, review, and active filter counts with clear labels", async () => {
    const activeItem = {
      ...queueResponse.items[0],
      acquisition: {
        ...queueResponse.items[0].acquisition!,
        id: "acq-2",
        selected_candidate_id: null,
        status: "searching",
        streaming_track_id: 5002,
      },
      candidates: [],
      selected_candidate: null,
      streaming_track: {
        ...queueResponse.items[0].streaming_track,
        id: 5002,
        title: "Searching Track",
      },
    };
    const needsSearchItem = {
      ...queueResponse.items[0],
      acquisition: null,
      candidates: [],
      selected_candidate: null,
      streaming_track: {
        ...queueResponse.items[0].streaming_track,
        id: 5003,
        title: "Needs Search Track",
      },
    };
    const response: SoulseekQueueResponse = {
      filter: "all",
      items: [queueResponse.items[0], activeItem, needsSearchItem],
      total_count: 3,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (url === "/api/soulseek/queue") {
        return {
          ok: true,
          json: async () => response,
        } as Response;
      }
      if (url === "/api/soulseek/acquisitions/acq-1") {
        return {
          ok: true,
          json: async () => queueResponse.items[0],
        } as Response;
      }
      if (url === "/api/soulseek/acquisitions/acq-2") {
        return {
          ok: true,
          json: async () => activeItem,
        } as Response;
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });

    renderWithQueryClient(<SoulseekQueueView />);

    const filters = await screen.findByRole("group", { name: "Soulseek queue filters" });
    await waitFor(() => {
      expect(filters).toHaveTextContent("Needs search1");
      expect(filters).toHaveTextContent("Review1");
      expect(filters).toHaveTextContent("Active1");
    });
    expect(filters).not.toHaveTextContent("Downloading");

    fireEvent.click(within(filters).getByRole("button", { name: /Active/ }));

    const queueItems = await screen.findByRole("region", { name: "Soulseek queue items" });
    expect(within(queueItems).getByText("Searching Track")).toBeInTheDocument();
    expect(within(queueItems).getByText("Searching")).toBeInTheDocument();
  });

  it("locks candidate approval controls after a candidate is selected", async () => {
    const selectedCandidate = queueResponse.items[0].candidates[0];
    const alternateCandidate = {
      ...selectedCandidate,
      filename: "Alternate - Open Eye Signal.flac",
      id: "candidate-2",
      score: 0.82,
    };
    const lockedItem = {
      ...queueResponse.items[0],
      acquisition: {
        ...queueResponse.items[0].acquisition!,
        selected_candidate_id: "candidate-1",
        slskd_batch_id: "transfer:transfer-1",
        slskd_transfer_id: "transfer-1",
      },
      candidates: [selectedCandidate, alternateCandidate],
      selected_candidate: selectedCandidate,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (url === "/api/soulseek/queue") {
        return {
          ok: true,
          json: async () => ({ ...queueResponse, items: [lockedItem] }),
        } as Response;
      }
      if (url === "/api/soulseek/acquisitions/acq-1") {
        return {
          ok: true,
          json: async () => lockedItem,
        } as Response;
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });

    renderWithQueryClient(<SoulseekQueueView />);

    expect(await screen.findByText("Approved candidate")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve Soulseek download Jon Hopkins - Open Eye Signal.flac" })).toBeDisabled();
    const alternateButton = screen.getByRole("button", { name: "Approve Soulseek download Alternate - Open Eye Signal.flac" });
    expect(alternateButton).toBeDisabled();
    expect(alternateButton).toHaveTextContent("Approval locked");
  });

  it("defaults to needs-search rows and queues row and bulk Soulseek searches", async () => {
    const firstMissingItem = {
      ...queueResponse.items[0],
      acquisition: null,
      candidates: [],
      playlist_ids: [11],
      playlist_titles: ["Late Night Drive"],
      selected_candidate: null,
      streaming_track: {
        ...queueResponse.items[0].streaming_track,
        id: 5003,
        title: "Needs Search Track",
      },
    };
    const secondMissingItem = {
      ...firstMissingItem,
      playlist_ids: [12],
      playlist_titles: ["Focus Queue"],
      streaming_track: {
        ...firstMissingItem.streaming_track,
        id: 5004,
        title: "Second Missing Track",
      },
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      if (url === "/api/soulseek/queue") {
        return {
          ok: true,
          json: async () => ({ filter: "all", items: [firstMissingItem, secondMissingItem], total_count: 2 }),
        } as Response;
      }
      if (url === "/api/soulseek/missing-tracks/5003/search" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            acquisition: { ...queueResponse.items[0].acquisition, id: "acq-3", status: "searching" },
            job_id: "search-job-3",
          }),
        } as Response;
      }
      if (url === "/api/soulseek/missing-tracks/search-selected" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            jobs: [
              { acquisition: { ...queueResponse.items[0].acquisition, id: "acq-3" }, job_id: "search-job-3", streaming_track_id: 5003 },
              { acquisition: { ...queueResponse.items[0].acquisition, id: "acq-4" }, job_id: "search-job-4", streaming_track_id: 5004 },
            ],
          }),
        } as Response;
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });

    renderWithQueryClient(<SoulseekQueueView />);

    const filters = await screen.findByRole("group", { name: "Soulseek queue filters" });
    await waitFor(() => {
      expect(within(filters).getByRole("button", { name: /Needs search/ })).toHaveAttribute("aria-pressed", "true");
    });
    fireEvent.click(await screen.findByRole("button", { name: "Search Soulseek for Needs Search Track" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/soulseek/missing-tracks/5003/search", { method: "POST" });
    });

    fireEvent.click(screen.getByRole("checkbox", { name: "Select Needs Search Track" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Second Missing Track" }));
    fireEvent.click(screen.getByRole("button", { name: "Search selected" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/soulseek/missing-tracks/search-selected", {
        body: JSON.stringify({ streaming_track_ids: [5003, 5004] }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      });
    });
    expect(await screen.findByText("Bulk search queued")).toBeInTheDocument();
  });

  it("syncs affected playlists for selected needs-search rows", async () => {
    const missingItem = {
      ...queueResponse.items[0],
      acquisition: null,
      candidates: [],
      playlist_ids: [11, 12],
      playlist_titles: ["Late Night Drive", "Focus Queue"],
      selected_candidate: null,
      streaming_track: {
        ...queueResponse.items[0].streaming_track,
        id: 5003,
        title: "Needs Search Track",
      },
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      if (url === "/api/soulseek/queue") {
        return {
          ok: true,
          json: async () => ({ filter: "all", items: [missingItem], total_count: 1 }),
        } as Response;
      }
      if (typeof url === "string" && /^\/api\/streaming\/playlists\/\d+\/sync$/.test(url) && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({ job_id: "sync-job", playlist_id: Number(url.match(/\d+/)?.[0] ?? 0) }),
        } as Response;
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });

    renderWithQueryClient(<SoulseekQueueView />);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select Needs Search Track" }));
    fireEvent.click(screen.getByRole("button", { name: "Sync affected playlists" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists/11/sync", { method: "POST" });
      expect(fetchMock).toHaveBeenCalledWith("/api/streaming/playlists/12/sync", { method: "POST" });
    });
    expect(await screen.findByText("Playlist sync queued")).toBeInTheDocument();
  });

  it("reviews candidates and approves a Soulseek download", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      if (url === "/api/soulseek/queue") {
        return {
          ok: true,
          json: async () => queueResponse,
        } as Response;
      }
      if (url === "/api/soulseek/acquisitions/acq-1") {
        return {
          ok: true,
          json: async () => queueResponse.items[0],
        } as Response;
      }
      if (url === "/api/soulseek/candidates/candidate-1/approve-download" && init?.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            acquisition: {
              ...queueResponse.items[0].acquisition,
              enqueue_job_id: "enqueue-job-1",
              selected_candidate_id: "candidate-1",
              status: "queued",
            },
            job_id: "enqueue-job-1",
          }),
        } as Response;
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });

    renderWithQueryClient(<SoulseekQueueView />);

    expect(await screen.findByRole("heading", { name: "Soulseek acquisition queue" })).toBeInTheDocument();
    const queueItems = await screen.findByRole("region", { name: "Soulseek queue items" });
    expect(within(queueItems).getByText("Open Eye Signal")).toBeInTheDocument();
    expect(await screen.findByText("Jon Hopkins - Open Eye Signal.flac")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Approve Soulseek download Jon Hopkins - Open Eye Signal.flac" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/soulseek/candidates/candidate-1/approve-download", { method: "POST" });
    });
    expect(await screen.findByText("Download approved")).toBeInTheDocument();
  });
});
