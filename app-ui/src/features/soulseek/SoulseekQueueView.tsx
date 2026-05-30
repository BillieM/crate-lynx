import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, RefreshCw, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { BulkActionBar } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { FilterChipGroup, type FilterChipOption } from "../../components/FilterChipGroup";
import { Pill, type PillTone } from "../../components/Pill";
import { StatusMessage } from "../../components/StatusMessage";
import { formatDuration } from "../../lib/formatters";
import { settleInChunks } from "../../lib/settleInChunks";
import { useDelayedInvalidate } from "../../lib/useDelayedInvalidate";
import { controlClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import { playlistSyncJobInvalidationKeys, syncStreamingPlaylist } from "../playlists/queries";
import {
  approveSoulseekCandidateDownload,
  invalidateSoulseekJourneyQueries,
  refreshSoulseekAcquisition,
  searchSelectedSoulseekTracks,
  searchSoulseekTrack,
  type SoulseekCandidate,
  type SoulseekQueueFilter,
  type SoulseekQueueItem,
  useSoulseekAcquisitionQuery,
  useSoulseekQueueQuery,
} from "./queries";

type QueueActionStatus = {
  body: string;
  status: "error" | "success";
  title: string;
};

const bulkSearchLimit = 25;
const defaultFilterPriority: SoulseekQueueFilter[] = ["review", "needs_search", "failed", "active", "all"];

const queueFilters: Array<Omit<FilterChipOption<SoulseekQueueFilter>, "count">> = [
  { label: "All", tone: "all", value: "all" },
  { label: "Needs search", tone: "unlinked", value: "needs_search" },
  { label: "Review", tone: "pending", value: "review" },
  { label: "Active", tone: "pending", value: "active" },
  { label: "Failed", tone: "unlinked", value: "failed" },
  { label: "Auto-linked", tone: "linked", value: "linked" },
];

function formatBytes(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }
  const units = ["KB", "MB", "GB", "TB"];
  let value = size / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[unitIndex]}`;
}

function formatSpeed(speed: number | null) {
  return speed === null ? "Unknown" : `${formatBytes(speed)}/s`;
}

function formatCandidateDuration(seconds: number | null) {
  return seconds === null ? "Unknown" : formatDuration(seconds * 1000);
}

function formatQuality(candidate: SoulseekCandidate) {
  const parts = [
    candidate.extension?.replace(".", "").toUpperCase(),
    candidate.bit_depth ? `${candidate.bit_depth}-bit` : null,
    candidate.bit_rate ? `${candidate.bit_rate} kbps` : null,
    candidate.sample_rate ? `${candidate.sample_rate} Hz` : null,
  ].filter(Boolean);
  return parts.join(" / ") || "Unknown";
}

function playlistUsage(item: SoulseekQueueItem) {
  if (item.playlist_count === 0) {
    return "No full-sync playlist usage";
  }
  return item.playlist_titles.join(", ") || `${item.playlist_count} playlists`;
}

function queueItemKey(item: SoulseekQueueItem) {
  return item.acquisition?.id ?? `track-${item.streaming_track.id}`;
}

function queueFilterForItem(item: SoulseekQueueItem): SoulseekQueueFilter {
  const status = item.acquisition?.status;
  if (!status || status === "no_candidates") {
    return "needs_search";
  }
  if (status === "candidates_found") {
    return "review";
  }
  if (status === "failed" || status === "link_failed") {
    return "failed";
  }
  if (status === "linked") {
    return "linked";
  }
  return "active";
}

function itemMatchesFilter(item: SoulseekQueueItem, filter: SoulseekQueueFilter) {
  return filter === "all" || queueFilterForItem(item) === filter;
}

function isSearchableQueueItem(item: SoulseekQueueItem) {
  return queueFilterForItem(item) === "needs_search";
}

function getStatusLabel(item: SoulseekQueueItem) {
  const status = item.acquisition?.status;
  if (!status) {
    return "Not searched";
  }
  return (
    {
      candidates_found: "Review",
      completed: "Downloaded",
      downloading: "Downloading",
      failed: "Failed",
      ingested: "Ingesting",
      link_failed: "Link failed",
      linked: "Auto-linked",
      no_candidates: "No candidates",
      proposal_available: "Link review",
      queued: item.acquisition?.slskd_transfer_id ? "Queued" : "Queueing",
      searching: "Searching",
    }[status] ?? status
  );
}

function getStatusTone(item: SoulseekQueueItem): PillTone {
  const filter = queueFilterForItem(item);
  if (filter === "failed") {
    return "danger";
  }
  if (filter === "linked") {
    return "success";
  }
  if (filter === "review") {
    return "info";
  }
  if (filter === "active") {
    return "pending";
  }
  return "neutral";
}

function sourceBasename(sourcePath: string | null) {
  if (!sourcePath) {
    return "Not reported";
  }
  return sourcePath.split(/[\\/]/).filter(Boolean).at(-1) ?? sourcePath;
}

function ingestStatus(acquisition: NonNullable<SoulseekQueueItem["acquisition"]>) {
  if (acquisition.local_track_id !== null) {
    return `Local track ${acquisition.local_track_id}`;
  }
  if (["completed", "ingested", "proposal_available", "linked", "link_failed"].includes(acquisition.status)) {
    return "Waiting for ingestion";
  }
  return "Not ready";
}

function linkStatus(acquisition: NonNullable<SoulseekQueueItem["acquisition"]>) {
  if (acquisition.status === "linked") {
    return `Final link ${acquisition.final_link_id ?? "created"}`;
  }
  if (acquisition.status === "link_failed") {
    return acquisition.link_error_detail ?? "Auto-link failed";
  }
  if (acquisition.status === "proposal_available") {
    return "Manual link review";
  }
  return "Pending";
}

function scoreTone(score: number): PillTone {
  if (score >= 0.78) {
    return "success";
  }
  if (score >= 0.62) {
    return "info";
  }
  return "pending";
}

function selectedItemIds(rowSelection: Record<string, boolean>) {
  return Object.entries(rowSelection)
    .filter(([, selected]) => selected)
    .map(([rowId]) => Number(rowId))
    .filter((rowId) => Number.isFinite(rowId));
}

export function SoulseekQueueView() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const delayedInvalidate = useDelayedInvalidate();
  const queueQuery = useSoulseekQueueQuery();
  const [activeFilter, setActiveFilter] = useState<SoulseekQueueFilter>("all");
  const [hasUserSelectedFilter, setHasUserSelectedFilter] = useState(false);
  const [activeItemKey, setActiveItemKey] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState<QueueActionStatus | null>(null);
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({});
  const [isSyncingPlaylists, setIsSyncingPlaylists] = useState(false);
  const allItems = useMemo(() => queueQuery.data?.items ?? [], [queueQuery.data?.items]);
  const selectedTrackIds = useMemo(() => selectedItemIds(rowSelection), [rowSelection]);
  const selectedItems = useMemo(
    () => allItems.filter((item) => selectedTrackIds.includes(item.streaming_track.id)),
    [allItems, selectedTrackIds],
  );
  const selectedPlaylistIds = useMemo(
    () => Array.from(new Set(selectedItems.flatMap((item) => item.playlist_ids))),
    [selectedItems],
  );
  const visibleItems = useMemo(
    () => allItems.filter((item) => itemMatchesFilter(item, activeFilter)),
    [activeFilter, allItems],
  );
  const selectedItem =
    visibleItems.find((item) => queueItemKey(item) === activeItemKey) ?? visibleItems[0] ?? null;
  const detailQuery = useSoulseekAcquisitionQuery(selectedItem?.acquisition?.id ?? null, {
    enabled: selectedItem?.acquisition !== null,
  });
  const detailItem = detailQuery.data ?? selectedItem;
  const candidates = detailItem?.candidates ?? [];
  const counts = useMemo(
    () =>
      queueFilters.reduce<Record<SoulseekQueueFilter, number>>(
        (accumulator, filter) => {
          accumulator[filter.value] =
            filter.value === "all" ? allItems.length : allItems.filter((item) => itemMatchesFilter(item, filter.value)).length;
          return accumulator;
        },
        {
          all: 0,
          active: 0,
          failed: 0,
          linked: 0,
          needs_search: 0,
          review: 0,
        },
      ),
    [allItems],
  );
  const filterOptions = queueFilters.map((filter) => ({ ...filter, count: counts[filter.value] }));
  const preferredFilter = useMemo(
    () => defaultFilterPriority.find((filter) => counts[filter] > 0) ?? "all",
    [counts],
  );

  useEffect(() => {
    if (hasUserSelectedFilter || activeFilter === preferredFilter) {
      return;
    }
    setActiveFilter(preferredFilter);
    setActiveItemKey(null);
  }, [activeFilter, hasUserSelectedFilter, preferredFilter]);

  useEffect(() => {
    setRowSelection((currentSelection) => {
      const searchableTrackIds = new Set(allItems.filter(isSearchableQueueItem).map((item) => item.streaming_track.id));
      const nextSelection: Record<string, boolean> = {};
      for (const [rowId, selected] of Object.entries(currentSelection)) {
        if (selected && searchableTrackIds.has(Number(rowId))) {
          nextSelection[rowId] = true;
        }
      }
      return Object.keys(nextSelection).length === Object.keys(currentSelection).length ? currentSelection : nextSelection;
    });
  }, [allItems]);
  const refreshMutation = useMutation({
    mutationFn: refreshSoulseekAcquisition,
    onError: () => {
      setActionStatus({
        body: "Soulseek status could not be refreshed.",
        status: "error",
        title: "Refresh failed",
      });
    },
    onSuccess: async () => {
      setActionStatus({
        body: "Soulseek status refresh was queued.",
        status: "success",
        title: "Refresh queued",
      });
      await invalidateSoulseekJourneyQueries(queryClient);
    },
  });
  const searchMutation = useMutation({
    mutationFn: searchSoulseekTrack,
    onError: () => {
      setActionStatus({
        body: "Soulseek search could not be queued.",
        status: "error",
        title: "Search failed",
      });
    },
    onSuccess: async () => {
      setActionStatus({
        body: "Soulseek search was queued.",
        status: "success",
        title: "Search queued",
      });
      await invalidateSoulseekJourneyQueries(queryClient);
    },
  });
  const bulkSearchMutation = useMutation({
    mutationFn: searchSelectedSoulseekTracks,
    onError: () => {
      setActionStatus({
        body: "Soulseek search jobs could not be queued.",
        status: "error",
        title: "Bulk search failed",
      });
    },
    onSuccess: async (response) => {
      setRowSelection({});
      setActionStatus({
        body: `${response.jobs.length} ${response.jobs.length === 1 ? "track was" : "tracks were"} queued for Soulseek search.`,
        status: "success",
        title: "Bulk search queued",
      });
      await invalidateSoulseekJourneyQueries(queryClient);
    },
  });
  const approveMutation = useMutation({
    mutationFn: approveSoulseekCandidateDownload,
    onError: () => {
      setActionStatus({
        body: "Soulseek download approval failed.",
        status: "error",
        title: "Download approval failed",
      });
    },
    onSuccess: async () => {
      setActionStatus({
        body: "Soulseek accepted the download. The imported file will auto-link after ingestion.",
        status: "success",
        title: "Download approved",
      });
      await invalidateSoulseekJourneyQueries(queryClient);
    },
  });
  const activeAcquisition = detailItem?.acquisition ?? null;
  const selectedCandidate = detailItem?.selected_candidate ?? null;

  function handleFilterChange(value: SoulseekQueueFilter) {
    setHasUserSelectedFilter(true);
    setActiveFilter(value);
    setActiveItemKey(null);
  }

  function toggleItemSelection(item: SoulseekQueueItem, checked: boolean) {
    if (!isSearchableQueueItem(item)) {
      return;
    }
    setRowSelection((currentSelection) => ({
      ...currentSelection,
      [String(item.streaming_track.id)]: checked,
    }));
  }

  function handleBulkSearch() {
    if (selectedTrackIds.length === 0 || bulkSearchMutation.isPending) {
      return;
    }
    if (selectedTrackIds.length > bulkSearchLimit) {
      setActionStatus({
        body: `Select ${bulkSearchLimit} or fewer rows for Soulseek search.`,
        status: "error",
        title: "Selection too large",
      });
      return;
    }
    bulkSearchMutation.mutate(selectedTrackIds);
  }

  async function handleSyncAffectedPlaylists() {
    if (selectedPlaylistIds.length === 0 || isSyncingPlaylists) {
      return;
    }

    setIsSyncingPlaylists(true);
    setActionStatus(null);
    const results = await settleInChunks(selectedPlaylistIds, 5, syncStreamingPlaylist);
    const successCount = results.filter((result) => result.status === "fulfilled").length;
    const failureCount = results.filter((result) => result.status === "rejected").length;

    await invalidateSoulseekJourneyQueries(queryClient);
    delayedInvalidate(playlistSyncJobInvalidationKeys(selectedPlaylistIds));
    setRowSelection({});
    setIsSyncingPlaylists(false);
    setActionStatus({
      body:
        failureCount > 0
          ? `${successCount} ${successCount === 1 ? "playlist was" : "playlists were"} queued and ${failureCount} ${failureCount === 1 ? "playlist failed" : "playlists failed"}.`
          : `${successCount} ${successCount === 1 ? "playlist was" : "playlists were"} queued for sync.`,
      status: failureCount > 0 ? "error" : "success",
      title: failureCount > 0 ? "Playlist sync partially failed" : "Playlist sync queued",
    });
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className={textClasses.sectionTitle}>Soulseek acquisition queue</h2>
          <p className={`mt-1 ${textClasses.bodyMuted}`}>
            Review approved searches, downloads, failures, and auto-linked imports.
          </p>
        </div>
        <FilterChipGroup
          activeValue={activeFilter}
          ariaLabel="Soulseek queue filters"
          density="compact"
          onValueChange={handleFilterChange}
          options={filterOptions}
        />
      </div>

      {actionStatus ? (
        <StatusMessage body={actionStatus.body} status={actionStatus.status} title={actionStatus.title} />
      ) : null}

      <BulkActionBar selectedCount={selectedTrackIds.length} onClearSelection={() => setRowSelection({})}>
        <ActionButton
          className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
          disabled={selectedTrackIds.length === 0 || selectedTrackIds.length > bulkSearchLimit || bulkSearchMutation.isPending}
          onClick={handleBulkSearch}
          type="button"
        >
          <Search aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
          {bulkSearchMutation.isPending ? "Searching..." : "Search selected"}
        </ActionButton>
        <ActionButton
          className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
          disabled={selectedPlaylistIds.length === 0 || isSyncingPlaylists}
          onClick={handleSyncAffectedPlaylists}
          type="button"
        >
          <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
          {isSyncingPlaylists ? "Syncing..." : "Sync affected playlists"}
        </ActionButton>
      </BulkActionBar>

      {queueQuery.isPending ? (
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <EmptyStateCard body="Loading Soulseek acquisition state." role="status" title="Loading Soulseek queue" />
        </div>
      ) : queueQuery.isError ? (
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <EmptyStateCard body="Soulseek queue could not be loaded." role="alert" title="Soulseek unavailable" tone="error" />
        </div>
      ) : visibleItems.length === 0 ? (
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <EmptyStateCard body="No Soulseek items match the active filter." title="Queue empty" />
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(16rem,0.8fr)_minmax(0,1.4fr)]">
          <div className="min-h-0 overflow-y-auto pr-1" aria-label="Soulseek queue items" role="region">
            <ul className="grid gap-2">
              {visibleItems.map((item) => {
                const isSelected = selectedItem !== null && queueItemKey(selectedItem) === queueItemKey(item);
                const canSearch = isSearchableQueueItem(item);
                const rowId = String(item.streaming_track.id);
                const isRowSelected = rowSelection[rowId] === true;
                const rowSearchPending =
                  searchMutation.isPending && String(searchMutation.variables) === String(item.streaming_track.id);
                return (
                  <li key={queueItemKey(item)}>
                    <div
                      className={`w-full text-left ${surfaceClasses.rowCardCompact} ${
                        isSelected ? "border-ctp-mauve/70 bg-ctp-surface0" : ""
                      }`}
                    >
                      <span className="flex min-w-0 items-start gap-2">
                        {canSearch ? (
                          <input
                            aria-label={`Select ${item.streaming_track.title}`}
                            checked={isRowSelected}
                            className="mt-1 h-4 w-4 shrink-0 accent-ctp-mauve"
                            onChange={(event) => toggleItemSelection(item, event.currentTarget.checked)}
                            type="checkbox"
                          />
                        ) : null}
                        <button
                          aria-pressed={isSelected}
                          className="grid min-w-0 flex-1 gap-2 text-left"
                          onClick={() => setActiveItemKey(queueItemKey(item))}
                          type="button"
                        >
                          <span className="flex min-w-0 items-start justify-between gap-2">
                            <span className="min-w-0">
                              <span className={`block truncate ${textClasses.label}`}>{item.streaming_track.title}</span>
                              <span className={`block truncate ${textClasses.caption}`}>{item.streaming_track.artist}</span>
                            </span>
                            <Pill className="shrink-0" tone={getStatusTone(item)}>
                              {getStatusLabel(item)}
                            </Pill>
                          </span>
                          <span className={`block min-w-0 truncate ${textClasses.finePrint} text-ctp-overlay1`} title={playlistUsage(item)}>
                            {playlistUsage(item)}
                          </span>
                        </button>
                        {canSearch ? (
                          <button
                            aria-label={`Search Soulseek for ${item.streaming_track.title}`}
                            className={`${controlClasses.iconButton} mt-5`}
                            disabled={searchMutation.isPending || bulkSearchMutation.isPending}
                            onClick={() => searchMutation.mutate(item.streaming_track.id)}
                            title="Search Soulseek"
                            type="button"
                          >
                            <Search aria-hidden="true" className={rowSearchPending ? "animate-spin" : ""} strokeWidth={1.9} />
                          </button>
                        ) : null}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="min-h-0 overflow-y-auto pr-1" aria-label="Soulseek queue detail" role="region">
            {detailItem ? (
              <article className={`${surfaceClasses.rowCard} gap-4`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className={textClasses.eyebrow}>Streaming track</p>
                    <h3 className={`mt-1 truncate ${textClasses.sectionTitle}`}>{detailItem.streaming_track.title}</h3>
                    <p className={`mt-1 ${textClasses.bodyMuted}`}>
                      {detailItem.streaming_track.artist}
                      {detailItem.streaming_track.album ? ` · ${detailItem.streaming_track.album}` : ""}
                      {detailItem.streaming_track.duration_ms ? ` · ${formatDuration(detailItem.streaming_track.duration_ms)}` : ""}
                    </p>
                  </div>
                  <Pill tone={getStatusTone(detailItem)}>{getStatusLabel(detailItem)}</Pill>
                </div>

                {activeAcquisition?.error_detail || activeAcquisition?.link_error_detail ? (
                  <StatusMessage
                    body={activeAcquisition.link_error_detail ?? activeAcquisition.error_detail ?? "Soulseek action failed."}
                    status="error"
                    title={activeAcquisition.status === "link_failed" ? "Auto-link failed" : "Soulseek failed"}
                  />
                ) : null}

                {activeAcquisition?.final_link_id ? (
                  <StatusMessage
                    body={`Linked to local track ${activeAcquisition.local_track_id ?? "unknown"} as final link ${activeAcquisition.final_link_id}.`}
                    status="success"
                    title="Auto-linked"
                  />
                ) : null}

                <PlaylistUsageChips
                  item={detailItem}
                  onOpenPlaylist={(playlistId) => navigate(`/playlists/${playlistId}`)}
                />

                <div className="flex flex-wrap gap-2">
                  <ActionButton
                    className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
                    disabled={searchMutation.isPending}
                    onClick={() => searchMutation.mutate(detailItem.streaming_track.id)}
                  >
                    <Search aria-hidden="true" className={searchMutation.isPending ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} strokeWidth={1.9} />
                    {activeAcquisition ? "Re-search" : "Search"}
                  </ActionButton>
                  {activeAcquisition ? (
                    <ActionButton
                      className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
                      disabled={refreshMutation.isPending}
                      onClick={() => refreshMutation.mutate(activeAcquisition.id)}
                    >
                      <RefreshCw aria-hidden="true" className={refreshMutation.isPending ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} strokeWidth={1.9} />
                      Refresh
                    </ActionButton>
                  ) : null}
                  {selectedCandidate && activeAcquisition?.status === "failed" ? (
                    <ActionButton
                      className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
                      disabled={approveMutation.isPending}
                      onClick={() => approveMutation.mutate(selectedCandidate.id)}
                      tone="success"
                    >
                      <Download aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                      Retry selected
                    </ActionButton>
                  ) : null}
                </div>

                {activeAcquisition ? (
                  <section className={`${surfaceClasses.insetPanel} px-3 py-2`}>
                    <dl className="grid gap-2 text-[11px] text-ctp-subtext0 sm:grid-cols-2">
                      <div>
                        <dt className="font-semibold uppercase text-ctp-overlay1">Transfer id</dt>
                        <dd className="mt-0.5 break-all text-ctp-text">
                          {activeAcquisition.slskd_transfer_id ?? activeAcquisition.slskd_batch_id ?? "Waiting for slskd"}
                        </dd>
                      </div>
                      <div>
                        <dt className="font-semibold uppercase text-ctp-overlay1">Source file</dt>
                        <dd className="mt-0.5 break-words text-ctp-text">
                          {sourceBasename(activeAcquisition.completed_source_path)}
                        </dd>
                      </div>
                      <div>
                        <dt className="font-semibold uppercase text-ctp-overlay1">Ingest status</dt>
                        <dd className="mt-0.5 text-ctp-text">{ingestStatus(activeAcquisition)}</dd>
                      </div>
                      <div>
                        <dt className="font-semibold uppercase text-ctp-overlay1">Link status</dt>
                        <dd className="mt-0.5 break-words text-ctp-text">{linkStatus(activeAcquisition)}</dd>
                      </div>
                    </dl>
                  </section>
                ) : null}

                <section className="grid gap-2">
                  <div className="flex items-center justify-between gap-2">
                    <h4 className={textClasses.label}>Candidates</h4>
                    {activeAcquisition ? (
                      <span className={`${textClasses.finePrint} text-ctp-subtext0 tabular-nums`}>
                        {activeAcquisition.candidate_count} stored
                      </span>
                    ) : null}
                  </div>
                  {detailQuery.isFetching ? <p className={textClasses.caption}>Refreshing candidates...</p> : null}
                  {candidates.length > 0 ? (
                    <ul className="grid gap-2">
                      {candidates.map((candidate) => (
                        <CandidateRow
                          candidate={candidate}
                          approvalLocked={activeAcquisition?.selected_candidate_id !== null && activeAcquisition?.selected_candidate_id !== undefined}
                          isApproving={approveMutation.isPending && String(approveMutation.variables) === String(candidate.id)}
                          isSelected={activeAcquisition?.selected_candidate_id === candidate.id}
                          key={candidate.id}
                          onApprove={(candidateId) => approveMutation.mutate(candidateId)}
                        />
                      ))}
                    </ul>
                  ) : activeAcquisition ? (
                    <EmptyStateCard body="No ranked candidates are stored for this search." className="text-left" title="No candidates" />
                  ) : (
                    <EmptyStateCard body="Queue a Soulseek search to collect ranked candidates." className="text-left" title="Not searched" />
                  )}
                </section>
              </article>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}

function PlaylistUsageChips({
  item,
  onOpenPlaylist,
}: {
  item: SoulseekQueueItem;
  onOpenPlaylist: (playlistId: number) => void;
}) {
  if (item.playlist_ids.length === 0) {
    return (
      <section className={`${surfaceClasses.insetPanel} px-3 py-2`}>
        <p className={textClasses.label}>Affected playlists</p>
        <p className={`mt-1 ${textClasses.caption}`}>No full-sync playlist usage.</p>
      </section>
    );
  }

  return (
    <section className={`${surfaceClasses.insetPanel} px-3 py-2`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={textClasses.label}>Affected playlists</p>
        <span className={`${textClasses.finePrint} text-ctp-subtext0 tabular-nums`}>
          {item.playlist_count.toLocaleString()}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {item.playlist_ids.map((playlistId, index) => (
          <button
            className={`${controlClasses.pill} border border-ctp-surface1 bg-ctp-surface0 text-ctp-subtext0 transition-colors hover:border-ctp-overlay0 hover:text-ctp-text`}
            key={playlistId}
            onClick={() => onOpenPlaylist(playlistId)}
            type="button"
          >
            {item.playlist_titles[index] ?? `Playlist ${playlistId}`}
          </button>
        ))}
      </div>
    </section>
  );
}

function CandidateRow({
  approvalLocked,
  candidate,
  isApproving,
  isSelected,
  onApprove,
}: {
  approvalLocked: boolean;
  candidate: SoulseekCandidate;
  isApproving: boolean;
  isSelected: boolean;
  onApprove: (candidateId: string) => void;
}) {
  return (
    <li className={surfaceClasses.insetPanel}>
      <div className="grid gap-2 px-3 py-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="break-words text-[12px] font-semibold text-ctp-text">{candidate.filename}</p>
            <p className={`${textClasses.caption} truncate`}>{candidate.username}</p>
          </div>
          <div className="flex items-center gap-1.5">
            {isSelected ? <Pill tone="success">Approved</Pill> : null}
            <Pill tone={scoreTone(candidate.score)}>{Math.round(candidate.score * 100)}%</Pill>
          </div>
        </div>
        <div className="grid gap-1 text-[11px] text-ctp-subtext0 sm:grid-cols-2">
          <span>Duration {formatCandidateDuration(candidate.duration_seconds)}</span>
          <span>Quality {formatQuality(candidate)}</span>
          <span>Size {formatBytes(candidate.size)}</span>
          <span>Queue {candidate.has_free_upload_slot ? "Free slot" : (candidate.queue_length ?? "Unknown")}</span>
          <span>Speed {formatSpeed(candidate.upload_speed)}</span>
        </div>
        <div className="flex justify-end">
          <ActionButton
            aria-label={`Approve Soulseek download ${candidate.filename}`}
            className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
            disabled={isApproving || approvalLocked}
            onClick={() => onApprove(candidate.id)}
            tone="success"
          >
            {isSelected ? (
              <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            ) : (
              <Download aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            )}
            {isApproving ? "Approving..." : isSelected ? "Approved candidate" : approvalLocked ? "Approval locked" : "Approve download"}
          </ActionButton>
        </div>
      </div>
    </li>
  );
}
