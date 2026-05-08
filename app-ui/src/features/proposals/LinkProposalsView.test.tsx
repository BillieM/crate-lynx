import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { LinkProposalsView } from "./LinkProposalsView";
import type { LinkProposalsResponse } from "../playlists/queries";

const proposalsResponse: LinkProposalsResponse = {
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
      streaming_title: "Pending Signal",
      streaming_track_id: 902,
    },
  ],
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
  rejectHandler?: () => Promise<Response> | Response;
  response?: LinkProposalsResponse;
};

function mockProposalFetch({ approveHandler, rejectHandler, response = proposalsResponse }: MockProposalFetchOptions = {}) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);

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

  it("renders flat proposal rows in score order without confidence band filters", async () => {
    const fetchMock = mockProposalFetch();

    renderLinkProposalsView();

    expect(await screen.findByRole("heading", { level: 2, name: "Proposal queue" })).toBeInTheDocument();
    expect(await screen.findAllByText("Night Runner.mp3")).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledWith("/api/proposals");

    expect(screen.queryByRole("heading", { level: 3, name: "High" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3, name: "Medium" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3, name: "Low" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Confidence band filters" })).not.toBeInTheDocument();
    expect(screen.queryByText("Ranked candidates")).not.toBeInTheDocument();

    const nightRunnerRow = screen.getByRole("listitem", { name: /Proposal 44: Night Runner\.mp3 to Night Runner$/ });
    const alternateRow = screen.getByRole("listitem", {
      name: /Proposal 47: Night Runner\.mp3 to Night Runner Alternate$/,
    });
    const pendingSignalRow = screen.getByRole("listitem", {
      name: /Proposal 45: Pending Signal\.mp3 to Pending Signal$/,
    });

    expect(nightRunnerRow.compareDocumentPosition(alternateRow)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(alternateRow.compareDocumentPosition(pendingSignalRow)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(within(nightRunnerRow).getByText("Night Runner File")).toBeInTheDocument();
    expect(within(nightRunnerRow).getByText("Private Archive")).toBeInTheDocument();
    expect(within(nightRunnerRow).getByText("Tag")).toBeInTheDocument();
    expect(within(nightRunnerRow).getByText("92%")).toBeInTheDocument();
    expect(within(nightRunnerRow).getByText("High confidence")).toBeInTheDocument();
    expect(within(alternateRow).getAllByText("Night Runner Alternate")).toHaveLength(2);
    expect(within(alternateRow).getByText("82%")).toBeInTheDocument();
    expect(within(alternateRow).getByText("Medium confidence")).toBeInTheDocument();
    expect(within(pendingSignalRow).getByText("ISRC")).toBeInTheDocument();
    expect(within(pendingSignalRow).getAllByText("Album unavailable")).toHaveLength(1);

    expect(
      within(nightRunnerRow).getByText("Local track").compareDocumentPosition(within(nightRunnerRow).getByText("Streaming track")),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(screen.getAllByRole("button", { name: /Approve proposal/ })).toHaveLength(3);
    expect(screen.getAllByRole("button", { name: /Reject proposal/ })).toHaveLength(3);
  });

  it("renders missing local metadata as dashes while keeping the filename", async () => {
    mockProposalFetch();

    renderLinkProposalsView();

    const pendingSignalRow = await screen.findByRole("listitem", { name: /Proposal 45: Pending Signal\.mp3/ });
    expect(within(pendingSignalRow).getAllByText("—")).toHaveLength(3);
    expect(within(pendingSignalRow).getAllByText("Album unavailable")).toHaveLength(1);
  });

  it("renders a dash only for the missing local field when partial metadata is present", async () => {
    mockProposalFetch({
      response: {
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
            streaming_title: "Partial Signal",
            streaming_track_id: 908,
          },
        ],
      },
    });

    renderLinkProposalsView();

    const partialRow = await screen.findByRole("listitem", { name: /Proposal 50: Partial Signal\.mp3/ });
    expect(within(partialRow).getAllByText("Partial Signal")).toHaveLength(3);
    expect(within(partialRow).getByText("Singles")).toBeInTheDocument();
    expect(within(partialRow).getAllByText("—")).toHaveLength(1);
  });

  it("ignores legacy confidence band URL state and fetches all proposals", async () => {
    const fetchMock = mockProposalFetch();

    renderLinkProposalsView("/proposals?band=high");

    expect(await screen.findAllByText("Night Runner.mp3")).toHaveLength(2);
    expect(screen.getByText("Pending Signal.mp3")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/proposals");
    expect(fetchMock).not.toHaveBeenCalledWith("/api/proposals?band=high");
    expect(screen.queryByRole("group", { name: "Confidence band filters" })).not.toBeInTheDocument();
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

    expect(await screen.findAllByText("Night Runner.mp3")).toHaveLength(2);
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
