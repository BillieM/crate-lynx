import { useQuery } from "@tanstack/react-query";

import { endpoints, fetchJson } from "../../lib/api";
import type { LinkProposal } from "../playlists/queries";

export type ProposalDetail = LinkProposal & {
  state: "pending" | "resolved" | "stale";
};

export const proposalDetailQueryKey = (proposalId: number | string) =>
  ["proposals", "detail", String(proposalId)] as const;

export function fetchProposalDetail(proposalId: number | string): Promise<ProposalDetail> {
  return fetchJson<ProposalDetail>(endpoints.api(`/proposals/${encodeURIComponent(String(proposalId))}`));
}

export function useProposalDetailQuery(proposalId: string | null) {
  return useQuery({
    enabled: proposalId !== null,
    queryKey: proposalDetailQueryKey(proposalId ?? "idle"),
    queryFn: () => fetchProposalDetail(proposalId ?? ""),
  });
}
