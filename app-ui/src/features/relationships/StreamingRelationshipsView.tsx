import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { ChevronDown, GitBranch, Link2, RefreshCw, XCircle } from "lucide-react";

import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { Pill, type PillTone } from "../../components/Pill";
import { formatDuration, getMatchMethodLabel } from "../../lib/formatters";
import { createOptimisticMutation } from "../../lib/optimisticMutation";
import { controlClasses, layoutClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import { LocalTrackAudioPreview } from "../localTracks/LocalTrackAudioPreview";
import { MatchInspectionPanel } from "../matching/MatchInspectionPanel";
import {
  acceptStreamingRelationshipSuggestion,
  type AcceptStreamingRelationshipSuggestionInput,
  type AcceptStreamingRelationshipSuggestionResponse,
  generateStreamingRelationshipSuggestions,
  invalidateStreamingRelationshipMutationQueries,
  invalidateStreamingRelationshipSuggestionQueries,
  rejectStreamingRelationshipSuggestion,
  type RejectStreamingRelationshipSuggestionResponse,
  type StreamingRelationshipSuggestion,
  type StreamingRelationshipSuggestionsResponse,
  streamingRelationshipQueryKeys,
  useStreamingRelationshipSuggestionsInfiniteQuery,
} from "./queries";

const relationshipSuggestionsQueryKey = streamingRelationshipQueryKeys.suggestionPages();

type RelationshipTrack = StreamingRelationshipSuggestion["first_track"];
type RelationshipLocalLink = NonNullable<StreamingRelationshipSuggestion["first_link"]>;
type RelationshipActionType = StreamingRelationshipSuggestion["relationship_type"];

function sortRelationshipSuggestions(suggestions: StreamingRelationshipSuggestion[]) {
  return [...suggestions].sort((left, right) => {
    if (right.score !== left.score) {
      return right.score - left.score;
    }

    return left.id - right.id;
  });
}

function removeRelationshipSuggestionFromCache(
  current: InfiniteData<StreamingRelationshipSuggestionsResponse> | undefined,
  suggestionId: number | string,
): InfiniteData<StreamingRelationshipSuggestionsResponse> | undefined {
  if (!current) {
    return current;
  }

  let totalRemovedCount = 0;
  const nextPages = current.pages.map((page) => {
    const suggestions = page.suggestions.filter((suggestion) => String(suggestion.id) !== String(suggestionId));
    const pageRemovedCount = page.suggestions.length - suggestions.length;
    totalRemovedCount += pageRemovedCount;

    return {
      ...page,
      returned_count: Math.max(0, page.returned_count - pageRemovedCount),
      suggestions,
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

function clampPercentage(matchPercentage: number) {
  return Math.max(0, Math.min(100, matchPercentage));
}

function formatRelationshipScore(score: number) {
  return `${Math.round(score * 100)}%`;
}

function getRelationshipScoreTone(score: number): PillTone {
  const scorePercentage = clampPercentage(score * 100);

  if (scorePercentage >= 85) {
    return "success";
  }

  if (scorePercentage >= 50) {
    return "pending";
  }

  return "neutral";
}

function getRelationshipTypeLabel(relationshipType: StreamingRelationshipSuggestion["relationship_type"]) {
  return relationshipType === "equivalent" ? "Equivalent" : "Related";
}

function getRelationshipTypeTone(relationshipType: StreamingRelationshipSuggestion["relationship_type"]): PillTone {
  return relationshipType === "equivalent" ? "success" : "info";
}

function getMatchMethodTone(matchMethod: string): PillTone {
  return matchMethod.toLowerCase() === "isrc" ? "success" : "neutral";
}

function getConfidenceLabel(confidence: string) {
  const normalizedConfidence = confidence.trim().toLowerCase();

  if (normalizedConfidence === "high") {
    return "High confidence";
  }

  if (normalizedConfidence === "medium") {
    return "Medium confidence";
  }

  if (normalizedConfidence === "low") {
    return "Low confidence";
  }

  return `${confidence} confidence`;
}

function getConfidenceDotColorClass(confidence: string) {
  const normalizedConfidence = confidence.trim().toLowerCase();

  if (normalizedConfidence === "high") {
    return "bg-ctp-green";
  }

  if (normalizedConfidence === "medium") {
    return "bg-ctp-yellow";
  }

  if (normalizedConfidence === "low") {
    return "bg-ctp-red";
  }

  return "bg-ctp-overlay1";
}

function MetadataValue({ fallback = "Unavailable", value }: { fallback?: string; value: string | number | null }) {
  if (value === null || value === "") {
    return <span className="italic text-ctp-overlay1">{fallback}</span>;
  }

  return value;
}

function TrackMetadataField({
  fallback,
  label,
  value,
}: {
  fallback?: string;
  label: string;
  value: string | number | null;
}) {
  return (
    <div className="grid min-w-0 gap-1 rounded-[8px] bg-ctp-surface0/48 px-2.5 py-2">
      <dt className={`${textClasses.detail} text-ctp-subtext0`}>{label}</dt>
      <dd className={`min-w-0 truncate ${textClasses.caption}`}>
        <MetadataValue fallback={fallback} value={value} />
      </dd>
    </div>
  );
}

function getLocalLinkLabel(link: RelationshipLocalLink | null) {
  if (!link) {
    return "No local link";
  }

  if (link.local_file_path) {
    return link.local_file_path.split("/").pop() || link.local_file_path;
  }

  if (link.local_title) {
    return link.local_title;
  }

  return `Local track ${link.local_track_id}`;
}

function RelationshipTrackPanel({
  label,
  link,
  track,
}: {
  label: string;
  link: RelationshipLocalLink | null;
  track: RelationshipTrack;
}) {
  return (
    <div className="grid min-w-0 gap-2 rounded-[8px] bg-ctp-base/48 p-2.5 ring-1 ring-inset ring-ctp-surface0">
      <div className="min-w-0">
        <p className={`${textClasses.eyebrow} tracking-normal text-ctp-subtext0`}>{label}</p>
        <p className={`mt-1 truncate ${textClasses.proposalTitle}`}>{track.title}</p>
        <p className={`mt-0.5 truncate ${textClasses.finePrint} text-ctp-subtext0`}>{track.artist}</p>
      </div>

      <dl className="grid min-w-0 gap-2 sm:grid-cols-2">
        <TrackMetadataField label="Album" value={track.album} />
        <TrackMetadataField label="Duration" value={formatDuration(track.duration_ms)} />
        <TrackMetadataField label="ISRC" value={track.isrc} />
        <TrackMetadataField label="Year" value={track.year} />
        <TrackMetadataField label="Provider ID" value={track.provider_track_id} />
        <TrackMetadataField label="Local link" value={getLocalLinkLabel(link)} />
      </dl>
    </div>
  );
}

function WinnerSelection({
  onSelect,
  selectedWinnerId,
  suggestion,
}: {
  onSelect: (finalLinkId: number) => void;
  selectedWinnerId: number | null;
  suggestion: StreamingRelationshipSuggestion;
}) {
  if (suggestion.conflict_state !== "different_local_links") {
    return null;
  }

  const finalLinks = suggestion.conflict?.final_links ?? [];

  if (finalLinks.length === 0) {
    return null;
  }

  return (
    <fieldset className="grid gap-2 rounded-[8px] border border-ctp-yellow/30 bg-ctp-yellow/10 px-3 py-2">
      <legend className={`${textClasses.detail} text-ctp-yellow`}>Choose winning local link</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {finalLinks.map((link) => {
          const inputId = `relationship-${suggestion.id}-winner-${link.final_link_id}`;
          const localLinkLabel = getLocalLinkLabel(link);

          return (
            <div
              className="grid min-w-0 gap-2 rounded-[8px] bg-ctp-base/42 px-2.5 py-2 text-ctp-text ring-1 ring-inset ring-ctp-surface1/60"
              key={link.final_link_id}
            >
              <div className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-2">
                <input
                  checked={selectedWinnerId === link.final_link_id}
                  className="mt-0.5 h-3.5 w-3.5 accent-ctp-yellow"
                  id={inputId}
                  name={`relationship-${suggestion.id}-winner`}
                  onChange={() => onSelect(link.final_link_id)}
                  type="radio"
                  value={link.final_link_id}
                />
                <label className="grid min-w-0 cursor-pointer gap-1" htmlFor={inputId}>
                  <span className={`truncate ${textClasses.caption} font-medium text-ctp-text`}>
                    {localLinkLabel}
                  </span>
                  <span className={`truncate ${textClasses.finePrint} text-ctp-subtext0`}>
                    Final link {link.final_link_id}
                  </span>
                </label>
              </div>
              <LocalTrackAudioPreview
                className="pl-5"
                label={`Listen to ${localLinkLabel}`}
                localTrackId={link.local_track_id}
              />
            </div>
          );
        })}
      </div>
    </fieldset>
  );
}

function localAudioLinksForSuggestion(suggestion: StreamingRelationshipSuggestion) {
  const conflictLinks =
    suggestion.conflict_state === "different_local_links" ? suggestion.conflict?.final_links ?? [] : [];
  const candidateLinks =
    conflictLinks.length > 0 ? conflictLinks : [suggestion.first_link, suggestion.second_link];
  const seenLocalTrackIds = new Set<number>();

  return candidateLinks
    .filter((link): link is RelationshipLocalLink => link !== null)
    .filter((link) => {
      if (seenLocalTrackIds.has(link.local_track_id)) {
        return false;
      }
      seenLocalTrackIds.add(link.local_track_id);
      return true;
    });
}

function localAudiosForSuggestion(suggestion: StreamingRelationshipSuggestion) {
  return localAudioLinksForSuggestion(suggestion)
    .map((link) => ({
      label: `Listen to ${getLocalLinkLabel(link)}`,
      localTrackId: link.local_track_id,
    }));
}

export function StreamingRelationshipsView() {
  const queryClient = useQueryClient();
  const [selectedWinnerIds, setSelectedWinnerIds] = useState<Record<number, number>>({});
  const suggestionsQuery = useStreamingRelationshipSuggestionsInfiniteQuery();
  const acceptMutation = useMutation({
    ...createOptimisticMutation<
      AcceptStreamingRelationshipSuggestionResponse,
      Error,
      AcceptStreamingRelationshipSuggestionInput,
      InfiniteData<StreamingRelationshipSuggestionsResponse>
    >({
      mutationFn: acceptStreamingRelationshipSuggestion,
      optimisticUpdate: (current, variables) =>
        removeRelationshipSuggestionFromCache(current, variables.suggestionId),
      queryClient,
      queryKey: relationshipSuggestionsQueryKey,
    }),
    onSettled: async () => {
      await invalidateStreamingRelationshipMutationQueries(queryClient);
    },
  });
  const rejectMutation = useMutation({
    ...createOptimisticMutation<
      RejectStreamingRelationshipSuggestionResponse,
      Error,
      number | string,
      InfiniteData<StreamingRelationshipSuggestionsResponse>
    >({
      mutationFn: rejectStreamingRelationshipSuggestion,
      optimisticUpdate: removeRelationshipSuggestionFromCache,
      queryClient,
      queryKey: relationshipSuggestionsQueryKey,
    }),
    onSettled: async () => {
      await invalidateStreamingRelationshipMutationQueries(queryClient);
    },
  });
  const generateMutation = useMutation({
    mutationFn: generateStreamingRelationshipSuggestions,
    onSuccess: async () => {
      await invalidateStreamingRelationshipSuggestionQueries(queryClient);
    },
  });
  const suggestions = useMemo(
    () => suggestionsQuery.data?.pages.flatMap((page) => page.suggestions) ?? [],
    [suggestionsQuery.data],
  );
  const suggestionCount = suggestions.length;
  const totalSuggestionCount = suggestionsQuery.data?.pages[0]?.total_count ?? suggestionCount;
  const hasMoreSuggestions = suggestionsQuery.hasNextPage;
  const hasUnloadedSuggestions = totalSuggestionCount > suggestionCount;
  const sortedSuggestions = useMemo(() => sortRelationshipSuggestions(suggestions ?? []), [suggestions]);
  const activeAcceptSuggestionId = acceptMutation.isPending ? String(acceptMutation.variables.suggestionId) : null;
  const activeAcceptRelationshipType = acceptMutation.isPending ? acceptMutation.variables.relationship_type ?? null : null;
  const activeRejectSuggestionId = rejectMutation.isPending ? String(rejectMutation.variables) : null;
  const failedAcceptSuggestionId = acceptMutation.isError ? String(acceptMutation.variables.suggestionId) : null;
  const failedAcceptRelationshipType = acceptMutation.isError ? acceptMutation.variables.relationship_type ?? null : null;
  const failedRejectSuggestionId = rejectMutation.isError ? String(rejectMutation.variables) : null;
  const renderRelationshipFrame = (children: ReactNode) => (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Relationship queue</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            {suggestionsQuery.isSuccess
              ? hasUnloadedSuggestions
                ? `Showing ${suggestionCount} of ${totalSuggestionCount} pending streaming-to-streaming suggestions sorted by confidence.`
                : `${suggestionCount} pending streaming-to-streaming suggestions sorted by confidence.`
              : "Streaming-to-streaming suggestions sorted by confidence."}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {generateMutation.isError ? (
            <p className={`font-medium text-ctp-red ${textClasses.finePrint}`}>Generate failed.</p>
          ) : null}
          {generateMutation.isSuccess ? (
            <p className={`font-medium text-ctp-subtext0 ${textClasses.finePrint}`}>
              {generateMutation.data.created_count} created, {generateMutation.data.pruned_count} pruned.
            </p>
          ) : null}
          <ActionButton
            className={`${controlClasses.actionButtonCompact} inline-flex items-center justify-center gap-1.5`}
            disabled={generateMutation.isPending}
            onClick={() => generateMutation.mutate()}
          >
            <RefreshCw
              aria-hidden="true"
              className={`h-3.5 w-3.5 ${generateMutation.isPending ? "animate-spin" : ""}`}
              strokeWidth={1.9}
            />
            <span>{generateMutation.isPending ? "Generating..." : "Generate"}</span>
          </ActionButton>
        </div>
      </div>
      {children}
    </section>
  );

  if (suggestionsQuery.isPending) {
    return renderRelationshipFrame(
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <EmptyStateCard
          body="Checking for pending streaming-to-streaming relationship suggestions."
          role="status"
          title="Loading relationships"
        />
      </div>,
    );
  }

  if (suggestionsQuery.isError) {
    return renderRelationshipFrame(
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <EmptyStateCard
          body="Pending streaming-to-streaming relationship suggestions could not be loaded."
          role="alert"
          title="Relationships unavailable"
          tone="error"
        />
      </div>,
    );
  }

  if (suggestionCount === 0) {
    return renderRelationshipFrame(
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <EmptyStateCard
          body="Pending streaming-to-streaming relationship suggestions will appear here after generation."
          className={`${layoutClasses.emptyStateNarrow} text-left`}
          title="Streaming relationships"
        />
      </div>,
    );
  }

  return renderRelationshipFrame(
    <div className="min-h-0 flex-1 overflow-y-auto pr-1">
      <ul className="grid gap-3">
        {sortedSuggestions.map((suggestion) => {
          const defaultWinnerId = suggestion.conflict?.final_links[0]?.final_link_id ?? null;
          const selectedWinnerId = selectedWinnerIds[suggestion.id] ?? defaultWinnerId;

          return (
            <RelationshipSuggestionRow
              activeAcceptRelationshipType={activeAcceptRelationshipType}
              activeAcceptSuggestionId={activeAcceptSuggestionId}
              activeRejectSuggestionId={activeRejectSuggestionId}
              failedAcceptRelationshipType={failedAcceptRelationshipType}
              failedAcceptSuggestionId={failedAcceptSuggestionId}
              failedRejectSuggestionId={failedRejectSuggestionId}
              key={suggestion.id}
              onAccept={(acceptInput) => acceptMutation.mutate(acceptInput)}
              onReject={(suggestionId) => rejectMutation.mutate(suggestionId)}
              onSelectWinner={(finalLinkId) =>
                setSelectedWinnerIds((current) => ({ ...current, [suggestion.id]: finalLinkId }))
              }
              selectedWinnerId={selectedWinnerId}
              suggestion={suggestion}
            />
          );
        })}
      </ul>
      {hasMoreSuggestions ? (
        <div className="flex justify-center py-3">
          <ActionButton
            className={`${controlClasses.actionButtonCompact} inline-flex items-center justify-center gap-1.5`}
            disabled={suggestionsQuery.isFetchingNextPage}
            onClick={() => {
              void suggestionsQuery.fetchNextPage();
            }}
          >
            {suggestionsQuery.isFetchingNextPage ? "Loading..." : "Load more"}
          </ActionButton>
        </div>
      ) : null}
    </div>,
  );
}

function RelationshipSuggestionRow({
  activeAcceptRelationshipType,
  activeAcceptSuggestionId,
  activeRejectSuggestionId,
  failedAcceptRelationshipType,
  failedAcceptSuggestionId,
  failedRejectSuggestionId,
  onAccept,
  onReject,
  onSelectWinner,
  selectedWinnerId,
  suggestion,
}: {
  activeAcceptRelationshipType: RelationshipActionType | null;
  activeAcceptSuggestionId: string | null;
  activeRejectSuggestionId: string | null;
  failedAcceptRelationshipType: RelationshipActionType | null;
  failedAcceptSuggestionId: string | null;
  failedRejectSuggestionId: string | null;
  onAccept: (input: AcceptStreamingRelationshipSuggestionInput) => void;
  onReject: (suggestionId: number) => void;
  onSelectWinner: (finalLinkId: number) => void;
  selectedWinnerId: number | null;
  suggestion: StreamingRelationshipSuggestion;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const recommendationLabel = getRelationshipTypeLabel(suggestion.relationship_type);
  const hasEquivalentConflict = suggestion.conflict_state === "different_local_links";
  const canAcceptEquivalent = !hasEquivalentConflict || selectedWinnerId !== null;
  const isAccepting = activeAcceptSuggestionId === String(suggestion.id);
  const isEquivalentAccepting = isAccepting && activeAcceptRelationshipType === "equivalent";
  const isRelatedAccepting = isAccepting && activeAcceptRelationshipType === "related";
  const isRejecting = activeRejectSuggestionId === String(suggestion.id);
  const isActionPending = isAccepting || isRejecting;
  const actionError =
    failedAcceptSuggestionId === String(suggestion.id)
      ? `${getRelationshipTypeLabel(failedAcceptRelationshipType ?? suggestion.relationship_type)} failed.`
      : failedRejectSuggestionId === String(suggestion.id)
        ? "Reject failed."
        : null;

  function handleAccept(relationshipType: RelationshipActionType) {
    onAccept({
      relationship_type: relationshipType,
      suggestionId: suggestion.id,
      winning_final_link_id:
        relationshipType === "equivalent" && hasEquivalentConflict && selectedWinnerId !== null ? selectedWinnerId : undefined,
    });
  }

  return (
    <li
      aria-label={`Suggestion ${suggestion.id}: ${suggestion.first_track.title} to ${suggestion.second_track.title}`}
      className={surfaceClasses.rowCardCompact}
    >
      <article className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1fr)_150px] xl:items-start">
        <div className="grid min-w-0 gap-2.5">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Pill className="tabular-nums" tone={getRelationshipScoreTone(suggestion.score)}>
              {formatRelationshipScore(suggestion.score)}
            </Pill>
            <Pill tone={getRelationshipTypeTone(suggestion.relationship_type)}>Recommended {recommendationLabel}</Pill>
            <Pill tone={getMatchMethodTone(suggestion.match_method)}>{getMatchMethodLabel(suggestion.match_method)}</Pill>
            <span className={`inline-flex items-center gap-1 ${textClasses.finePrint} font-medium text-ctp-subtext0`}>
              <span
                aria-hidden="true"
                className={`h-1.5 w-1.5 rounded-full ${getConfidenceDotColorClass(suggestion.confidence)}`}
              />
              {getConfidenceLabel(suggestion.confidence)}
            </span>
            {hasEquivalentConflict ? <Pill tone="pending">Conflict</Pill> : null}
          </div>

          <div className="grid min-w-0 gap-2 lg:grid-cols-2">
            <RelationshipTrackPanel label="First streaming track" link={suggestion.first_link} track={suggestion.first_track} />
            <RelationshipTrackPanel
              label="Second streaming track"
              link={suggestion.second_link}
              track={suggestion.second_track}
            />
          </div>

          <WinnerSelection
            onSelect={onSelectWinner}
            selectedWinnerId={selectedWinnerId}
            suggestion={suggestion}
          />
          {isExpanded ? (
            <MatchInspectionPanel
              localAudios={localAudiosForSuggestion(suggestion)}
              streamingTracks={[
                {
                  artist: suggestion.first_track.artist,
                  providerTrackId: suggestion.first_track.provider_track_id,
                  title: suggestion.first_track.title,
                },
                {
                  artist: suggestion.second_track.artist,
                  providerTrackId: suggestion.second_track.provider_track_id,
                  title: suggestion.second_track.title,
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
            <span className="sr-only"> suggestion {suggestion.id}</span>
          </ActionButton>
          <ActionButton
            className={`${controlClasses.actionButtonCompact} inline-flex items-center justify-center gap-1.5`}
            disabled={isActionPending || !canAcceptEquivalent}
            onClick={() => handleAccept("equivalent")}
            tone="success"
          >
            <Link2 aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            <span>{isEquivalentAccepting ? "Accepting..." : "Equivalent"}</span>
            <span className="sr-only"> suggestion {suggestion.id}</span>
          </ActionButton>
          <ActionButton
            className={`${controlClasses.actionButtonCompact} inline-flex items-center justify-center gap-1.5`}
            disabled={isActionPending}
            onClick={() => handleAccept("related")}
            tone="neutral"
          >
            <GitBranch aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            <span>{isRelatedAccepting ? "Accepting..." : "Related"}</span>
            <span className="sr-only"> suggestion {suggestion.id}</span>
          </ActionButton>
          <ActionButton
            className={`${controlClasses.actionButtonCompact} inline-flex items-center justify-center gap-1.5`}
            disabled={isActionPending}
            onClick={() => onReject(suggestion.id)}
            tone="danger"
          >
            <XCircle aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            <span>{isRejecting ? "Rejecting..." : "Reject"}</span>
            <span className="sr-only"> suggestion {suggestion.id}</span>
          </ActionButton>
          {actionError ? (
            <p className={`font-medium text-ctp-red ${textClasses.finePrint} xl:text-right`}>{actionError}</p>
          ) : null}
        </div>
      </article>
    </li>
  );
}
