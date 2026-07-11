import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, XCircle } from "lucide-react";
import { useLocation } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { FilterChipGroup, type FilterChipOption } from "../../components/FilterChipGroup";
import { Pill, type PillTone } from "../../components/Pill";
import { ApiRequestError } from "../../lib/api";
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
import { proposalDetailQueryKey, useProposalDetailQuery } from "./queries";

const proposalsQueryKey = playlistQueryKeys.proposalPages();
type ConfidenceFilter = "all" | LinkProposal["confidence_band"];

const confidenceFilterDefinitions: Array<Omit<FilterChipOption<ConfidenceFilter>, "count">> = [
  { label: "All confidence", tone: "all", value: "all" },
  { label: "High", tone: "linked", value: "high" },
  { label: "Medium", tone: "pending", value: "medium" },
  { label: "Low", tone: "unlinked", value: "low" },
];

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

function proposalSearchText(proposal: LinkProposal) {
  return [
    proposal.local_file_path,
    proposal.local_title,
    proposal.local_artist,
    proposal.local_album,
    proposal.streaming_title,
    proposal.streaming_artist,
    proposal.streaming_album,
    proposal.match_method,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function groupProposalsByLocalTrack(proposals: LinkProposal[]) {
  const groups = new Map<number, LinkProposal[]>();
  for (const proposal of proposals) {
    const candidates = groups.get(proposal.local_track_id) ?? [];
    candidates.push(proposal);
    groups.set(proposal.local_track_id, candidates);
  }
  return Array.from(groups.values());
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
  showLocalValue = true,
  streamingFallback,
  streamingValue,
}: {
  label: string;
  localValue: string | null;
  showLocalValue?: boolean;
  streamingFallback?: string;
  streamingValue: string | null;
}) {
  return (
    <div className="grid min-w-0 gap-1.5 rounded-[8px] bg-ctp-surface0/48 px-2.5 py-2">
      <dt className={`${textClasses.detail} text-ctp-subtext0`}>{label}</dt>
      <dd className="grid min-w-0 gap-1">
        {showLocalValue ? (
          <div className="grid min-w-0 grid-cols-[1.25rem_minmax(0,1fr)] items-baseline gap-1.5">
            <span aria-hidden="true" className="text-[10px] font-semibold uppercase text-ctp-overlay1">
              L
            </span>
            <span className="sr-only">Local: </span>
            <span className={`min-w-0 truncate ${textClasses.caption}`}>
              <MetadataValue value={localValue} />
            </span>
          </div>
        ) : null}
        <div className={showLocalValue ? "grid min-w-0 grid-cols-[1.25rem_minmax(0,1fr)] items-baseline gap-1.5" : "min-w-0"}>
          {showLocalValue ? (
            <span aria-hidden="true" className="text-[10px] font-semibold uppercase text-ctp-overlay1">
              S
            </span>
          ) : null}
          <span className="sr-only">Streaming: </span>
          <span className={`min-w-0 truncate ${textClasses.caption}`}>
            <MetadataValue fallback={streamingFallback} value={streamingValue} />
          </span>
        </div>
      </dd>
    </div>
  );
}

function ProposalTask({
  activeApproveProposalId,
  activeRejectProposalId,
  failedApproveProposalId,
  failedRejectProposalId,
  onApprove,
  onReject,
  proposals,
}: {
  activeApproveProposalId: string | null;
  activeRejectProposalId: string | null;
  failedApproveProposalId: string | null;
  failedRejectProposalId: string | null;
  onApprove: (proposalId: number) => void;
  onReject: (proposalId: number) => void;
  proposals: LinkProposal[];
}) {
  const localTrack = proposals[0];

  return (
    <li
      aria-label={`Local track task ${getLocalTrackLabel(localTrack)}`}
      className={surfaceClasses.rowCardCompact}
    >
      <article className="grid gap-3">
        <header className="grid min-w-0 gap-2 border-b border-ctp-surface0 pb-2 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
          <div className="min-w-0">
            <p className={`${textClasses.eyebrow} tracking-normal text-ctp-subtext0`}>Local track</p>
            <p className={`mt-1 truncate ${textClasses.label}`}>
              {localTrack.local_title ?? getLocalTrackLabel(localTrack)}
            </p>
            <p className={`mt-0.5 truncate ${textClasses.caption}`}>
              {[localTrack.local_artist, localTrack.local_album].filter(Boolean).join(" · ") || "Metadata unavailable"}
            </p>
            {localTrack.local_title ? (
              <p className={`mt-1 truncate font-mono ${textClasses.finePrint} text-ctp-overlay1`}>
                {getLocalTrackLabel(localTrack)}
              </p>
            ) : null}
          </div>
          <Pill className="w-fit tabular-nums" tone="neutral">
            {proposals.length} {proposals.length === 1 ? "candidate" : "alternatives"}
          </Pill>
        </header>
        <ol aria-label={`Ranked alternatives for ${getLocalTrackLabel(localTrack)}`} className="grid gap-2">
          {proposals.map((proposal, index) => (
            <ProposalRow
              activeApproveProposalId={activeApproveProposalId}
              activeRejectProposalId={activeRejectProposalId}
              failedApproveProposalId={failedApproveProposalId}
              failedRejectProposalId={failedRejectProposalId}
              key={proposal.id}
              onApprove={onApprove}
              onReject={onReject}
              proposal={proposal}
              rank={index + 1}
              showLocalTrack={false}
            />
          ))}
        </ol>
      </article>
    </li>
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
  const location = useLocation();
  const queryClient = useQueryClient();
  const pathProposalId = /^\/proposals\/(?<proposalId>\d+)\/?$/.exec(location.pathname)?.groups?.proposalId ?? null;
  const queryProposalId = new URLSearchParams(location.search).get("proposal_id");
  const focusedProposalId = pathProposalId ?? (queryProposalId && /^\d+$/.test(queryProposalId) ? queryProposalId : null);
  const focusedProposalRef = useRef<HTMLDivElement>(null);
  const [confidenceFilter, setConfidenceFilter] = useState<ConfidenceFilter>("all");
  const [matchMethodFilter, setMatchMethodFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const proposalDetailQuery = useProposalDetailQuery(focusedProposalId);
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
      if (focusedProposalId !== null) {
        await queryClient.invalidateQueries({ queryKey: proposalDetailQueryKey(focusedProposalId) });
      }
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
      if (focusedProposalId !== null) {
        await queryClient.invalidateQueries({ queryKey: proposalDetailQueryKey(focusedProposalId) });
      }
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
  const sortedProposals = useMemo(() => sortLinkProposals(proposals), [proposals]);
  const matchMethods = useMemo(
    () => Array.from(new Set(proposals.map((proposal) => proposal.match_method))).sort(),
    [proposals],
  );
  const normalizedSearchQuery = searchQuery.trim().toLowerCase();
  const filteredProposals = useMemo(
    () =>
      sortedProposals.filter(
        (proposal) =>
          (confidenceFilter === "all" || proposal.confidence_band === confidenceFilter) &&
          (matchMethodFilter === "all" || proposal.match_method === matchMethodFilter) &&
          (normalizedSearchQuery === "" || proposalSearchText(proposal).includes(normalizedSearchQuery)),
      ),
    [confidenceFilter, matchMethodFilter, normalizedSearchQuery, sortedProposals],
  );
  const proposalTasks = useMemo(() => groupProposalsByLocalTrack(filteredProposals), [filteredProposals]);
  const confidenceFilterOptions = confidenceFilterDefinitions.map((filter) => ({
    ...filter,
    count:
      filter.value === "all"
        ? proposals.length
        : proposals.filter((proposal) => proposal.confidence_band === filter.value).length,
  }));
  const hasActiveFilters = confidenceFilter !== "all" || matchMethodFilter !== "all" || normalizedSearchQuery !== "";
  const activeApproveProposalId = approveMutation.isPending ? String(approveMutation.variables) : null;
  const activeRejectProposalId = rejectMutation.isPending ? String(rejectMutation.variables) : null;
  const failedApproveProposalId = approveMutation.isError ? String(approveMutation.variables) : null;
  const failedRejectProposalId = rejectMutation.isError ? String(rejectMutation.variables) : null;
  useEffect(() => {
    if (focusedProposalId !== null && proposalDetailQuery.isSuccess) {
      focusedProposalRef.current?.focus();
    }
  }, [focusedProposalId, proposalDetailQuery.isSuccess]);

  const renderProposalFrame = (children: ReactNode, description?: string) => (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Proposal queue</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            {description ?? (proposalsQuery.isSuccess
              ? hasUnloadedProposals
                ? `Showing ${proposalCount} of ${totalProposalCount} pending suggestions sorted by confidence.`
                : `${proposalCount} pending suggestions sorted by confidence.`
              : "Pending suggestions sorted by confidence.")}
          </p>
        </div>
      </div>
      {focusedProposalId === null && proposalsQuery.isSuccess && proposalCount > 0 ? (
        <div className={`${surfaceClasses.insetPanel} grid gap-3 px-3 py-3`}>
          <div className="grid gap-2 md:grid-cols-[minmax(12rem,1fr)_minmax(10rem,0.4fr)]">
            <label className="grid gap-1">
              <span className={textClasses.detail}>Search loaded proposals</span>
              <input
                className={`${controlClasses.searchFrame} min-h-9 px-3 ${textClasses.input} text-ctp-text outline-none`}
                onChange={(event) => setSearchQuery(event.currentTarget.value)}
                placeholder="Local file, artist, album, or streaming track"
                type="search"
                value={searchQuery}
              />
            </label>
            <label className="grid gap-1">
              <span className={textClasses.detail}>Match method</span>
              <select
                className={`${controlClasses.searchFrame} min-h-9 px-3 ${textClasses.input} text-ctp-text outline-none`}
                onChange={(event) => setMatchMethodFilter(event.currentTarget.value)}
                value={matchMethodFilter}
              >
                <option value="all">All methods</option>
                {matchMethods.map((method) => (
                  <option key={method} value={method}>
                    {getMatchMethodLabel(method)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <FilterChipGroup
              activeValue={confidenceFilter}
              ariaLabel="Proposal confidence filters"
              density="compact"
              onValueChange={setConfidenceFilter}
              options={confidenceFilterOptions}
            />
            {hasActiveFilters ? (
              <ActionButton
                className={controlClasses.actionButtonCompact}
                onClick={() => {
                  setConfidenceFilter("all");
                  setMatchMethodFilter("all");
                  setSearchQuery("");
                }}
              >
                Clear filters
              </ActionButton>
            ) : null}
          </div>
        </div>
      ) : null}
      {children}
    </section>
  );

  if (focusedProposalId !== null) {
    if (proposalDetailQuery.isPending) {
      return renderProposalFrame(
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <EmptyStateCard body={`Loading proposal ${focusedProposalId}.`} role="status" title="Locating proposal" />
        </div>,
        `Locating proposal ${focusedProposalId}.`,
      );
    }

    if (proposalDetailQuery.isError) {
      const isMissing =
        proposalDetailQuery.error instanceof ApiRequestError && proposalDetailQuery.error.status === 404;
      return renderProposalFrame(
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <EmptyStateCard
            body={
              isMissing
                ? `Proposal ${focusedProposalId} does not exist or is no longer available.`
                : `Proposal ${focusedProposalId} could not be loaded. Try again from the proposal queue.`
            }
            role="alert"
            title={isMissing ? "Proposal not found" : "Proposal unavailable"}
            tone="error"
          />
        </div>,
        `Exact proposal ${focusedProposalId}.`,
      );
    }

    const focusedProposal = proposalDetailQuery.data;
    const stateCopy = {
      pending: {
        body: "This exact proposal is pending and ready for review.",
        title: "Proposal ready for review",
      },
      resolved: {
        body: "This proposal has already been approved or rejected. Its original comparison remains available below.",
        title: "Proposal already resolved",
      },
      stale: {
        body: "This proposal can no longer be acted on because its local track or streaming target changed state.",
        title: "Proposal is stale",
      },
    }[focusedProposal.state];

    return renderProposalFrame(
      <div
        aria-label={`Focused proposal ${focusedProposal.id}`}
        className="min-h-0 flex-1 overflow-y-auto pr-1 outline-none focus-visible:ring-2 focus-visible:ring-ctp-mauve"
        ref={focusedProposalRef}
        tabIndex={-1}
      >
        <div className={`${surfaceClasses.insetPanel} mb-3 px-3 py-2`} role="status">
          <p className={textClasses.label}>{stateCopy.title}</p>
          <p className={`mt-1 ${textClasses.caption}`}>{stateCopy.body}</p>
        </div>
        <ul>
          <ProposalRow
            activeApproveProposalId={activeApproveProposalId}
            activeRejectProposalId={activeRejectProposalId}
            canAct={focusedProposal.state === "pending"}
            failedApproveProposalId={failedApproveProposalId}
            failedRejectProposalId={failedRejectProposalId}
            onApprove={(proposalId) => approveMutation.mutate(proposalId)}
            onReject={(proposalId) => rejectMutation.mutate(proposalId)}
            proposal={focusedProposal}
          />
        </ul>
      </div>,
      `Showing exact proposal ${focusedProposal.id}.`,
    );
  }

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

  if (filteredProposals.length === 0) {
    return renderProposalFrame(
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <EmptyStateCard
          body="No loaded proposals match the current search and filters. Clear or broaden them to return to the queue."
          className={`${layoutClasses.emptyStateNarrow} text-left`}
          role="status"
          title="No matching proposals"
        />
      </div>,
      `0 of ${proposalCount} loaded candidates match the current filters. ${proposalCount} of ${totalProposalCount} total candidates are loaded.`,
    );
  }

  return renderProposalFrame(
    <div className="min-h-0 flex-1 overflow-y-auto pr-1">
      <ul aria-label="Local-track proposal tasks" className="grid gap-3">
        {proposalTasks.map((taskProposals) => (
          <ProposalTask
            activeApproveProposalId={activeApproveProposalId}
            activeRejectProposalId={activeRejectProposalId}
            failedApproveProposalId={failedApproveProposalId}
            failedRejectProposalId={failedRejectProposalId}
            key={taskProposals[0].local_track_id}
            onApprove={(proposalId) => approveMutation.mutate(proposalId)}
            onReject={(proposalId) => rejectMutation.mutate(proposalId)}
            proposals={taskProposals}
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
    `${proposalTasks.length} local-track ${proposalTasks.length === 1 ? "task" : "tasks"} shown from ${filteredProposals.length} matching loaded candidates. ${proposalCount} of ${totalProposalCount} total candidates are loaded.`,
  );
}

function ProposalRow({
  activeApproveProposalId,
  activeRejectProposalId,
  canAct = true,
  failedApproveProposalId,
  failedRejectProposalId,
  onApprove,
  onReject,
  proposal,
  rank,
  showLocalTrack = true,
}: {
  activeApproveProposalId: string | null;
  activeRejectProposalId: string | null;
  canAct?: boolean;
  failedApproveProposalId: string | null;
  failedRejectProposalId: string | null;
  onApprove: (proposalId: number) => void;
  onReject: (proposalId: number) => void;
  proposal: LinkProposal;
  rank?: number;
  showLocalTrack?: boolean;
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
      className={showLocalTrack ? surfaceClasses.rowCardCompact : `${surfaceClasses.insetPanel} grid gap-2 px-3 py-2.5`}
    >
      <article className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1fr)_150px] xl:items-start">
        <div className="grid min-w-0 gap-2.5">
          <div className={`grid min-w-0 gap-2 ${showLocalTrack ? "md:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]" : ""} md:items-start`}>
            {showLocalTrack ? <div className="min-w-0">
              <p className={`${textClasses.eyebrow} tracking-normal text-ctp-subtext0`}>Local track</p>
              <p className={`mt-1 truncate font-mono ${textClasses.finePrint} text-ctp-overlay1`}>
                {getLocalTrackLabel(proposal)}
              </p>
            </div> : null}
            <div className={`min-w-0 ${showLocalTrack ? "border-t border-ctp-surface0 pt-2 md:border-t-0 md:pt-0" : ""}`}>
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <p className={`${textClasses.eyebrow} tracking-normal text-ctp-subtext0`}>
                  {rank ? `Alternative ${rank}` : "Streaming track"}
                </p>
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
              showLocalValue={showLocalTrack}
              streamingValue={proposal.streaming_title}
            />
            <ProposalComparisonField
              label="Artist"
              localValue={proposal.local_artist}
              showLocalValue={showLocalTrack}
              streamingValue={proposal.streaming_artist}
            />
            <ProposalComparisonField
              label="Album"
              localValue={proposal.local_album}
              showLocalValue={showLocalTrack}
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
          {canAct ? (
            <>
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
            </>
          ) : null}
          {actionError ? (
            <p className={`font-medium text-ctp-red ${textClasses.finePrint} xl:text-right`}>{actionError}</p>
          ) : null}
        </div>
      </article>
    </li>
  );
}
