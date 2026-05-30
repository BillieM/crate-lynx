import { createColumnHelper, type RowSelectionState, type SortingState } from "@tanstack/react-table";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ListMusic, RadioTower, RefreshCw, Search, SearchX } from "lucide-react";
import { useMemo, useState } from "react";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { MetricCard } from "../../components/MetricCard";
import { Pill, type PillTone } from "../../components/Pill";
import { StatusMessage } from "../../components/StatusMessage";
import { formatDuration } from "../../lib/formatters";
import { settleInChunks } from "../../lib/settleInChunks";
import { useDelayedInvalidate } from "../../lib/useDelayedInvalidate";
import { controlClasses, textClasses } from "../../styles/componentClasses";
import {
  playlistSyncJobInvalidationKeys,
  syncStreamingPlaylist,
} from "../playlists/queries";
import {
  invalidateMissingLocallyQueries,
  type MissingLocallyResponse,
  type MissingLocallyTrack,
  refreshSoulseekAcquisition,
  searchMissingTrack,
  searchSelectedMissingTracks,
  useMissingLocallyTracksQuery,
} from "./queries";

type MaintenanceViewState = "ready" | "loading" | "error";

const emptyMissingLocallyTracks: MissingLocallyTrack[] = [];
const columnHelper = createColumnHelper<MissingLocallyTrack>();

type BulkMissingStatus = {
  body: string;
  status: "error" | "success";
  title: string;
};

function formatPlaylistUsage(track: MissingLocallyTrack) {
  const playlistNames = track.playlist_titles.join(", ");

  if (track.playlist_count <= 1) {
    return playlistNames || "Playlist unavailable";
  }

  return `${track.playlist_count} playlists: ${playlistNames || "titles unavailable"}`;
}

function getPlaylistCountLabel(track: MissingLocallyTrack) {
  return `${track.playlist_count} ${track.playlist_count === 1 ? "playlist" : "playlists"}`;
}

function getSoulseekStatusLabel(track: MissingLocallyTrack) {
  const status = track.soulseek_acquisition?.status;
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
      queued: "Queued",
      searching: "Searching",
    }[status] ?? status
  );
}

function getSoulseekStatusTone(track: MissingLocallyTrack): PillTone {
  const status = track.soulseek_acquisition?.status;
  if (status === "failed" || status === "link_failed" || status === "no_candidates") {
    return "danger";
  }
  if (status === "completed" || status === "ingested" || status === "proposal_available" || status === "linked") {
    return "success";
  }
  if (status === "queued" || status === "downloading" || status === "searching") {
    return "pending";
  }
  if (status === "candidates_found") {
    return "info";
  }
  return "neutral";
}

function MissingSoulseekRowActions({
  actionsDisabled,
  isRefreshing,
  isSearching,
  onRefresh,
  onSearch,
  track,
}: {
  actionsDisabled: boolean;
  isRefreshing: boolean;
  isSearching: boolean;
  onRefresh: (track: MissingLocallyTrack) => void;
  onSearch: (track: MissingLocallyTrack) => void;
  track: MissingLocallyTrack;
}) {
  const acquisition = track.soulseek_acquisition ?? null;

  return (
    <div className="flex items-center justify-end gap-1">
      <button
        aria-label={`Search Soulseek for ${track.title}`}
        className={controlClasses.iconButton}
        disabled={actionsDisabled}
        title="Search Soulseek"
        type="button"
        onClick={() => onSearch(track)}
      >
        <Search aria-hidden="true" className={isSearching ? "animate-spin" : ""} strokeWidth={1.9} />
      </button>
      {acquisition?.slskd_batch_id ? (
        <button
          aria-label={`Refresh Soulseek download for ${track.title}`}
          className={controlClasses.iconButton}
          disabled={actionsDisabled}
          title="Refresh Soulseek download"
          type="button"
          onClick={() => onRefresh(track)}
        >
          <RefreshCw aria-hidden="true" className={isRefreshing ? "animate-spin" : ""} strokeWidth={1.9} />
        </button>
      ) : null}
    </div>
  );
}

type MissingLocallyViewProps = {
  isPending?: boolean;
  state?: MaintenanceViewState;
  tracksResponse?: MissingLocallyResponse;
};

export function MissingLocallyView({ isPending = false, state, tracksResponse }: MissingLocallyViewProps = {}) {
  const queryClient = useQueryClient();
  const delayedInvalidate = useDelayedInvalidate();
  const missingLocallyQuery = useMissingLocallyTracksQuery();
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const [bulkSyncStatus, setBulkSyncStatus] = useState<BulkMissingStatus | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);
  const [bulkSearchStatus, setBulkSearchStatus] = useState<BulkMissingStatus | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [rowActionStatus, setRowActionStatus] = useState<BulkMissingStatus | null>(null);
  const [pendingSoulseekAction, setPendingSoulseekAction] = useState<{
    action: "refresh" | "search";
    trackId: number;
  } | null>(null);
  const resolvedState =
    state ?? (missingLocallyQuery.isPending ? "loading" : missingLocallyQuery.isError ? "error" : "ready");
  const tracks = tracksResponse?.tracks ?? missingLocallyQuery.data?.tracks ?? emptyMissingLocallyTracks;
  const playlistCount = new Set(tracks.flatMap((track) => track.playlist_titles)).size;
  const selectedTracks = useMemo(() => tracks.filter((track) => rowSelection[String(track.id)]), [rowSelection, tracks]);
  const selectedPlaylistIds = useMemo(
    () => Array.from(new Set(selectedTracks.flatMap((track) => track.playlist_ids))),
    [selectedTracks],
  );
  const selectedSearchTrackIds = useMemo(() => selectedTracks.map((track) => track.id), [selectedTracks]);
  const actionsDisabled = resolvedState !== "ready" || isPending;
  const rowActionMutationPending = pendingSoulseekAction !== null;
  const rowSearchMutation = useMutation({
    mutationFn: (track: MissingLocallyTrack) => searchMissingTrack(track.id),
    onError: (_error, track) => {
      setRowActionStatus({
        body: `Soulseek search could not be queued for ${track.title}.`,
        status: "error",
        title: "Soulseek search failed",
      });
    },
    onMutate: (track) => {
      setRowActionStatus(null);
      setPendingSoulseekAction({ action: "search", trackId: track.id });
    },
    onSettled: () => setPendingSoulseekAction(null),
    onSuccess: async (_response, track) => {
      await invalidateMissingLocallyQueries(queryClient);
      setRowActionStatus({
        body: `${track.title} was queued for Soulseek search.`,
        status: "success",
        title: "Soulseek search queued",
      });
    },
  });
  const rowRefreshMutation = useMutation({
    mutationFn: (track: MissingLocallyTrack) => {
      const acquisitionId = track.soulseek_acquisition?.id;
      if (!acquisitionId) {
        throw new Error("Soulseek acquisition is missing");
      }
      return refreshSoulseekAcquisition(acquisitionId);
    },
    onError: (_error, track) => {
      setRowActionStatus({
        body: `Soulseek status could not be refreshed for ${track.title}.`,
        status: "error",
        title: "Soulseek refresh failed",
      });
    },
    onMutate: (track) => {
      setRowActionStatus(null);
      setPendingSoulseekAction({ action: "refresh", trackId: track.id });
    },
    onSettled: () => setPendingSoulseekAction(null),
    onSuccess: async (_response, track) => {
      await invalidateMissingLocallyQueries(queryClient);
      setRowActionStatus({
        body: `${track.title} was queued for Soulseek status refresh.`,
        status: "success",
        title: "Soulseek refresh queued",
      });
    },
  });
  const columns = useMemo(
    () => [
      columnHelper.display({
        cell: () => (
          <span
            aria-label="Streaming track missing local match"
            className="inline-flex h-2.5 w-2.5 rounded-full bg-ctp-yellow shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-yellow)_16%,transparent)]"
            role="status"
          />
        ),
        enableSorting: false,
        header: "Status",
        meta: {
          widthClass: "w-8",
        },
      }),
      columnHelper.accessor("title", {
        cell: (info) => <span className="block max-w-[10rem] truncate font-semibold">{info.getValue()}</span>,
        header: "Title",
        meta: {
          widthClass: "min-w-[8rem]",
        },
      }),
      columnHelper.accessor("artist", {
        cell: (info) => <span className="block max-w-[9rem] truncate">{info.getValue()}</span>,
        header: "Artist",
        meta: {
          widthClass: "min-w-[7rem]",
        },
      }),
      columnHelper.accessor("album", {
        cell: (info) => <span className="block max-w-[9rem] truncate">{info.getValue() ?? "Album unavailable"}</span>,
        header: "Album",
        meta: {
          hideBelow: "md",
          widthClass: "min-w-[7rem]",
        },
      }),
      columnHelper.accessor("duration_ms", {
        cell: (info) => <span className="tabular-nums">{formatDuration(info.getValue())}</span>,
        header: "Duration",
        meta: {
          align: "end",
          widthClass: "w-16",
        },
      }),
      columnHelper.display({
        cell: (info) => (
          <span className="block max-w-[6rem] truncate" title={formatPlaylistUsage(info.row.original)}>
            {getPlaylistCountLabel(info.row.original)}
          </span>
        ),
        header: "Playlists",
        meta: {
          widthClass: "w-24",
        },
      }),
      columnHelper.display({
        cell: (info) => (
          <Pill className="whitespace-nowrap" tone={getSoulseekStatusTone(info.row.original)}>
            {getSoulseekStatusLabel(info.row.original)}
          </Pill>
        ),
        header: "Soulseek",
        meta: {
          widthClass: "w-28",
        },
      }),
      columnHelper.display({
        cell: (info) => (
          <MissingSoulseekRowActions
            actionsDisabled={actionsDisabled || rowActionMutationPending}
            isRefreshing={
              pendingSoulseekAction?.action === "refresh" &&
              pendingSoulseekAction.trackId === info.row.original.id
            }
            isSearching={
              pendingSoulseekAction?.action === "search" &&
              pendingSoulseekAction.trackId === info.row.original.id
            }
            onRefresh={(track) => rowRefreshMutation.mutate(track)}
            onSearch={(track) => rowSearchMutation.mutate(track)}
            track={info.row.original}
          />
        ),
        enableSorting: false,
        header: "Actions",
        meta: {
          align: "end",
          widthClass: "w-24",
        },
      }),
    ],
    [
      actionsDisabled,
      pendingSoulseekAction,
      rowActionMutationPending,
      rowRefreshMutation,
      rowSearchMutation,
    ],
  );

  async function handleBulkSync() {
    if (selectedPlaylistIds.length === 0 || isSyncing) {
      return;
    }

    setIsSyncing(true);
    setBulkSyncStatus(null);
    setRowActionStatus(null);

    const results = await settleInChunks(selectedPlaylistIds, 5, syncStreamingPlaylist);
    const successCount = results.filter((result) => result.status === "fulfilled").length;
    const failureCount = results.filter((result) => result.status === "rejected").length;

    await invalidateMissingLocallyQueries(queryClient);
    delayedInvalidate(playlistSyncJobInvalidationKeys(selectedPlaylistIds));

    setRowSelection({});
    setIsSyncing(false);
    setBulkSyncStatus({
      body:
        failureCount > 0
          ? `${successCount} ${successCount === 1 ? "playlist was" : "playlists were"} queued and ${failureCount} ${failureCount === 1 ? "playlist failed" : "playlists failed"}.`
          : `${successCount} ${successCount === 1 ? "playlist was" : "playlists were"} queued for sync.`,
      status: failureCount > 0 ? "error" : "success",
      title: failureCount > 0 ? "Playlist sync partially failed" : "Playlist sync queued",
    });
  }

  async function handleBulkSearch() {
    if (selectedSearchTrackIds.length === 0 || isSearching) {
      return;
    }
    if (selectedSearchTrackIds.length > 25) {
      setBulkSearchStatus({
        body: "Select 25 or fewer rows for Soulseek search.",
        status: "error",
        title: "Search selection too large",
      });
      return;
    }

    setIsSearching(true);
    setBulkSearchStatus(null);
    setRowActionStatus(null);
    try {
      const response = await searchSelectedMissingTracks(selectedSearchTrackIds);
      await invalidateMissingLocallyQueries(queryClient);
      setRowSelection({});
      setBulkSearchStatus({
        body: `${response.jobs.length} ${response.jobs.length === 1 ? "track was" : "tracks were"} queued for Soulseek search.`,
        status: "success",
        title: "Soulseek search queued",
      });
    } catch {
      setBulkSearchStatus({
        body: "Soulseek search jobs could not be queued.",
        status: "error",
        title: "Soulseek search failed",
      });
    } finally {
      setIsSearching(false);
    }
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      {isPending ? (
        <StatusMessage
          body="Missing-local-match results may update when playlist matching finishes."
          status="pending"
          title="Missing locally scan in progress"
        />
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2" aria-label="Missing locally summary">
        <MetricCard
          icon={SearchX}
          label="Missing tracks"
          toneClass="bg-ctp-yellow/18 text-ctp-yellow ring-ctp-yellow/30"
          value={tracks.length}
        />
        <MetricCard
          icon={ListMusic}
          label="Affected playlists"
          toneClass="bg-ctp-blue/18 text-ctp-blue ring-ctp-blue/30"
          value={playlistCount}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" aria-label="Missing local tracks" role="region">
        {bulkSyncStatus ? (
          <StatusMessage body={bulkSyncStatus.body} status={bulkSyncStatus.status} title={bulkSyncStatus.title} />
        ) : null}
        {bulkSearchStatus ? (
          <StatusMessage body={bulkSearchStatus.body} status={bulkSearchStatus.status} title={bulkSearchStatus.title} />
        ) : null}
        {resolvedState === "loading" ? (
          <EmptyStateCard
            body="Checking synced streaming tracks against the local library."
            className="text-left"
            role="status"
            title="Loading missing tracks"
          />
        ) : resolvedState === "error" ? (
          <EmptyStateCard
            body="The missing locally report could not be loaded."
            className="text-left"
            role="alert"
            title="Missing locally unavailable"
            tone="error"
          />
        ) : tracks.length > 0 ? (
          <div className="grid gap-2.5">
            <div className="flex items-center justify-between gap-3 px-1">
              <div className="flex items-center gap-2 text-ctp-subtext0">
                <RadioTower aria-hidden="true" className="h-4 w-4" strokeWidth={1.8} />
                <h2 className={textClasses.label}>Streaming tracks without local matches</h2>
              </div>
              <p className={`${textClasses.caption} tabular-nums`}>{tracks.length} rows</p>
            </div>
            <DataTable
              bulkActionSlot={
                <>
                  <ActionButton
                    className="inline-flex items-center gap-1.5"
                    disabled={
                      selectedSearchTrackIds.length === 0 ||
                      selectedSearchTrackIds.length > 25 ||
                      isSearching ||
                      actionsDisabled
                    }
                    onClick={handleBulkSearch}
                  >
                    <Search aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                    {isSearching ? "Searching..." : "Search selected"}
                  </ActionButton>
                  <ActionButton
                    className="inline-flex items-center gap-1.5"
                    disabled={selectedPlaylistIds.length === 0 || isSyncing}
                    onClick={handleBulkSync}
                  >
                    <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                    {isSyncing ? "Syncing..." : "Sync affected playlists"}
                  </ActionButton>
                </>
              }
              columns={columns}
              data={tracks}
              density="tight"
              rowId={(track) => String(track.id)}
              rowSelection={rowSelection}
              sorting={sorting}
              stickyHeader
              onRowSelectionChange={setRowSelection}
              onSortingChange={setSorting}
            />
          </div>
        ) : (
          <EmptyStateCard body="Every synced streaming track has a local match." className="text-left" title="No missing tracks" />
        )}
      </div>
      {rowActionStatus ? (
        <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-50 w-[min(22rem,calc(100vw-2rem))]">
          <StatusMessage
            body={rowActionStatus.body}
            className="pointer-events-auto shadow-lg shadow-ctp-crust/35"
            status={rowActionStatus.status}
            title={rowActionStatus.title}
          />
        </div>
      ) : null}
    </section>
  );
}
