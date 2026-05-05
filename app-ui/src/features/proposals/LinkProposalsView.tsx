import { useMemo, type CSSProperties, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { FilterChipGroup, type FilterChipOption } from "../../components/FilterChipGroup";
import { Pill, type PillTone } from "../../components/Pill";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import {
  approveLinkProposal,
  playlistQueryKeys,
  rejectLinkProposal,
  type LinkProposal,
  type LinkProposalConfidenceBand,
  type LinkProposalsResponse,
  useLinkProposalsQuery,
} from "../playlists/queries";

type LinkProposalGroup = {
  candidates: LinkProposal[];
  localTrackId: number;
};
type GroupedLinkProposalGroups = Record<LinkProposalConfidenceBand, LinkProposalGroup[]>;
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

function getEmptyProposalGroupBuckets(): GroupedLinkProposalGroups {
  return {
    high: [],
    low: [],
    medium: [],
  };
}

function sortProposalCandidates(proposals: LinkProposal[]) {
  return [...proposals].sort((left, right) => {
    if (right.score !== left.score) {
      return right.score - left.score;
    }

    return left.id - right.id;
  });
}

function groupLinkProposalsByBand(proposals: LinkProposal[]): GroupedLinkProposalGroups {
  const proposalsByTrack = proposals.reduce<Map<number, LinkProposal[]>>((groups, proposal) => {
    const existingGroup = groups.get(proposal.local_track_id) ?? [];
    existingGroup.push(proposal);
    groups.set(proposal.local_track_id, existingGroup);
    return groups;
  }, new Map());
  const groupedByBand = getEmptyProposalGroupBuckets();

  Array.from(proposalsByTrack.entries())
    .map(([localTrackId, trackProposals]) => ({
      candidates: sortProposalCandidates(trackProposals),
      localTrackId,
    }))
    .sort((left, right) => right.candidates[0].score - left.candidates[0].score)
    .forEach((proposalGroup) => {
      groupedByBand[proposalGroup.candidates[0].confidence_band].push(proposalGroup);
    });

  return groupedByBand;
}

async function removeProposalCandidateFromCache(
  queryClient: ReturnType<typeof useQueryClient>,
  proposalId: number | string,
  options: { removeLocalTrackGroup: boolean },
): Promise<OptimisticProposalMutationContext> {
  await queryClient.cancelQueries({ queryKey: ["playlists", "proposals"] });

  const previousProposalQueries = queryClient.getQueriesData<LinkProposalsResponse>({
    queryKey: ["playlists", "proposals"],
  });
  const targetLocalTrackIds = new Set(
    previousProposalQueries.flatMap(([, data]) =>
      data?.proposals
        .filter((proposal) => String(proposal.id) === String(proposalId))
        .map((proposal) => proposal.local_track_id) ?? [],
    ),
  );

  queryClient.setQueriesData<LinkProposalsResponse>({ queryKey: ["playlists", "proposals"] }, (current) => {
    if (!current) {
      return current;
    }

    return {
      proposals: current.proposals.filter((proposal) => {
        if (String(proposal.id) === String(proposalId)) {
          return false;
        }

        return !options.removeLocalTrackGroup || !targetLocalTrackIds.has(proposal.local_track_id);
      }),
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

  return matchMethod;
}

function getMatchMethodTone(matchMethod: string): PillTone {
  const normalizedMethod = matchMethod.toLowerCase();

  if (normalizedMethod === "isrc") {
    return "success";
  }

  return "neutral";
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
    onMutate: (proposalId) => removeProposalCandidateFromCache(queryClient, proposalId, { removeLocalTrackGroup: true }),
    onError: (_error, _proposalId, context) => {
      restoreProposalCache(queryClient, context);
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: playlistQueryKeys.all });
    },
  });
  const rejectMutation = useMutation({
    mutationFn: rejectLinkProposal,
    onMutate: (proposalId) => removeProposalCandidateFromCache(queryClient, proposalId, { removeLocalTrackGroup: false }),
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
          <h2 className={textClasses.sectionTitle}>Proposal queue</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            {proposalsQuery.isSuccess
              ? `${proposalCount} pending suggestions grouped by confidence.`
              : "Pending suggestions grouped by confidence."}
          </p>
        </div>
        <FilterChipGroup
          activeValue={activeFilter}
          ariaLabel="Confidence band filters"
          density="compact"
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
        <EmptyStateCard body={emptyBody} className={`${layoutClasses.emptyStateNarrow} text-left`} title={emptyTitle} />
      </div>,
    );
  }

  return renderProposalFrame(
    <div className="min-h-0 flex-1 overflow-y-auto pr-1">
      <div className="grid gap-4">
        {proposalBandOrder.map((band) => {
          const bandProposalGroups = groupedProposals[band];
          const label = proposalBandLabels[band];

          return (
            <section aria-labelledby={`proposal-band-${band}`} className="grid gap-3" key={band}>
              <header className="flex items-center justify-between gap-3">
                <h3 className={textClasses.proposalTitle} id={`proposal-band-${band}`}>
                  {label}
                </h3>
                <span className={controlClasses.countBadge}>
                  {bandProposalGroups.length}
                </span>
              </header>
              {bandProposalGroups.length > 0 ? (
                <ul className="grid gap-3">
                  {bandProposalGroups.map((proposalGroup) => (
                    <ProposalGroupCard
                      activeApproveProposalId={activeApproveProposalId}
                      activeRejectProposalId={activeRejectProposalId}
                      failedApproveProposalId={failedApproveProposalId}
                      failedRejectProposalId={failedRejectProposalId}
                      key={proposalGroup.localTrackId}
                      onApprove={(proposalId) => approveMutation.mutate(proposalId)}
                      onReject={(proposalId) => rejectMutation.mutate(proposalId)}
                      proposalGroup={proposalGroup}
                    />
                  ))}
                </ul>
              ) : (
                <p className={`${surfaceClasses.dashedPlaceholder} ${textClasses.bodyMuted}`}>
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

function ProposalGroupCard({
  activeApproveProposalId,
  activeRejectProposalId,
  failedApproveProposalId,
  failedRejectProposalId,
  onApprove,
  onReject,
  proposalGroup,
}: {
  activeApproveProposalId: string | null;
  activeRejectProposalId: string | null;
  failedApproveProposalId: string | null;
  failedRejectProposalId: string | null;
  onApprove: (proposalId: number) => void;
  onReject: (proposalId: number) => void;
  proposalGroup: LinkProposalGroup;
}) {
  const topProposal = proposalGroup.candidates[0];
  const activeProposalId = activeApproveProposalId ?? activeRejectProposalId;
  const isGroupActionPending = proposalGroup.candidates.some((proposal) => String(proposal.id) === activeProposalId);

  return (
    <li className={surfaceClasses.rowCardCompact}>
      <div className="grid gap-3 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <div className="min-w-0">
          <p className={`${textClasses.eyebrow} tracking-normal text-ctp-subtext0`}>Local track</p>
          <p className={`mt-1 truncate ${textClasses.proposalTitle}`}>{getLocalTrackLabel(topProposal)}</p>
          <p className={`mt-1 truncate ${textClasses.caption}`}>{topProposal.local_file_path}</p>
          <p className={`mt-2 ${textClasses.detail}`}>Track #{topProposal.local_track_id}</p>
        </div>
        <div className="grid gap-2">
          <p className={`${textClasses.eyebrow} tracking-normal text-ctp-subtext0`}>Ranked candidates</p>
          <ul className="grid gap-2">
            {proposalGroup.candidates.map((proposal, index) => (
              <ProposalCandidateRow
                actionError={
                  failedApproveProposalId === String(proposal.id)
                    ? "Approve failed."
                    : failedRejectProposalId === String(proposal.id)
                      ? "Reject failed."
                      : null
                }
                isApproving={activeApproveProposalId === String(proposal.id)}
                isRejecting={activeRejectProposalId === String(proposal.id)}
                isGroupActionPending={isGroupActionPending}
                key={proposal.id}
                onApprove={() => onApprove(proposal.id)}
                onReject={() => onReject(proposal.id)}
                proposal={proposal}
                rank={index + 1}
              />
            ))}
          </ul>
        </div>
      </div>
    </li>
  );
}

function ProposalCandidateRow({
  actionError,
  isApproving,
  isGroupActionPending,
  isRejecting,
  onApprove,
  onReject,
  proposal,
  rank,
}: {
  actionError: string | null;
  isApproving: boolean;
  isGroupActionPending: boolean;
  isRejecting: boolean;
  onApprove: () => void;
  onReject: () => void;
  proposal: LinkProposal;
  rank: number;
}) {
  const scorePercentage = getProposalScorePercentage(proposal.score);
  const scoreMeterStyle: CSSProperties & Record<"--proposal-score-width", string> = {
    "--proposal-score-width": `${scorePercentage}%`,
  };

  return (
    <li className={`${surfaceClasses.insetPanel} px-3 py-2.5`}>
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_170px]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={controlClasses.countBadgeCompact}>{rank}</span>
            <Pill tone={getMatchMethodTone(proposal.match_method)}>
              {getMatchMethodLabel(proposal.match_method)}
            </Pill>
            <span className={textClasses.score}>{formatProposalScore(proposal.score)}</span>
          </div>
          <p className={`mt-2 truncate ${textClasses.proposalTitle}`}>{proposal.streaming_title}</p>
          <p className={`mt-1 truncate ${textClasses.caption}`}>{proposal.streaming_artist}</p>
          <p className={`mt-2 truncate ${textClasses.detail}`}>{proposal.streaming_album ?? "Album unavailable"}</p>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-ctp-surface0" aria-hidden="true">
            <div
              className={`h-full rounded-full [width:var(--proposal-score-width)] ${getProposalScoreColorClass(scorePercentage)}`}
              style={scoreMeterStyle}
            />
          </div>
        </div>
        <div className="grid content-end gap-2">
          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            <ActionButton disabled={isGroupActionPending} onClick={onApprove} tone="success">
              {isApproving ? "Approving..." : "Approve"}
            </ActionButton>
            <ActionButton disabled={isGroupActionPending} onClick={onReject} tone="danger">
              {isRejecting ? "Rejecting..." : "Reject"}
            </ActionButton>
          </div>
          {actionError ? (
            <p className={`text-right font-medium text-ctp-red ${textClasses.finePrint}`}>{actionError}</p>
          ) : null}
        </div>
      </div>
    </li>
  );
}
