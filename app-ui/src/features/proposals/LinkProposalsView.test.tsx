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
      local_file_path: "Frame Delay/Night Runner.mp3",
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
      local_file_path: "Frame Delay/Night Runner.mp3",
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
      local_file_path: "Static Gate/Pending Signal.mp3",
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
      const [, queryString = ""] = url.split("?");
      const band = new URLSearchParams(queryString).get("band");
      const proposals = band
        ? response.proposals.filter((proposal) => proposal.confidence_band === band)
        : response.proposals;

      return {
        ok: true,
        json: async () => ({ proposals }),
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

  it("groups proposal cards by local track within confidence bands and renders reusable confidence filters", async () => {
    mockProposalFetch();

    renderLinkProposalsView();

    expect(await screen.findByRole("heading", { level: 2, name: "Proposal queue" })).toBeInTheDocument();
    expect(await screen.findByText("Night Runner.mp3")).toBeInTheDocument();

    const highSection = screen.getByRole("heading", { level: 3, name: "High" }).closest("section");
    const mediumSection = screen.getByRole("heading", { level: 3, name: "Medium" }).closest("section");

    expect(highSection).not.toBeNull();
    expect(mediumSection).not.toBeNull();
    expect(within(highSection!).getByText("Night Runner.mp3")).toBeInTheDocument();
    expect(within(highSection!).getByText("Night Runner Alternate")).toBeInTheDocument();
    expect(within(highSection!).getAllByText("Tag")).toHaveLength(2);
    expect(within(highSection!).getByText("92%")).toBeInTheDocument();
    expect(within(highSection!).getByText("82%")).toBeInTheDocument();
    expect(within(mediumSection!).getByText("Pending Signal.mp3")).toBeInTheDocument();
    expect(within(mediumSection!).getByText("ISRC")).toBeInTheDocument();
    expect(within(mediumSection!).getByText("Album unavailable")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Confidence band filters" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
  });

  it("updates the query when a confidence filter chip is selected", async () => {
    const fetchMock = mockProposalFetch();

    renderLinkProposalsView();

    expect(await screen.findByText("Night Runner.mp3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Medium" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/proposals?band=medium");
      expect(screen.queryByText("Night Runner.mp3")).not.toBeInTheDocument();
    });
    expect(await screen.findByText("Pending Signal.mp3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Medium" })).toHaveAttribute("aria-pressed", "true");
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

    expect(await screen.findByText("Night Runner.mp3")).toBeInTheDocument();
    expect(screen.getByText("Night Runner Alternate")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Reject" })[1]);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/proposals/47/reject", { method: "POST" });
      expect(screen.queryByText("Night Runner Alternate")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Night Runner.mp3")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Approve" })[0]);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/proposals/44/approve", { method: "POST" });
      expect(screen.queryByText("Night Runner.mp3")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));

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
