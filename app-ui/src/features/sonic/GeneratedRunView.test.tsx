import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { GeneratedRunView } from "./GeneratedRunView";

const queryMocks = vi.hoisted(() => ({
  deleteRun: vi.fn(),
  refetchRun: vi.fn(),
  refetchTracks: vi.fn(),
  runDetail: vi.fn(),
  tracks: vi.fn(),
}));

vi.mock("./queries", () => ({
  useDeletePlaylistGenerationRunMutation: () => ({
    isError: false,
    isPending: false,
    mutate: queryMocks.deleteRun,
  }),
  useGeneratedPlaylistTracksQuery: () => queryMocks.tracks(),
  useSonicRunDetailQuery: () => queryMocks.runDetail(),
}));

const run = {
  completed_at: "2026-05-24T12:00:00Z",
  created_at: "2026-05-24T11:55:00Z",
  error_detail: null,
  generation_config: {},
  generation_number: 19,
  id: 501,
  playlist_count: 3,
  source_filter: {},
  status: "completed",
  track_count: 58,
  updated_at: "2026-05-24T12:00:00Z",
};

const playlists = [
  {
    created_at: "2026-05-24T12:00:00Z",
    depth: 0,
    id: 1,
    name: "Root crate",
    parent_playlist_id: null,
    position: 1,
    run_id: 501,
    summary: {},
    track_count: 30,
  },
  {
    created_at: "2026-05-24T12:00:00Z",
    depth: 1,
    id: 2,
    name: "Child crate",
    parent_playlist_id: 1,
    position: 1,
    run_id: 501,
    summary: {},
    track_count: 14,
  },
  {
    created_at: "2026-05-24T12:00:00Z",
    depth: 0,
    id: 3,
    name: "Second root",
    parent_playlist_id: null,
    position: 2,
    run_id: 501,
    summary: {},
    track_count: 14,
  },
];

function renderGeneratedRun() {
  return render(
    <MemoryRouter>
      <GeneratedRunView runId={501} />
    </MemoryRouter>,
  );
}

describe("GeneratedRunView", () => {
  beforeEach(() => {
    queryMocks.runDetail.mockReturnValue({
      data: { playlists, run },
      error: null,
      isError: false,
      isPending: false,
      refetch: queryMocks.refetchRun,
    });
    queryMocks.tracks.mockReturnValue({
      data: { tracks: [] },
      isError: false,
      isPending: false,
      refetch: queryMocks.refetchTracks,
    });
  });

  it("uses a roving tree tab stop with hierarchy-aware keyboard navigation", () => {
    renderGeneratedRun();

    const tree = screen.getByRole("tree", { name: "Generated playlists" });
    const root = within(tree).getByRole("treeitem", { name: "Root crate, 30 tracks" });
    const child = within(tree).getByRole("treeitem", { name: "Child crate, 14 tracks" });
    const secondRoot = within(tree).getByRole("treeitem", { name: "Second root, 14 tracks" });

    expect(root).toHaveAttribute("tabindex", "0");
    expect(root).toHaveAttribute("aria-expanded", "true");
    expect(root).toHaveAttribute("aria-posinset", "1");
    expect(root).toHaveAttribute("aria-setsize", "2");
    expect(child).toHaveAttribute("tabindex", "-1");

    fireEvent.keyDown(root, { key: "ArrowRight" });
    expect(child).toHaveFocus();
    expect(child).toHaveAttribute("tabindex", "0");

    fireEvent.keyDown(child, { key: "ArrowLeft" });
    expect(root).toHaveFocus();

    fireEvent.keyDown(root, { key: "End" });
    expect(secondRoot).toHaveFocus();
  });

  it("labels failed counts as partial and explains an empty failed run", () => {
    queryMocks.runDetail.mockReturnValue({
      data: {
        playlists: [],
        run: { ...run, error_detail: "Worker stopped", playlist_count: 0, status: "failed", track_count: 0 },
      },
      error: null,
      isError: false,
      isPending: false,
      refetch: queryMocks.refetchRun,
    });

    renderGeneratedRun();

    expect(screen.getByText("Run ID 501 · 0 playlists generated · 0 tracks included before failure")).toBeInTheDocument();
    expect(screen.getByText("Generation failed before any playlists were stored.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Worker stopped");
  });
});
