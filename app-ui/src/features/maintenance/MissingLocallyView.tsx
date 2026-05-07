import { createColumnHelper, type RowSelectionState, type SortingState } from "@tanstack/react-table";
import { useQueryClient } from "@tanstack/react-query";
import { ListMusic, Music2, RadioTower, RefreshCw, SearchX } from "lucide-react";
import { useMemo, useState } from "react";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { StatusMessage } from "../../components/StatusMessage";
import { surfaceClasses, textClasses } from "../../styles/componentClasses";
import { syncStreamingPlaylist } from "../playlists/queries";
import {
  maintenanceQueryKeys,
  type MissingLocallyResponse,
  type MissingLocallyTrack,
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

function formatDuration(durationMs: number | null) {
  if (durationMs === null || durationMs < 0) {
    return "Unknown";
  }

  const totalSeconds = Math.floor(durationMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

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

async function settleInChunks<TItem, TResult>(
  items: TItem[],
  chunkSize: number,
  worker: (item: TItem) => Promise<TResult>,
): Promise<PromiseSettledResult<TResult>[]> {
  const settledResults: PromiseSettledResult<TResult>[] = [];

  for (let index = 0; index < items.length; index += chunkSize) {
    settledResults.push(...(await Promise.allSettled(items.slice(index, index + chunkSize).map(worker))));
  }

  return settledResults;
}

function MissingSummaryCard({
  icon: Icon,
  label,
  toneClass,
  value,
}: {
  icon: typeof Music2;
  label: string;
  toneClass: string;
  value: string;
}) {
  return (
    <section className={`${surfaceClasses.compactCard} min-h-24`} aria-label={label}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={`${textClasses.microEyebrow} text-ctp-subtext0`}>{label}</p>
          <p className="mt-2 text-[24px] font-semibold leading-none tabular-nums text-ctp-text">{value}</p>
        </div>
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] ring-1 ring-inset ${toneClass}`}>
          <Icon aria-hidden="true" className="h-[18px] w-[18px]" strokeWidth={1.8} />
        </div>
      </div>
    </section>
  );
}

type MissingLocallyViewProps = {
  isPending?: boolean;
  state?: MaintenanceViewState;
  tracksResponse?: MissingLocallyResponse;
};

export function MissingLocallyView({ isPending = false, state, tracksResponse }: MissingLocallyViewProps = {}) {
  const queryClient = useQueryClient();
  const missingLocallyQuery = useMissingLocallyTracksQuery();
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const [bulkSyncStatus, setBulkSyncStatus] = useState<BulkMissingStatus | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);
  const resolvedState =
    state ?? (missingLocallyQuery.isPending ? "loading" : missingLocallyQuery.isError ? "error" : "ready");
  const tracks = tracksResponse?.tracks ?? missingLocallyQuery.data?.tracks ?? emptyMissingLocallyTracks;
  const playlistCount = new Set(tracks.flatMap((track) => track.playlist_titles)).size;
  const selectedTracks = useMemo(() => tracks.filter((track) => rowSelection[String(track.id)]), [rowSelection, tracks]);
  const selectedPlaylistIds = useMemo(
    () => Array.from(new Set(selectedTracks.flatMap((track) => track.playlist_ids))),
    [selectedTracks],
  );
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
          widthClass: "w-20",
        },
      }),
      columnHelper.accessor("title", {
        cell: (info) => <span className="block max-w-[18rem] truncate font-semibold">{info.getValue()}</span>,
        header: "Title",
        meta: {
          widthClass: "min-w-[12rem]",
        },
      }),
      columnHelper.accessor("artist", {
        cell: (info) => <span className="block max-w-[14rem] truncate">{info.getValue()}</span>,
        header: "Artist",
        meta: {
          widthClass: "min-w-[10rem]",
        },
      }),
      columnHelper.accessor("album", {
        cell: (info) => <span className="block max-w-[14rem] truncate">{info.getValue() ?? "Album unavailable"}</span>,
        header: "Album",
        meta: {
          hideBelow: "md",
          widthClass: "min-w-[11rem]",
        },
      }),
      columnHelper.accessor("duration_ms", {
        cell: (info) => <span className="tabular-nums">{formatDuration(info.getValue())}</span>,
        header: "Duration",
        meta: {
          align: "end",
          widthClass: "w-24",
        },
      }),
      columnHelper.display({
        cell: (info) => (
          <span className="block max-w-[16rem] truncate" title={formatPlaylistUsage(info.row.original)}>
            {getPlaylistCountLabel(info.row.original)}
          </span>
        ),
        header: "Affected playlists",
        meta: {
          widthClass: "min-w-[10rem]",
        },
      }),
      columnHelper.accessor("provider_track_id", {
        cell: (info) => <span className="block max-w-[14rem] truncate font-mono text-[11px]">{info.getValue()}</span>,
        header: "Provider ID",
        meta: {
          hideBelow: "lg",
          widthClass: "min-w-[10rem]",
        },
      }),
    ],
    [],
  );

  async function handleBulkSync() {
    if (selectedPlaylistIds.length === 0 || isSyncing) {
      return;
    }

    setIsSyncing(true);
    setBulkSyncStatus(null);

    const results = await settleInChunks(selectedPlaylistIds, 5, syncStreamingPlaylist);
    const successCount = results.filter((result) => result.status === "fulfilled").length;
    const failureCount = results.filter((result) => result.status === "rejected").length;

    await queryClient.invalidateQueries({ queryKey: maintenanceQueryKeys.missingLocally() });

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
        <MissingSummaryCard
          icon={SearchX}
          label="Missing tracks"
          toneClass="bg-ctp-yellow/18 text-ctp-yellow ring-ctp-yellow/30"
          value={tracks.length.toString()}
        />
        <MissingSummaryCard
          icon={ListMusic}
          label="Affected playlists"
          toneClass="bg-ctp-blue/18 text-ctp-blue ring-ctp-blue/30"
          value={playlistCount.toString()}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" aria-label="Missing local tracks" role="region">
        {bulkSyncStatus ? (
          <StatusMessage body={bulkSyncStatus.body} status={bulkSyncStatus.status} title={bulkSyncStatus.title} />
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
                <ActionButton
                  className="inline-flex items-center gap-1.5"
                  disabled={selectedPlaylistIds.length === 0 || isSyncing}
                  onClick={handleBulkSync}
                >
                  <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                  {isSyncing ? "Syncing..." : "Sync affected playlists"}
                </ActionButton>
              }
              columns={columns}
              data={tracks}
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
    </section>
  );
}
