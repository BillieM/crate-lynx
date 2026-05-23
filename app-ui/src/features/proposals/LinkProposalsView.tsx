import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, XCircle } from "lucide-react";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { Pill, type PillTone } from "../../components/Pill";
import { getLocalTrackLabel, getMatchMethodLabel } from "../../lib/formatters";
import { createOptimisticMutation, type OptimisticMutationSnapshot } from "../../lib/optimisticMutation";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import { MatchInspectionPanel } from "../matching/MatchInspectionPanel";
import {
  type ApproveLinkProposalResponse,
  approveLinkProposal,
  type LinkProposal,
  type LinkProposalsResponse,
  invalidatePlaylistLinkQueries,
  playlistQueryKeys,
  rejectLinkProposal,
  type RejectLinkProposalResponse,
  useLinkProposalsInfiniteQuery,
} from "../playlists/queries";

const proposalsQueryKey = playlistQueryKeys.proposalPages();

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

function removeProposalCandidateFromCache(
  current: InfiniteData<LinkProposalsResponse> | undefined,
  proposalId: number | string,
  snapshots: OptimisticMutationSnapshot<InfiniteData<LinkProposalsResponse>>[],
  options: { removeLocalTrackGroup: boolean },
): InfiniteData<LinkProposalsResponse> | undefined {
  if (!current) {
    return current;
  }

  const targetLocalTrackIds = new Set(
    snapshots.flatMap(([, data]) =>
      data?.pages.flatMap((page) =>
        page.proposals
          .filter((proposal) => String(proposal.id) === String(proposalId))
          .map((proposal) => proposal.local_track_id),
      ) ?? [],
    ),
  );
  let totalRemovedCount = 0;
  const nextPages = current.pages.map((page) => {
    let pageRemovedCount = 0;
    const proposals = page.proposals.filter((proposal) => {
      if (String(proposal.id) === String(proposalId)) {
        pageRemovedCount += 1;
        return false;
      }

      if (options.removeLocalTrackGroup && targetLocalTrackIds.has(proposal.local_track_id)) {
        pageRemovedCount += 1;
        return false;
      }

      return true;
    });
    totalRemovedCount += pageRemovedCount;

    return {
      ...page,
      proposals,
      returned_count: Math.max(0, page.returned_count - pageRemovedCount),
    };
  });

  return {
    ...current,
    pages: nextPages.map((page) => ({
      ...page,
      total_count: Math.max(0, page.total_count - totalRemovedCount),
    })),
  };
}

function MetadataValue({ fallback = "—", value }: { fallback?: string; value: string | null }) {
  if (!value) {
    return <span className="italic text-ctp-overlay1">{fallback}</span>;
  }

  return value;
}

function ProposalComparisonField({
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
    <div className="grid min-w-0 gap-1.5 rounded-[8px] bg-ctp-surface0/48 px-2.5 py-2">
      <dt className={`${textClasses.detail} text-ctp-subtext0`}>{label}</dt>
      <dd className="grid min-w-0 gap-1">
        <div className="grid min-w-0 grid-cols-[1.25rem_minmax(0,1fr)] items-baseline gap-1.5">
          <span aria-hidden="true" className="text-[10px] font-semibold uppercase text-ctp-overlay1">
            L
          </span>
          <span className="sr-only">Local: </span>
          <span className={`min-w-0 truncate ${textClasses.caption}`}>
            <MetadataValue value={localValue} />
          </span>
        </div>
        <div className="grid min-w-0 grid-cols-[1.25rem_minmax(0,1fr)] items-baseline gap-1.5">
          <span aria-hidden="true" className="text-[10px] font-semibold uppercase text-ctp-overlay1">
            S
          </span>
          <span className="sr-only">Streaming: </span>
          <span className={`min-w-0 truncate ${textClasses.caption}`}>
            <MetadataValue fallback={streamingFallback} value={streamingValue} />
          </span>
        </div>
      </dd>
    </div>
  );
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
  const proposalsQuery = useLinkProposalsInfiniteQuery();
  const approveMutation = useMutation({
    ...createOptimisticMutation<
      ApproveLinkProposalResponse,
      Error,
      number | string,
      InfiniteData<LinkProposalsResponse>
    >({
      mutationFn: approveLinkProposal,
      optimisticUpdate: (current, proposalId, snapshots) =>
        removeProposalCandidateFromCache(current, proposalId, snapshots, { removeLocalTrackGroup: true }),
      queryClient,
      queryKey: proposalsQueryKey,
    }),
    onSettled: async () => {
      await invalidatePlaylistLinkQueries(queryClient);
    },
  });
  const rejectMutation = useMutation({
    ...createOptimisticMutation<
      RejectLinkProposalResponse,
      Error,
      number | string,
      InfiniteData<LinkProposalsResponse>
    >({
      mutationFn: rejectLinkProposal,
      optimisticUpdate: (current, proposalId, snapshots) =>
        removeProposalCandidateFromCache(current, proposalId, snapshots, { removeLocalTrackGroup: false }),
      queryClient,
      queryKey: proposalsQueryKey,
    }),
    onSettled: async () => {
      await invalidatePlaylistLinkQueries(queryClient);
    },
  });
  const proposals = useMemo(
    () => proposalsQuery.data?.pages.flatMap((page) => page.proposals) ?? [],
    [proposalsQuery.data],
  );
  const proposalCount = proposals.length;
  const totalProposalCount = proposalsQuery.data?.pages[0]?.total_count ?? proposalCount;
  const hasMoreProposals = proposalsQuery.hasNextPage;
  const hasUnloadedProposals = totalProposalCount > proposalCount;
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
              ? hasUnloadedProposals
                ? `Showing ${proposalCount} of ${totalProposalCount} pending suggestions sorted by confidence.`
                : `${proposalCount} pending suggestions sorted by confidence.`
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
      {hasMoreProposals ? (
        <div className="flex justify-center py-3">
          <ActionButton
            className={`${controlClasses.actionButtonCompact} inline-flex items-center justify-center gap-1.5`}
            disabled={proposalsQuery.isFetchingNextPage}
            onClick={() => {
              void proposalsQuery.fetchNextPage();
            }}
          >
            {proposalsQuery.isFetchingNextPage ? "Loading..." : "Load more"}
          </ActionButton>
        </div>
      ) : null}
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
  const [isExpanded, setIsExpanded] = useState(false);
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
        <div className="grid min-w-0 gap-2.5">
          <div className="grid min-w-0 gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)] md:items-start">
            <div className="min-w-0">
              <p className={`${textClasses.eyebrow} tracking-normal text-ctp-subtext0`}>Local track</p>
              <p className={`mt-1 truncate font-mono ${textClasses.finePrint} text-ctp-overlay1`}>
                {getLocalTrackLabel(proposal)}
              </p>
            </div>
            <div className="min-w-0 border-t border-ctp-surface0 pt-2 md:border-t-0 md:pt-0">
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
              <p className={`mt-1 truncate ${textClasses.finePrint} font-medium text-ctp-text`}>
                {proposal.streaming_title}
              </p>
            </div>
          </div>

          <dl className="grid min-w-0 gap-2 md:grid-cols-3">
            <ProposalComparisonField
              label="Title"
              localValue={proposal.local_title}
              streamingValue={proposal.streaming_title}
            />
            <ProposalComparisonField
              label="Artist"
              localValue={proposal.local_artist}
              streamingValue={proposal.streaming_artist}
            />
            <ProposalComparisonField
              label="Album"
              localValue={proposal.local_album}
              streamingFallback="Album unavailable"
              streamingValue={proposal.streaming_album}
            />
          </dl>
          {isExpanded ? (
            <MatchInspectionPanel
              localAudio={{
                label: `Listen to ${proposal.local_title ?? getLocalTrackLabel(proposal)}`,
                localTrackId: proposal.local_track_id,
              }}
              streamingTracks={[
                {
                  artist: proposal.streaming_artist,
                  providerTrackId: proposal.streaming_provider_track_id,
                  title: proposal.streaming_title,
                },
              ]}
            />
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-ctp-surface0 pt-2 xl:flex-col xl:items-stretch xl:border-t-0 xl:pt-0">
          <ActionButton
            aria-expanded={isExpanded}
            className={`${controlClasses.actionButtonCompact} inline-flex items-center justify-center gap-1.5`}
            onClick={() => setIsExpanded((current) => !current)}
          >
            <ChevronDown
              aria-hidden="true"
              className={`h-3.5 w-3.5 transition-transform ${isExpanded ? "rotate-180" : ""}`}
              strokeWidth={1.9}
            />
            <span>{isExpanded ? "Hide details" : "Inspect"}</span>
            <span className="sr-only"> proposal {proposal.id}</span>
          </ActionButton>
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
