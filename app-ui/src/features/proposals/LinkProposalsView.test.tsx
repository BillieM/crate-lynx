import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { LinkProposalsView } from "./LinkProposalsView";
import type { LinkProposalsResponse } from "../playlists/queries";
import type { ProposalDetail } from "./queries";

const proposalsResponse: LinkProposalsResponse = {
  limit: 50,
  next_cursor: null,
  proposals: [
    {
      confidence_band: "high",
      id: 44,
      local_album: "Private Archive",
      local_artist: "Frame Delay",
      local_file_path: "Frame Delay/Night Runner.mp3",
      local_title: "Night Runner File",
      local_track_id: 501,
      match_method: "tag",
      rejected_at: null,
      score: 0.92,
      status: "pending",
      streaming_album: "Late Night Drive",
      streaming_artist: "Frame Delay",
      streaming_provider_track_id: "ytm-901",
      streaming_title: "Night Runner",
      streaming_track_id: 901,
    },
    {
      confidence_band: "medium",
      id: 47,
      local_album: "Private Archive",
      local_artist: "Frame Delay",
      local_file_path: "Frame Delay/Night Runner.mp3",
      local_title: "Night Runner File",
      local_track_id: 501,
      match_method: "tag",
      rejected_at: null,
      score: 0.82,
      status: "pending",
      streaming_album: "Late Night Drive",
      streaming_artist: "Frame Delay",
      streaming_provider_track_id: "ytm-907",
      streaming_title: "Night Runner Alternate",
      streaming_track_id: 907,
    },
    {
      confidence_band: "medium",
      id: 45,
      local_album: null,
      local_artist: null,
      local_file_path: "Static Gate/Pending Signal.mp3",
      local_title: null,
      local_track_id: 502,
      match_method: "isrc",
      rejected_at: null,
      score: 0.72,
      status: "pending",
      streaming_album: null,
      streaming_artist: "Static Gate",
      streaming_provider_track_id: "ytm-902",
      streaming_title: "Pending Signal",
      streaming_track_id: 902,
    },
  ],
  returned_count: 3,
  total_count: 3,
};

function renderLinkProposalsView(initialEntry = "/proposals") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <LinkProposalsView />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

type MockProposalFetchOptions = {
  approveHandler?: () => Promise<Response> | Response;
  detailResponse?: ProposalDetail;
  detailStatus?: number;
  rejectHandler?: () => Promise<Response> | Response;
  response?: LinkProposalsResponse;
};

function mockProposalFetch({
  approveHandler,
  detailResponse,
  detailStatus,
  rejectHandler,
  response = proposalsResponse,
}: MockProposalFetchOptions = {}) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);

    if (url === "/api/proposals/44" && init?.method === undefined) {
      return {
        ok: detailStatus === undefined || detailStatus < 400,
        status: detailStatus ?? 200,
        json: async () => detailResponse ?? { ...proposalsResponse.proposals[0], state: "pending" },
      } as Response;
    }

    if (/^\/api\/proposals(?:\?|$)/.test(url) && init?.method === undefined) {
      return {
        ok: true,
        json: async () => response,
      } as Response;
    }

    if (url === "/api/proposals/44/approve" && init?.method === "POST") {
      if (approveHandler) {
        return approveHandler();
      }

      return {
        ok: true,
        json: async () => ({ final_link_id: 9044, proposal_id: 44, status: "approved" }),
      } as Response;
    }

    if ((url === "/api/proposals/45/reject" || url === "/api/proposals/47/reject") && init?.method === "POST") {
      if (rejectHandler) {
        return rejectHandler();
      }

      const proposalId = Number(url.match(/\/api\/proposals\/(\d+)\/reject/)?.[1]);

      return {
        ok: true,
        json: async () => ({ proposal_id: proposalId, rejected_at: "2026-05-04T10:00:00Z", status: "rejected" }),
      } as Response;
    }

    throw new Error(`Unexpected fetch request: ${init?.method ?? "GET"} ${url}`);
  });
}

describe("LinkProposalsView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("groups ranked alternatives into one task per local track with truthful counts", async () => {
    const fetchMock = mockProposalFetch();

    renderLinkProposalsView();

    expect(await screen.findByRole("heading", { level: 2, name: "Proposal queue" })).toBeInTheDocument();
    expect(await screen.findAllByText("Night Runner.mp3")).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/proposals?limit=50");

    expect(screen.getByText("2 local-track tasks shown from 3 matching loaded candidates. 3 of 3 total candidates are loaded.")).toBeInTheDocument();
    const taskList = screen.getByRole("list", { name: "Local-track proposal tasks" });
    expect(within(taskList).getAllByRole("listitem", { name: /Local track task/ })).toHaveLength(2);
    const nightRunnerTask = screen.getByRole("listitem", { name: "Local track task Night Runner.mp3" });
    expect(within(nightRunnerTask).getByRole("list", { name: "Ranked alternatives for Night Runner.mp3" })).toBeInTheDocument();
    expect(within(nightRunnerTask).getByText("2 alternatives")).toBeInTheDocument();

    const nightRunnerRow = screen.getByRole("listitem", { name: /Proposal 44: Night Runner\.mp3 to Night Runner$/ });
    const alternateRow = screen.getByRole("listitem", {
      name: /Proposal 47: Night Runner\.mp3 to Night Runner Alternate$/,
    });
    const pendingSignalRow = screen.getByRole("listitem", {
      name: /Proposal 45: Pending Signal\.mp3 to Pending Signal$/,
    });

    expect(nightRunnerRow.compareDocumentPosition(alternateRow)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(alternateRow.compareDocumentPosition(pendingSignalRow)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(within(nightRunnerTask).getByText("Night Runner File")).toBeInTheDocument();
    expect(within(nightRunnerTask).getByText(/Frame Delay · Private Archive/)).toBeInTheDocument();
    expect(within(nightRunnerRow).getByText("Tag")).toBeInTheDocument();
    expect(within(nightRunnerRow).getByText("92%")).toBeInTheDocument();
    expect(within(nightRunnerRow).getByText("High confidence")).toBeInTheDocument();
    fireEvent.click(within(nightRunnerRow).getByRole("button", { name: "Inspect proposal 44" }));
    expect(within(nightRunnerRow).getByLabelText("Listen to Night Runner File")).toHaveAttribute(
      "src",
      "/api/local-tracks/501/audio",
    );
    expect(within(nightRunnerRow).getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      "https://music.youtube.com/watch?v=ytm-901",
    );
    fireEvent.click(within(nightRunnerRow).getByRole("button", { name: "Preview" }));
    expect(within(nightRunnerRow).getByTitle("YouTube preview for Night Runner").getAttribute("src")).toContain(
      "https://www.youtube.com/embed/ytm-901",
    );
    expect(within(alternateRow).getAllByText("Night Runner Alternate")).toHaveLength(2);
    expect(within(alternateRow).getByText("82%")).toBeInTheDocument();
    expect(within(alternateRow).getByText("Medium confidence")).toBeInTheDocument();
    expect(within(pendingSignalRow).getByText("ISRC")).toBeInTheDocument();
    expect(within(pendingSignalRow).getAllByText("Album unavailable")).toHaveLength(1);

    expect(within(nightRunnerRow).getByText("Alternative 1")).toBeInTheDocument();
    expect(within(alternateRow).getByText("Alternative 2")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Approve proposal/ })).toHaveLength(3);
    expect(screen.getAllByRole("button", { name: /Reject proposal/ })).toHaveLength(3);
  });

  it("keeps the local filename and labels unavailable local metadata once at task level", async () => {
    mockProposalFetch();

    renderLinkProposalsView();

    const pendingSignalTask = await screen.findByRole("listitem", { name: "Local track task Pending Signal.mp3" });
    const pendingSignalRow = within(pendingSignalTask).getByRole("listitem", { name: /Proposal 45: Pending Signal\.mp3/ });
    expect(within(pendingSignalTask).getByText("Metadata unavailable")).toBeInTheDocument();
    expect(within(pendingSignalTask).getByText("Pending Signal.mp3")).toBeInTheDocument();
    expect(within(pendingSignalRow).getAllByText("Album unavailable")).toHaveLength(1);
  });

  it("renders a dash only for the missing local field when partial metadata is present", async () => {
    mockProposalFetch({
      response: {
        limit: 50,
        next_cursor: null,
        proposals: [
          {
            confidence_band: "medium",
            id: 50,
            local_album: "Singles",
            local_artist: null,
            local_file_path: "Static Gate/Partial Signal.mp3",
            local_title: "Partial Signal",
            local_track_id: 503,
            match_method: "tag",
            rejected_at: null,
            score: 0.74,
            status: "pending",
            streaming_album: "Signals",
            streaming_artist: "Static Gate",
            streaming_provider_track_id: "ytm-908",
            streaming_title: "Partial Signal",
            streaming_track_id: 908,
          },
        ],
        returned_count: 1,
        total_count: 1,
      },
    });

    renderLinkProposalsView();

    const partialTask = await screen.findByRole("listitem", { name: "Local track task Partial Signal.mp3" });
    expect(within(partialTask).getAllByText("Partial Signal").length).toBeGreaterThanOrEqual(2);
    expect(within(partialTask).getByText("Singles")).toBeInTheDocument();
  });

  it("ignores legacy confidence band URL state and fetches all proposals", async () => {
    const fetchMock = mockProposalFetch();

    renderLinkProposalsView("/proposals?band=high");

    expect(await screen.findAllByText("Night Runner.mp3")).toHaveLength(1);
    expect(screen.getByText("Pending Signal.mp3")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/proposals?limit=50");
    expect(fetchMock).not.toHaveBeenCalledWith("/api/proposals?band=high");
    expect(screen.getByRole("group", { name: "Proposal confidence filters" })).toBeInTheDocument();
  });

  it("filters loaded tasks by search, method, and confidence without overstating totals", async () => {
    mockProposalFetch();

    renderLinkProposalsView();

    const searchInput = await screen.findByRole("searchbox", { name: "Search loaded proposals" });
    fireEvent.change(searchInput, { target: { value: "Pending Signal" } });
    expect(screen.getByText("1 local-track task shown from 1 matching loaded candidates. 3 of 3 total candidates are loaded.")).toBeInTheDocument();
    expect(screen.queryByRole("listitem", { name: "Local track task Night Runner.mp3" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Match method" }), { target: { value: "isrc" } });
    expect(screen.getByRole("listitem", { name: "Local track task Pending Signal.mp3" })).toBeInTheDocument();
    expect(screen.queryByRole("listitem", { name: "Local track task Night Runner.mp3" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Match method" }), { target: { value: "all" } });
    fireEvent.click(screen.getByRole("button", { name: "High 1" }));
    expect(screen.getByRole("listitem", { name: "Local track task Night Runner.mp3" })).toBeInTheDocument();
    expect(screen.queryByRole("listitem", { name: "Local track task Pending Signal.mp3" })).not.toBeInTheDocument();
  });

  it("loads and focuses the exact pending proposal from a path deep link", async () => {
    const fetchMock = mockProposalFetch();

    renderLinkProposalsView("/proposals/44");

    const focusedProposal = await screen.findByLabelText("Focused proposal 44");
    expect(fetchMock).toHaveBeenCalledWith("/api/proposals/44");
    expect(focusedProposal).toHaveFocus();
    expect(within(focusedProposal).getByText("Proposal ready for review")).toBeInTheDocument();
    expect(within(focusedProposal).getByRole("button", { name: "Approve proposal 44" })).toBeInTheDocument();
  });

  it.each([
    ["resolved", "Proposal already resolved"],
    ["stale", "Proposal is stale"],
  ] as const)("distinguishes an exact %s proposal from a pending proposal", async (state, title) => {
    mockProposalFetch({
      detailResponse: { ...proposalsResponse.proposals[0], state },
    });

    renderLinkProposalsView("/proposals?proposal_id=44");

    const focusedProposal = await screen.findByLabelText("Focused proposal 44");
    expect(within(focusedProposal).getByText(title)).toBeInTheDocument();
    expect(within(focusedProposal).queryByRole("button", { name: "Approve proposal 44" })).not.toBeInTheDocument();
    expect(within(focusedProposal).queryByRole("button", { name: "Reject proposal 44" })).not.toBeInTheDocument();
  });

  it("distinguishes a missing exact proposal from a general loading failure", async () => {
    mockProposalFetch({ detailStatus: 404 });

    renderLinkProposalsView("/proposals/44");

    expect(await screen.findByRole("alert")).toHaveTextContent("Proposal not found");
    expect(screen.getByText("Proposal 44 does not exist or is no longer available.")).toBeInTheDocument();
  });

  it("loads more proposals with cursor pagination", async () => {
    const thirdProposal = proposalsResponse.proposals[2];
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url === "/api/proposals?limit=50") {
        return {
          ok: true,
          json: async () => ({
            ...proposalsResponse,
            next_cursor: "page-2",
            proposals: proposalsResponse.proposals.slice(0, 2),
            returned_count: 2,
            total_count: 75,
          }),
        } as Response;
      }

      if (url === "/api/proposals?cursor=page-2&limit=50") {
        return {
          ok: true,
          json: async () => ({
            ...proposalsResponse,
            next_cursor: null,
            proposals: [thirdProposal],
            returned_count: 1,
            total_count: 75,
          }),
        } as Response;
      }

      throw new Error(`Unexpected fetch request: GET ${url}`);
    });

    renderLinkProposalsView();

    expect(await screen.findByText("1 local-track task shown from 2 matching loaded candidates. 2 of 75 total candidates are loaded.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/proposals?cursor=page-2&limit=50");
    });
    expect(await screen.findByText("2 local-track tasks shown from 3 matching loaded candidates. 3 of 75 total candidates are loaded.")).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: /Proposal 45: Pending Signal\.mp3/ })).toBeInTheDocument();
  });

  it("optimistically removes whole local-track groups on approve and only selected candidates on reject", async () => {
    let resolveApprove: (response: Response) => void = () => {};
    let resolveReject: (response: Response) => void = () => {};
    const approvePromise = new Promise<Response>((resolve) => {
      resolveApprove = resolve;
    });
    const rejectPromise = new Promise<Response>((resolve) => {
      resolveReject = resolve;
    });
    const fetchMock = mockProposalFetch({
      approveHandler: () => approvePromise,
      rejectHandler: () => rejectPromise,
    });

    renderLinkProposalsView();

    expect(await screen.findAllByText("Night Runner.mp3")).toHaveLength(1);
    expect(screen.getAllByText("Night Runner Alternate")).toHaveLength(2);
    const alternateRow = screen.getByRole("listitem", {
      name: /Proposal 47: Night Runner\.mp3 to Night Runner Alternate$/,
    });
    fireEvent.click(within(alternateRow).getByRole("button", { name: /Reject proposal 47/ }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/proposals/47/reject", { method: "POST" });
      expect(screen.queryByText("Night Runner Alternate")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("listitem", { name: /Proposal 44: Night Runner\.mp3/ })).toBeInTheDocument();

    fireEvent.click(
      within(screen.getByRole("listitem", { name: /Proposal 44: Night Runner\.mp3/ })).getByRole("button", {
        name: /Approve proposal 44/,
      }),
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/proposals/44/approve", { method: "POST" });
      expect(screen.queryByText("Night Runner.mp3")).not.toBeInTheDocument();
    });

    fireEvent.click(
      within(screen.getByRole("listitem", { name: /Proposal 45: Pending Signal\.mp3/ })).getByRole("button", {
        name: /Reject proposal 45/,
      }),
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/proposals/45/reject", { method: "POST" });
      expect(screen.queryByText("Pending Signal.mp3")).not.toBeInTheDocument();
    });

    resolveApprove({
      ok: true,
      json: async () => ({ final_link_id: 9044, proposal_id: 44, status: "approved" }),
    } as Response);
    resolveReject({
      ok: true,
      json: async () => ({ proposal_id: 45, rejected_at: "2026-05-04T10:00:00Z", status: "rejected" }),
    } as Response);
  });
});
