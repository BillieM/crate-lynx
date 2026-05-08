import { useMemo, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";
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

type OptimisticProposalMutationContext = {
  previousProposalQueries: [readonly unknown[], LinkProposalsResponse | undefined][];
};

function clampPercentage(matchPercentage: number) {
  return Math.max(0, Math.min(100, matchPercentage));
}

function sortLinkProposals(proposals: LinkProposal[]) {
  return [...proposals].sort((left, right) => {
    if (right.score !== left.score) {
      return right.score - left.score;
    }

    return left.id - right.id;
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

function ProposalComparisonRow({
  label,
  localValue,
  streamingFallback,
  streamingValue,
}: {
  label: string;
  localValue: string | null;
  streamingFallback?: string;
  streamingValue: string | null;
}) {
  return (
    <div className="grid min-w-0 gap-1 rounded-[8px] bg-ctp-surface0/48 px-2.5 py-2 sm:grid-cols-[70px_minmax(0,1fr)_minmax(0,1fr)] sm:items-baseline sm:gap-3 lg:contents">
      <dt className={`${textClasses.detail} text-ctp-subtext0 lg:py-0.5`}>{label}</dt>
      <dd className={`min-w-0 truncate ${textClasses.caption} lg:py-0.5`}>
        <span className={`${textClasses.microEyebrow} mb-1 block text-ctp-overlay1 sm:hidden`}>Local</span>
        <MetadataValue value={localValue} />
      </dd>
      <dd className={`min-w-0 truncate ${textClasses.caption} lg:py-0.5`}>
        <span className={`${textClasses.microEyebrow} mb-1 block text-ctp-overlay1 sm:hidden`}>Streaming</span>
        <MetadataValue fallback={streamingFallback} value={streamingValue} />
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

function getProposalScoreTone(scorePercentage: number): PillTone {
  if (scorePercentage >= 85) {
    return "success";
  }

  if (scorePercentage >= 50) {
    return "pending";
  }

  return "neutral";
}

function getConfidenceLabel(confidenceBand: LinkProposal["confidence_band"]) {
  if (confidenceBand === "high") {
    return "High confidence";
  }

  if (confidenceBand === "medium") {
    return "Medium confidence";
  }

  return "Low confidence";
}

function getConfidenceDotColorClass(confidenceBand: LinkProposal["confidence_band"]) {
  if (confidenceBand === "high") {
    return "bg-ctp-green";
  }

  if (confidenceBand === "medium") {
    return "bg-ctp-yellow";
  }

  return "bg-ctp-red";
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
  const sortedProposals = useMemo(() => sortLinkProposals(proposals ?? []), [proposals]);
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
        {sortedProposals.map((proposal) => (
          <ProposalRow
            activeApproveProposalId={activeApproveProposalId}
            activeRejectProposalId={activeRejectProposalId}
            failedApproveProposalId={failedApproveProposalId}
            failedRejectProposalId={failedRejectProposalId}
            key={proposal.id}
            onApprove={(proposalId) => approveMutation.mutate(proposalId)}
            onReject={(proposalId) => rejectMutation.mutate(proposalId)}
            proposal={proposal}
          />
        ))}
      </ul>
    </div>,
  );
}

function ProposalRow({
  activeApproveProposalId,
  activeRejectProposalId,
  failedApproveProposalId,
  failedRejectProposalId,
  onApprove,
  onReject,
  proposal,
}: {
  activeApproveProposalId: string | null;
  activeRejectProposalId: string | null;
  failedApproveProposalId: string | null;
  failedRejectProposalId: string | null;
  onApprove: (proposalId: number) => void;
  onReject: (proposalId: number) => void;
  proposal: LinkProposal;
}) {
  const scorePercentage = getProposalScorePercentage(proposal.score);
  const actionError =
    failedApproveProposalId === String(proposal.id)
      ? "Approve failed."
      : failedRejectProposalId === String(proposal.id)
        ? "Reject failed."
        : null;
  const isApproving = activeApproveProposalId === String(proposal.id);
  const isRejecting = activeRejectProposalId === String(proposal.id);
  const isActionPending = isApproving || isRejecting;

  return (
    <li
      aria-label={`Proposal ${proposal.id}: ${getLocalTrackLabel(proposal)} to ${proposal.streaming_title}`}
      className={surfaceClasses.rowCardCompact}
    >
      <article className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1fr)_150px] xl:items-start">
        <dl className="grid min-w-0 gap-2 lg:grid-cols-[70px_minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
          <div className="hidden lg:block" aria-hidden="true" />
          <div className="min-w-0">
            <p className={`${textClasses.eyebrow} tracking-normal text-ctp-subtext0`}>Local track</p>
            <p className={`mt-1 truncate font-mono ${textClasses.finePrint} text-ctp-overlay1`}>
              {getLocalTrackLabel(proposal)}
            </p>
          </div>
          <div className="min-w-0 border-t border-ctp-surface0 pt-2 sm:border-t-0 sm:pt-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <p className={`${textClasses.eyebrow} tracking-normal text-ctp-subtext0`}>Streaming track</p>
              <Pill className="tabular-nums" tone={getProposalScoreTone(scorePercentage)}>
                {formatProposalScore(proposal.score)}
              </Pill>
              <Pill tone={getMatchMethodTone(proposal.match_method)}>
                {getMatchMethodLabel(proposal.match_method)}
              </Pill>
              <span className={`inline-flex items-center gap-1 ${textClasses.finePrint} font-medium text-ctp-subtext0`}>
                <span
                  aria-hidden="true"
                  className={`h-1.5 w-1.5 rounded-full ${getConfidenceDotColorClass(proposal.confidence_band)}`}
                />
                {getConfidenceLabel(proposal.confidence_band)}
              </span>
            </div>
          </div>

          <ProposalComparisonRow
            label="Title"
            localValue={proposal.local_title}
            streamingValue={proposal.streaming_title}
          />
          <ProposalComparisonRow
            label="Artist"
            localValue={proposal.local_artist}
            streamingValue={proposal.streaming_artist}
          />
          <ProposalComparisonRow
            label="Album"
            localValue={proposal.local_album}
            streamingFallback="Album unavailable"
            streamingValue={proposal.streaming_album}
          />
        </dl>

        <div className="flex flex-wrap items-center gap-2 border-t border-ctp-surface0 pt-2 xl:flex-col xl:items-stretch xl:border-t-0 xl:pt-0">
          <ActionButton
            className={`${controlClasses.actionButtonCompact} inline-flex items-center justify-center gap-1.5`}
            disabled={isActionPending}
            onClick={() => onApprove(proposal.id)}
            tone="success"
          >
            <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            <span>{isApproving ? "Approving..." : "Approve"}</span>
            <span className="sr-only"> proposal {proposal.id}</span>
          </ActionButton>
          <ActionButton
            className={`${controlClasses.actionButtonCompact} inline-flex items-center justify-center gap-1.5`}
            disabled={isActionPending}
            onClick={() => onReject(proposal.id)}
            tone="danger"
          >
            <XCircle aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            <span>{isRejecting ? "Rejecting..." : "Reject"}</span>
            <span className="sr-only"> proposal {proposal.id}</span>
          </ActionButton>
          {actionError ? (
            <p className={`font-medium text-ctp-red ${textClasses.finePrint} xl:text-right`}>{actionError}</p>
          ) : null}
        </div>
      </article>
    </li>
  );
}
