import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { PropsWithChildren, ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import { LocalLibraryView } from "./LocalLibraryView";
import type { LibraryTracksResponse } from "./queries";

const libraryTracksResponse: LibraryTracksResponse = {
  next_cursor: null,
  stats: {
    linked: 2,
    pending: 2,
    total: 5,
    unlinked: 1,
  },
  tracks: [
    {
      album: "Nocturnal",
      artist: "The Midnight",
      duration_ms: 245000,
      file_path: "/library/Synthwave/The Midnight/Nocturnal/Night Shift.mp3",
      file_status: "available",
      final_link_id: 9001,
      id: 1001,
      library_root_rel_path: "Synthwave/The Midnight/Nocturnal/Night Shift.mp3",
      link_status: "linked",
      match_method: "isrc",
      title: "Night Shift",
    },
    {
      album: "Electric Youth",
      artist: "College",
      duration_ms: 250000,
      file_path: "/library/Electronic/College/Electric Youth/A Real Hero.mp3",
      file_status: "available",
      final_link_id: null,
      id: 1002,
      library_root_rel_path: "Electronic/College/Electric Youth/A Real Hero.mp3",
      link_status: "pending",
      match_method: "tag",
      title: "A Real Hero",
    },
    {
      album: "Migration",
      artist: "Bonobo",
      duration_ms: 360000,
      file_path: "/library/Downtempo/Bonobo/Migration/No Reason.flac",
      file_status: "available",
      final_link_id: 9003,
      id: 1003,
      library_root_rel_path: "Downtempo/Bonobo/Migration/No Reason.flac",
      link_status: "linked",
      match_method: "manual",
      title: "No Reason",
    },
    {
      album: null,
      artist: null,
      duration_ms: null,
      file_path: "/library/Piano/Nils Frahm/unknown/import-9a4f.mp3",
      file_status: "beets_failed",
      final_link_id: null,
      id: 1004,
      library_root_rel_path: "Piano/Nils Frahm/unknown/import-9a4f.mp3",
      link_status: "unlinked",
      match_method: null,
      title: "Ambre",
    },
    {
      album: "Immunity",
      artist: "Jon Hopkins",
      duration_ms: 270000,
      file_path: "/library/Electronic/Jon Hopkins/Immunity/Open Eye Signal.mp3",
      file_status: "missing",
      final_link_id: null,
      id: 1005,
      library_root_rel_path: "Electronic/Jon Hopkins/Immunity/Open Eye Signal.mp3",
      link_status: "pending",
      match_method: "manual",
      title: "Open Eye Signal",
    },
  ],
};

function mockLibraryFetch(response: LibraryTracksResponse = libraryTracksResponse) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: async () => response,
  } as Response);
}

function mockLibraryFetchWithRematch({
  libraryResponse = libraryTracksResponse,
  rematchResponse,
}: {
  libraryResponse?: LibraryTracksResponse;
  rematchResponse: Promise<Response> | Response;
}) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);

    if (url.includes("/rematch")) {
      return await rematchResponse;
    }

    return {
      ok: true,
      json: async () => libraryResponse,
    } as Response;
  });
}

function mockPaginatedLibraryFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);

    if (url === "/api/library/tracks") {
      return {
        ok: true,
        json: async () => ({
          next_cursor: 1001,
          stats: libraryTracksResponse.stats,
          tracks: [libraryTracksResponse.tracks[0]],
        }),
      } as Response;
    }

    if (url === "/api/library/tracks?cursor=1001") {
      return {
        ok: true,
        json: async () => ({
          next_cursor: null,
          stats: libraryTracksResponse.stats,
          tracks: libraryTracksResponse.tracks.slice(1),
        }),
      } as Response;
    }

    throw new Error(`Unexpected fetch ${url}`);
  });
}

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

describe("LocalLibraryView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the library filter facets with backend counts", async () => {
    const fetchMock = mockLibraryFetch();

    renderWithQueryClient(<LocalLibraryView />);

    const filters = await screen.findByRole("region", { name: "Library filters" });
    const allButton = await within(filters).findByRole("button", { name: "All 5" });

    expect(within(filters).getByRole("group", { name: "Library link status filters" })).toBeInTheDocument();
    expect(allButton).toHaveAttribute("aria-pressed", "true");
    expect(within(filters).getByRole("button", { name: "Linked 2" })).toHaveAttribute("aria-pressed", "false");
    expect(within(filters).getByRole("button", { name: "Pending 2" })).toHaveAttribute("aria-pressed", "false");
    expect(within(filters).getByRole("button", { name: "Unlinked 1" })).toHaveAttribute("aria-pressed", "false");
    expect(within(filters).getByRole("button", { name: "Reset library filters" })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledWith("/api/library/tracks");
  });

  it("updates and resets library filter selections", async () => {
    mockLibraryFetch();

    renderWithQueryClient(<LocalLibraryView />);

    const filters = await screen.findByRole("region", { name: "Library filters" });
    const pendingButton = await within(filters).findByRole("button", { name: "Pending 2" });

    fireEvent.click(pendingButton);

    expect(within(filters).getByRole("button", { name: "Pending 2" })).toHaveAttribute("aria-pressed", "true");

    const resetButton = within(filters).getByRole("button", { name: "Reset library filters" });
    expect(resetButton).toBeEnabled();
    fireEvent.click(resetButton);

    expect(within(filters).getByRole("button", { name: "All 5" })).toHaveAttribute("aria-pressed", "true");
    expect(resetButton).toBeDisabled();
  });

  it("renders compact local library track rows with backend metadata and link state", async () => {
    mockLibraryFetch();

    renderWithQueryClient(<LocalLibraryView />);

    const trackList = await screen.findByRole("region", { name: "Local library tracks" });

    expect(await within(trackList).findByRole("heading", { name: "Local library track list" })).toBeInTheDocument();
    expect(within(trackList).getByText("Showing 5 of 5 rows")).toBeInTheDocument();
    expect(within(trackList).getAllByRole("status", { name: "Linked track" })).toHaveLength(2);
    expect(within(trackList).getByText("Night Shift")).toBeInTheDocument();
    expect(within(trackList).getByText("The Midnight")).toBeInTheDocument();
    expect(within(trackList).getByText("Nocturnal")).toBeInTheDocument();
    expect(within(trackList).getByText("Synthwave/The Midnight/Nocturnal/Night Shift.mp3")).toBeInTheDocument();
    expect(within(trackList).getAllByText("4:05")).toHaveLength(1);
    expect(within(trackList).getByText("Artist unavailable")).toBeInTheDocument();
    expect(within(trackList).getByText("Album unavailable")).toBeInTheDocument();
  });

  it("loads additional library pages on demand", async () => {
    const fetchMock = mockPaginatedLibraryFetch();

    renderWithQueryClient(<LocalLibraryView />);

    const trackList = await screen.findByRole("region", { name: "Local library tracks" });

    expect(await within(trackList).findByText("Showing 1 of 5 rows")).toBeInTheDocument();
    expect(within(trackList).getByText("Night Shift")).toBeInTheDocument();
    expect(within(trackList).queryByText("A Real Hero")).not.toBeInTheDocument();

    fireEvent.click(within(trackList).getByRole("button", { name: "Load more" }));

    expect(await within(trackList).findByText("A Real Hero")).toBeInTheDocument();
    expect(within(trackList).getByText("Showing 5 of 5 rows")).toBeInTheDocument();
    expect(within(trackList).queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/library/tracks");
    expect(fetchMock).toHaveBeenCalledWith("/api/library/tracks?cursor=1001");
  });

  it("omits per-row detail and re-match actions", async () => {
    mockLibraryFetch();

    renderWithQueryClient(<LocalLibraryView />);

    await screen.findByText("Showing 5 of 5 rows");

    expect(screen.queryByRole("button", { name: "Details" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Re-match" })).not.toBeInTheDocument();
  });

  it("opens the local track drawer when a body row is clicked", async () => {
    mockLibraryFetch();

    renderWithQueryClient(<LocalLibraryView />);

    fireEvent.click(await screen.findByText("Night Shift"));

    expect(await screen.findByRole("dialog", { name: "Track #1001" })).toBeInTheDocument();
  });

  it("filters the rendered library track rows by selected link status", async () => {
    mockLibraryFetch();

    renderWithQueryClient(<LocalLibraryView />);

    const filters = await screen.findByRole("region", { name: "Library filters" });
    const pendingButton = await within(filters).findByRole("button", { name: "Pending 2" });

    fireEvent.click(pendingButton);

    const trackList = screen.getByRole("region", { name: "Local library tracks" });
    expect(within(trackList).getByText("Showing 2 of 5 rows")).toBeInTheDocument();
    expect(within(trackList).getByText("A Real Hero")).toBeInTheDocument();
    expect(within(trackList).getByText("Open Eye Signal")).toBeInTheDocument();
    expect(within(trackList).queryByText("Night Shift")).not.toBeInTheDocument();
  });

  it("enables bulk actions only for compatible selected local rows", async () => {
    mockLibraryFetch();

    renderWithQueryClient(<LocalLibraryView />);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select row 1" }));

    let bulkBar = screen.getByText("1 row selected").closest("div");
    expect(bulkBar).not.toBeNull();
    expect(within(bulkBar as HTMLElement).getByRole("button", { name: "Re-match" })).toBeDisabled();
    expect(within(bulkBar as HTMLElement).getByRole("button", { name: "Unlink" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 2" }));

    bulkBar = screen.getByText("1 row selected").closest("div");
    expect(bulkBar).not.toBeNull();
    expect(within(bulkBar as HTMLElement).getByRole("button", { name: "Re-match" })).toBeEnabled();
    expect(within(bulkBar as HTMLElement).getByRole("button", { name: "Unlink" })).toBeDisabled();
  });

  it("bulk re-matches a selected pending row and renders aggregate feedback", async () => {
    const fetchMock = mockLibraryFetchWithRematch({
      rematchResponse: {
        ok: true,
        json: async () => ({ job_id: "match-job-1002", local_track_id: 1002 }),
      } as Response,
    });

    renderWithQueryClient(<LocalLibraryView />);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select row 2" }));
    const bulkBar = screen.getByText("1 row selected").closest("div") as HTMLElement;

    expect(within(bulkBar).getByRole("button", { name: "Re-match" })).toBeEnabled();
    expect(within(bulkBar).getByRole("button", { name: "Unlink" })).toBeDisabled();

    fireEvent.click(within(bulkBar).getByRole("button", { name: "Re-match" }));

    expect(await screen.findByText("Bulk re-match queued")).toBeInTheDocument();
    expect(screen.getByText("1 row was queued for matching.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/local-tracks/1002/rematch", { method: "POST" });
  });

  it("bulk re-matches selected unlinked rows and renders aggregate feedback", async () => {
    const fetchMock = mockLibraryFetchWithRematch({
      rematchResponse: {
        ok: true,
        json: async () => ({ job_id: "match-job-1004", local_track_id: 1004 }),
      } as Response,
    });

    renderWithQueryClient(<LocalLibraryView />);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select row 4" }));
    const bulkBar = screen.getByText("1 row selected").closest("div") as HTMLElement;
    fireEvent.click(within(bulkBar).getByRole("button", { name: "Re-match" }));

    expect(await screen.findByText("Bulk re-match queued")).toBeInTheDocument();
    expect(screen.getByText("1 row was queued for matching.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/local-tracks/1004/rematch", { method: "POST" });
  });

  it("runs mixed linked and pending selections through only the eligible bulk rows", async () => {
    const fetchMock = mockLibraryFetchWithRematch({
      rematchResponse: {
        ok: true,
        json: async () => ({ job_id: "match-job-1002", local_track_id: 1002 }),
      } as Response,
    });

    renderWithQueryClient(<LocalLibraryView />);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select row 1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 2" }));

    let bulkBar = screen.getByText("2 rows selected").closest("div") as HTMLElement;
    expect(within(bulkBar).getByRole("button", { name: "Re-match" })).toBeEnabled();
    expect(within(bulkBar).getByRole("button", { name: "Unlink" })).toBeEnabled();

    fireEvent.click(within(bulkBar).getByRole("button", { name: "Re-match" }));

    expect(await screen.findByText("Bulk re-match queued")).toBeInTheDocument();

    const rematchCalls = fetchMock.mock.calls.filter(
      ([input, init]) => String(input).includes("/rematch") && init?.method === "POST",
    );
    expect(rematchCalls).toHaveLength(1);
    expect(rematchCalls[0]).toEqual(["/api/local-tracks/1002/rematch", { method: "POST" }]);

    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 2" }));

    bulkBar = screen.getByText("2 rows selected").closest("div") as HTMLElement;
    fireEvent.click(within(bulkBar).getByRole("button", { name: "Unlink" }));

    expect(await screen.findByText("Bulk unlink complete")).toBeInTheDocument();

    const unlinkCalls = fetchMock.mock.calls.filter(
      ([input, init]) => String(input).includes("/api/final-links/") && init?.method === "DELETE",
    );
    expect(unlinkCalls).toHaveLength(1);
    expect(unlinkCalls[0]).toEqual(["/api/final-links/9001", { method: "DELETE" }]);
  });

  it("bulk unlinks selected linked rows and renders aggregate feedback", async () => {
    const fetchMock = mockLibraryFetch();

    renderWithQueryClient(<LocalLibraryView />);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select row 1" }));
    const bulkBar = screen.getByText("1 row selected").closest("div") as HTMLElement;
    fireEvent.click(within(bulkBar).getByRole("button", { name: "Unlink" }));

    expect(await screen.findByText("Bulk unlink complete")).toBeInTheDocument();
    expect(screen.getByText("1 link was removed.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/final-links/9001", { method: "DELETE" });
  });

  it("renders partial failure feedback for bulk unlink errors", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);

      if (url === "/api/final-links/9001" && init?.method === "DELETE") {
        return {
          ok: false,
          status: 500,
          json: async () => ({ detail: "failed" }),
        } as Response;
      }

      return {
        ok: true,
        json: async () => libraryTracksResponse,
      } as Response;
    });

    renderWithQueryClient(<LocalLibraryView />);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select row 1" }));
    const bulkBar = screen.getByText("1 row selected").closest("div") as HTMLElement;
    fireEvent.click(within(bulkBar).getByRole("button", { name: "Unlink" }));

    expect(await screen.findByText("Bulk unlink partially failed")).toBeInTheDocument();
    expect(screen.getByText("0 links were removed and 1 row failed.")).toBeInTheDocument();
  });

  it("clears table selection when library filters change", async () => {
    mockLibraryFetch();

    renderWithQueryClient(<LocalLibraryView />);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select row 1" }));
    expect(screen.getByText("1 row selected")).toBeInTheDocument();

    const filters = screen.getByRole("region", { name: "Library filters" });
    fireEvent.click(within(filters).getByRole("button", { name: "Pending 2" }));

    await waitFor(() => {
      expect(screen.queryByText("1 row selected")).not.toBeInTheDocument();
    });
  });

  it("disables library filters while a refresh is pending", async () => {
    mockLibraryFetch();

    renderWithQueryClient(<LocalLibraryView isPending />);

    expect(await screen.findByText("Library refresh in progress")).toBeInTheDocument();

    const filters = screen.getByRole("region", { name: "Library filters" });
    expect(await within(filters).findByRole("button", { name: "All 5" })).toBeDisabled();
    expect(within(filters).getByRole("button", { name: "Reset library filters" })).toBeDisabled();
  });

  it("renders the library loading, error, and empty states", async () => {
    mockLibraryFetch({
      next_cursor: null,
      stats: {
        linked: 0,
        pending: 0,
        total: 0,
        unlinked: 0,
      },
      tracks: [],
    });

    const { rerender } = renderWithQueryClient(<LocalLibraryView state="loading" />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading library tracks");
    expect(screen.getByRole("region", { name: "Library filters" })).toBeInTheDocument();

    rerender(<LocalLibraryView state="error" />);

    expect(screen.getByRole("alert")).toHaveTextContent("Library unavailable");
    expect(screen.getByRole("region", { name: "Library filters" })).toBeInTheDocument();

    rerender(<LocalLibraryView tracksResponse={{ next_cursor: null, stats: libraryTracksResponse.stats, tracks: [] }} />);

    expect(await screen.findByRole("heading", { name: "No matching library tracks" })).toBeInTheDocument();
    expect(screen.getByText("No tracks match the selected link-status filter.")).toBeInTheDocument();
  });
});
