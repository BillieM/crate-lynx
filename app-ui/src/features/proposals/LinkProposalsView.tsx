import { useMemo, type CSSProperties, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { Pill, type PillTone } from "../../components/Pill";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import {
  approveLinkProposal,
  playlistQueryKeys,
  rejectLinkProposal,
  type LinkProposal,
  type LinkProposalsResponse,
  useLinkProposalsQuery,
} from "../playlists/queries";

type LinkProposalGroup = {
  candidates: LinkProposal[];
  localTrackId: number;
};
type OptimisticProposalMutationContext = {
  previousProposalQueries: [readonly unknown[], LinkProposalsResponse | undefined][];
};

function clampPercentage(matchPercentage: number) {
  return Math.max(0, Math.min(100, matchPercentage));
}

function sortProposalCandidates(proposals: LinkProposal[]) {
  return [...proposals].sort((left, right) => {
    if (right.score !== left.score) {
      return right.score - left.score;
    }

    return left.id - right.id;
  });
}

function groupLinkProposalsByLocalTrack(proposals: LinkProposal[]): LinkProposalGroup[] {
  const proposalsByTrack = proposals.reduce<Map<number, LinkProposal[]>>((groups, proposal) => {
    const existingGroup = groups.get(proposal.local_track_id) ?? [];
    existingGroup.push(proposal);
    groups.set(proposal.local_track_id, existingGroup);
    return groups;
  }, new Map());

  return Array.from(proposalsByTrack.entries())
    .map(([localTrackId, trackProposals]) => ({
      candidates: sortProposalCandidates(trackProposals),
      localTrackId,
    }))
    .sort((left, right) => {
      const scoreDifference = right.candidates[0].score - left.candidates[0].score;

      if (scoreDifference !== 0) {
        return scoreDifference;
      }

      return left.localTrackId - right.localTrackId;
    });
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

function getLocalTrackLabel(proposal: LinkProposal) {
  return proposal.local_file_path.split("/").pop() || proposal.local_file_path;
}

function MetadataValue({ fallback = "—", value }: { fallback?: string; value: string | null }) {
  if (!value) {
    return <span className="italic text-ctp-overlay1">{fallback}</span>;
  }

  return value;
}

function ProposalMetadataRow({
  fallback,
  label,
  value,
}: {
  fallback?: string;
  label: string;
  value: string | null;
}) {
  return (
    <div className="grid min-w-0 grid-cols-[82px_minmax(0,1fr)] items-baseline gap-2">
      <dt className={`${textClasses.detail} text-ctp-subtext0`}>{label}</dt>
      <dd className={`min-w-0 truncate ${textClasses.caption}`}>
        <MetadataValue fallback={fallback} value={value} />
      </dd>
    </div>
  );
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
  const queryClient = useQueryClient();
  const proposalsQuery = useLinkProposalsQuery();
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
  const proposalGroups = useMemo(() => groupLinkProposalsByLocalTrack(proposals ?? []), [proposals]);
  const activeApproveProposalId = approveMutation.isPending ? String(approveMutation.variables) : null;
  const activeRejectProposalId = rejectMutation.isPending ? String(rejectMutation.variables) : null;
  const failedApproveProposalId = approveMutation.isError ? String(approveMutation.variables) : null;
  const failedRejectProposalId = rejectMutation.isError ? String(rejectMutation.variables) : null;
  const renderProposalFrame = (children: ReactNode) => (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Proposal queue</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            {proposalsQuery.isSuccess
              ? `${proposalCount} pending suggestions sorted by confidence.`
              : "Pending suggestions sorted by confidence."}
          </p>
        </div>
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
    return renderProposalFrame(
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <EmptyStateCard
          body="Pending local-to-streaming match suggestions will appear here as matching jobs finish."
          className={`${layoutClasses.emptyStateNarrow} text-left`}
          title="Proposal queue"
        />
      </div>,
    );
  }

  return renderProposalFrame(
    <div className="min-h-0 flex-1 overflow-y-auto pr-1">
      <ul className="grid gap-3">
        {proposalGroups.map((proposalGroup) => (
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
      <div className="grid gap-4">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="min-w-0">
            <p className={`${textClasses.eyebrow} tracking-normal text-ctp-subtext0`}>Local track</p>
            <dl className="mt-2 grid gap-2">
              <ProposalMetadataRow label="Filename" value={getLocalTrackLabel(topProposal)} />
              <ProposalMetadataRow label="Title" value={topProposal.local_title} />
              <ProposalMetadataRow label="Artist" value={topProposal.local_artist} />
              <ProposalMetadataRow label="Album" value={topProposal.local_album} />
            </dl>
          </div>
          <div className="min-w-0 md:border-l md:border-ctp-surface0 md:pl-4">
            <p className={`${textClasses.eyebrow} tracking-normal text-ctp-subtext0`}>Streaming track</p>
            <dl className="mt-2 grid gap-2">
              <ProposalMetadataRow label="Title" value={topProposal.streaming_title} />
              <ProposalMetadataRow label="Artist" value={topProposal.streaming_artist} />
              <ProposalMetadataRow fallback="Album unavailable" label="Album" value={topProposal.streaming_album} />
            </dl>
          </div>
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
