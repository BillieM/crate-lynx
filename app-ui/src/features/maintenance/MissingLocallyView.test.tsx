import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import type { PropsWithChildren, ReactElement } from "react";

import { MissingLocallyView } from "./MissingLocallyView";
import type { MissingLocallyResponse } from "./queries";

const missingLocallyResponse: MissingLocallyResponse = {
  tracks: [
    {
      album: "Immunity",
      artist: "Jon Hopkins",
      duration_ms: 270000,
      id: 5001,
      playlist_count: 1,
      playlist_ids: [11],
      playlist_titles: ["Late Night Drive"],
      provider_track_id: "ytm:VLPL_missing_018",
      title: "Open Eye Signal",
    },
    {
      album: "Migration",
      artist: "Bonobo feat. Nick Murphy",
      duration_ms: 360000,
      id: 5002,
      playlist_count: 2,
      playlist_ids: [12, 11],
      playlist_titles: ["Focus Queue", "Late Night Drive"],
      provider_track_id: "ytm:VLPL_missing_024",
      title: "No Reason",
    },
    {
      album: null,
      artist: "Kelly Lee Owens",
      duration_ms: 221000,
      id: 5003,
      playlist_count: 1,
      playlist_ids: [13],
      playlist_titles: ["New Imports"],
      provider_track_id: "ytm:VLPL_missing_031",
      title: "Melt!",
    },
  ],
};

function mockMissingLocallyFetch(response: MissingLocallyResponse = missingLocallyResponse) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: async () => response,
  } as Response);
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
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }

  return render(ui, { wrapper: Wrapper });
}

describe("MissingLocallyView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders summary counts for streaming tracks without local matches", async () => {
    const fetchMock = mockMissingLocallyFetch();

    renderWithQueryClient(<MissingLocallyView />);

    const summary = screen.getByLabelText("Missing locally summary");

    await waitFor(() => {
      expect(within(summary).getByLabelText("Missing tracks")).toHaveTextContent("3");
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/maintenance/missing-locally");
    expect(within(summary).getByLabelText("Missing tracks")).toHaveTextContent("3");
    expect(within(summary).getByLabelText("Affected playlists")).toHaveTextContent("3");
    expect(within(summary).queryByLabelText("High priority")).not.toBeInTheDocument();
  });

  it("lists streaming tracks with aggregated playlist usage and match gap details", async () => {
    mockMissingLocallyFetch();

    renderWithQueryClient(<MissingLocallyView />);

    const trackList = screen.getByRole("region", { name: "Missing local tracks" });

    expect(await within(trackList).findByRole("heading", { name: "Streaming tracks without local matches" })).toBeInTheDocument();
    expect(within(trackList).getByText("3 rows")).toBeInTheDocument();
    expect(within(trackList).getAllByRole("status", { name: "Streaming track missing local match" })).toHaveLength(3);
    expect(within(trackList).getByText("Open Eye Signal")).toBeInTheDocument();
    expect(within(trackList).getByText("Jon Hopkins")).toBeInTheDocument();
    expect(within(trackList).getByText("Immunity")).toBeInTheDocument();
    expect(within(trackList).getByText("Late Night Drive")).toBeInTheDocument();
    expect(within(trackList).getByText("ytm:VLPL_missing_018")).toBeInTheDocument();
    expect(within(trackList).getByText("2 playlists: Focus Queue, Late Night Drive")).toBeInTheDocument();
    expect(within(trackList).queryByText("High gap")).not.toBeInTheDocument();
    expect(within(trackList).queryByText("Streaming only")).not.toBeInTheDocument();
    expect(within(trackList).queryByText("No local match")).not.toBeInTheDocument();
    expect(within(trackList).getByText("No Reason")).toBeInTheDocument();
    expect(within(trackList).getByText("Bonobo feat. Nick Murphy")).toBeInTheDocument();
    expect(within(trackList).getByText("Melt!")).toBeInTheDocument();
    expect(within(trackList).getByText("Album unavailable")).toBeInTheDocument();
  });

  it("renders a pending status while missing-local matching is running", () => {
    mockMissingLocallyFetch();

    renderWithQueryClient(<MissingLocallyView isPending />);

    expect(screen.getByText("Missing locally scan in progress")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Missing local tracks" })).toBeInTheDocument();
  });

  it("renders missing-locally loading, error, and empty states", () => {
    mockMissingLocallyFetch({
      tracks: [],
    });

    const { rerender } = renderWithQueryClient(<MissingLocallyView state="loading" />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading missing tracks");
    expect(screen.queryByText("Open Eye Signal")).not.toBeInTheDocument();

    rerender(<MissingLocallyView state="error" />);

    expect(screen.getByRole("alert")).toHaveTextContent("Missing locally unavailable");

    rerender(<MissingLocallyView state="ready" tracksResponse={{ tracks: [] }} />);

    expect(screen.getByRole("heading", { name: "No missing tracks" })).toBeInTheDocument();
    expect(screen.getByLabelText("Missing tracks")).toHaveTextContent("0");
    expect(screen.getByLabelText("Affected playlists")).toHaveTextContent("0");
    expect(screen.queryByLabelText("High priority")).not.toBeInTheDocument();
  });
});
