import { useMemo, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { FilterChipGroup, type FilterChipOption } from "../../components/FilterChipGroup";
import {
  approveLinkProposal,
  playlistQueryKeys,
  rejectLinkProposal,
  type LinkProposal,
  type LinkProposalConfidenceBand,
  type LinkProposalsResponse,
  useLinkProposalsQuery,
} from "../playlists/queries";

type GroupedLinkProposals = Record<LinkProposalConfidenceBand, LinkProposal[]>;
type LinkProposalConfidenceBandFilter = LinkProposalConfidenceBand | "all";
type OptimisticProposalMutationContext = {
  previousProposalQueries: [readonly unknown[], LinkProposalsResponse | undefined][];
};

const proposalBandOrder = ["high", "medium", "low"] satisfies LinkProposalConfidenceBand[];
const proposalBandLabels = {
  high: "High",
  low: "Low",
  medium: "Medium",
} satisfies Record<LinkProposalConfidenceBand, string>;
const proposalBandFilterChips = [
  {
    label: "All",
    tone: "all",
    value: "all",
  },
  {
    label: "High",
    tone: "linked",
    value: "high",
  },
  {
    label: "Medium",
    tone: "pending",
    value: "medium",
  },
  {
    label: "Low",
    tone: "unlinked",
    value: "low",
  },
] satisfies FilterChipOption<LinkProposalConfidenceBandFilter>[];

function clampPercentage(matchPercentage: number) {
  return Math.max(0, Math.min(100, matchPercentage));
}

function getEmptyProposalGroups(): GroupedLinkProposals {
  return {
    high: [],
    low: [],
    medium: [],
  };
}

function groupLinkProposalsByBand(proposals: LinkProposal[]): GroupedLinkProposals {
  return proposals.reduce<GroupedLinkProposals>((groups, proposal) => {
    groups[proposal.confidence_band].push(proposal);
    return groups;
  }, getEmptyProposalGroups());
}

async function removeProposalFromCache(
  queryClient: ReturnType<typeof useQueryClient>,
  proposalId: number | string,
): Promise<OptimisticProposalMutationContext> {
  await queryClient.cancelQueries({ queryKey: ["playlists", "proposals"] });

  const previousProposalQueries = queryClient.getQueriesData<LinkProposalsResponse>({
    queryKey: ["playlists", "proposals"],
  });

  queryClient.setQueriesData<LinkProposalsResponse>({ queryKey: ["playlists", "proposals"] }, (current) => {
    if (!current) {
      return current;
    }

    return {
      proposals: current.proposals.filter((proposal) => String(proposal.id) !== String(proposalId)),
    };
  });

  return { previousProposalQueries };
}

function restoreProposalCache(
  queryClient: ReturnType<typeof useQueryClient>,
  context: OptimisticProposalMutationContext | undefined,
) {
  context?.previousProposalQueries.forEach(([queryKey, data]) => {
    queryClient.setQueryData(queryKey, data);
  });
}

function isProposalConfidenceBand(value: string | null): value is LinkProposalConfidenceBand {
  return value === "high" || value === "medium" || value === "low";
}

function getLocalTrackLabel(proposal: LinkProposal) {
  return proposal.local_file_path.split("/").pop() || proposal.local_file_path;
}

function getMatchMethodLabel(matchMethod: string) {
  const normalizedMethod = matchMethod.toLowerCase();

  if (normalizedMethod === "isrc") {
    return "ISRC";
  }

  if (normalizedMethod === "tag") {
    return "Tag";
  }

  if (normalizedMethod === "acoustic") {
    return "Acoustic";
  }

  return matchMethod;
}

function formatProposalScore(score: number) {
  return `${Math.round(score * 100)}%`;
}

function getProposalScorePercentage(score: number) {
  return clampPercentage(score * 100);
}

function getProposalScoreColorClass(scorePercentage: number) {
  if (scorePercentage >= 85) {
    return "bg-ctp-green";
  }

  if (scorePercentage >= 50) {
    return "bg-ctp-yellow";
  }

  return "bg-ctp-overlay1";
}

export function LinkProposalsView() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const activeConfidenceBand = useMemo(() => {
    const band = new URLSearchParams(location.search).get("band");
    return isProposalConfidenceBand(band) ? band : null;
  }, [location.search]);
  const activeFilter: LinkProposalConfidenceBandFilter = activeConfidenceBand ?? "all";
  const proposalsQuery = useLinkProposalsQuery({ confidenceBand: activeConfidenceBand });
  const approveMutation = useMutation({
    mutationFn: approveLinkProposal,
    onMutate: (proposalId) => removeProposalFromCache(queryClient, proposalId),
    onError: (_error, _proposalId, context) => {
      restoreProposalCache(queryClient, context);
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: playlistQueryKeys.all });
    },
  });
  const rejectMutation = useMutation({
    mutationFn: rejectLinkProposal,
    onMutate: (proposalId) => removeProposalFromCache(queryClient, proposalId),
    onError: (_error, _proposalId, context) => {
      restoreProposalCache(queryClient, context);
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: playlistQueryKeys.all });
    },
  });
  const proposals = proposalsQuery.data?.proposals;
  const proposalCount = proposals?.length ?? 0;
  const groupedProposals = useMemo(() => groupLinkProposalsByBand(proposals ?? []), [proposals]);
  const activeApproveProposalId = approveMutation.isPending ? String(approveMutation.variables) : null;
  const activeRejectProposalId = rejectMutation.isPending ? String(rejectMutation.variables) : null;
  const failedApproveProposalId = approveMutation.isError ? String(approveMutation.variables) : null;
  const failedRejectProposalId = rejectMutation.isError ? String(rejectMutation.variables) : null;
  const updateConfidenceBandFilter = (filter: LinkProposalConfidenceBandFilter) => {
    const params = new URLSearchParams(location.search);

    if (filter === "all") {
      params.delete("band");
    } else {
      params.set("band", filter);
    }

    const search = params.toString();
    navigate({ pathname: location.pathname, search: search ? `?${search}` : "" });
  };
  const renderProposalFrame = (children: ReactNode) => (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-[18px] font-semibold text-ctp-text">Proposal queue</h2>
          <p className="mt-1 text-[13px] text-ctp-subtext0">
            {proposalsQuery.isSuccess
              ? `${proposalCount} pending suggestions grouped by confidence.`
              : "Pending suggestions grouped by confidence."}
          </p>
        </div>
        <FilterChipGroup
          activeValue={activeFilter}
          ariaLabel="Confidence band filters"
          onValueChange={updateConfidenceBandFilter}
          options={proposalBandFilterChips}
        />
      </div>
      {children}
    </section>
  );

  if (proposalsQuery.isPending) {
    return renderProposalFrame(
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <EmptyStateCard
          body="Checking for pending local-to-streaming match suggestions."
          role="status"
          title="Loading proposals"
        />
      </div>,
    );
  }

  if (proposalsQuery.isError) {
    return renderProposalFrame(
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <EmptyStateCard
          body="Pending local-to-streaming match suggestions could not be loaded."
          role="alert"
          title="Proposals unavailable"
          tone="error"
        />
      </div>,
    );
  }

  if (proposalCount === 0) {
    const emptyTitle = activeConfidenceBand
      ? `No ${proposalBandLabels[activeConfidenceBand].toLowerCase()} confidence proposals`
      : "Proposal queue";
    const emptyBody = activeConfidenceBand
      ? "Switch confidence bands or clear the filter to review other pending suggestions."
      : "Pending local-to-streaming match suggestions will appear here as matching jobs finish.";

    return renderProposalFrame(
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <EmptyStateCard body={emptyBody} className="max-w-[460px] py-7 text-left" title={emptyTitle} />
      </div>,
    );
  }

  return renderProposalFrame(
    <div className="min-h-0 flex-1 overflow-y-auto pr-1">
      <div className="grid gap-6">
        {proposalBandOrder.map((band) => {
          const bandProposals = groupedProposals[band];
          const label = proposalBandLabels[band];

          return (
            <section aria-labelledby={`proposal-band-${band}`} className="grid gap-3" key={band}>
              <header className="flex items-center justify-between gap-3">
                <h3 className="text-[14px] font-semibold text-ctp-text" id={`proposal-band-${band}`}>
                  {label}
                </h3>
                <span className="rounded-full bg-ctp-surface0 px-2.5 py-1 text-[12px] font-semibold text-ctp-subtext0">
                  {bandProposals.length}
                </span>
              </header>
              {bandProposals.length > 0 ? (
                <ul className="grid gap-3">
                  {bandProposals.map((proposal) => (
                    <ProposalCard
                      actionError={
                        failedApproveProposalId === String(proposal.id)
                          ? "Approve failed."
                          : failedRejectProposalId === String(proposal.id)
                            ? "Reject failed."
                            : null
                      }
                      isApproving={activeApproveProposalId === String(proposal.id)}
                      isRejecting={activeRejectProposalId === String(proposal.id)}
                      key={proposal.id}
                      onApprove={() => approveMutation.mutate(proposal.id)}
                      onReject={() => rejectMutation.mutate(proposal.id)}
                      proposal={proposal}
                    />
                  ))}
                </ul>
              ) : (
                <p className="rounded-[8px] border border-dashed border-ctp-surface0 px-5 py-4 text-[13px] text-ctp-subtext0">
                  No {label.toLowerCase()} confidence proposals.
                </p>
              )}
            </section>
          );
        })}
      </div>
    </div>,
  );
}

function ProposalCard({
  actionError,
  isApproving,
  isRejecting,
  onApprove,
  onReject,
  proposal,
}: {
  actionError: string | null;
  isApproving: boolean;
  isRejecting: boolean;
  onApprove: () => void;
  onReject: () => void;
  proposal: LinkProposal;
}) {
  const scorePercentage = getProposalScorePercentage(proposal.score);
  const isActionPending = isApproving || isRejecting;

  return (
    <li className="rounded-[8px] border border-ctp-surface0 bg-ctp-mantle/80 p-4 shadow-sm shadow-ctp-crust/20">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_210px]">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase text-ctp-subtext0">Local track</p>
          <p className="mt-1 truncate text-[14px] font-semibold text-ctp-text">{getLocalTrackLabel(proposal)}</p>
          <p className="mt-1 truncate text-[12px] text-ctp-subtext0">{proposal.local_file_path}</p>
          <p className="mt-2 text-[12px] font-medium text-ctp-overlay1">Track #{proposal.local_track_id}</p>
        </div>
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase text-ctp-subtext0">Streaming track</p>
          <p className="mt-1 truncate text-[14px] font-semibold text-ctp-text">{proposal.streaming_title}</p>
          <p className="mt-1 truncate text-[12px] text-ctp-subtext0">{proposal.streaming_artist}</p>
          <p className="mt-2 truncate text-[12px] font-medium text-ctp-overlay1">
            {proposal.streaming_album ?? "Album unavailable"}
          </p>
        </div>
        <div className="grid content-between gap-3">
          <div className="flex flex-wrap items-center gap-2 xl:justify-end">
            <span className="rounded-full bg-ctp-surface0 px-2.5 py-1 text-[11px] font-semibold text-ctp-subtext0 ring-1 ring-inset ring-ctp-surface1">
              {getMatchMethodLabel(proposal.match_method)}
            </span>
            <span className="text-[15px] font-semibold text-ctp-text">{formatProposalScore(proposal.score)}</span>
          </div>
          <div>
            <div className="h-2 overflow-hidden rounded-full bg-ctp-surface0" aria-hidden="true">
              <div
                className={`h-full rounded-full ${getProposalScoreColorClass(scorePercentage)}`}
                style={{
                  width: `${scorePercentage}%`,
                }}
              />
            </div>
            <p className="mt-2 text-[12px] font-medium text-ctp-subtext0">Confidence score</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 xl:justify-end">
            <ActionButton disabled={isActionPending} onClick={onApprove} tone="success">
              {isApproving ? "Approving..." : "Approve"}
            </ActionButton>
            <ActionButton disabled={isActionPending} onClick={onReject} tone="danger">
              {isRejecting ? "Rejecting..." : "Reject"}
            </ActionButton>
            {actionError ? (
              <p className="basis-full text-right text-[11px] font-medium text-ctp-red">{actionError}</p>
            ) : null}
          </div>
        </div>
      </div>
    </li>
  );
}
