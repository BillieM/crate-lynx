import { createColumnHelper, type RowSelectionState, type SortingState } from "@tanstack/react-table";
import { useQueryClient } from "@tanstack/react-query";
import { Unlink } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { StatusMessage } from "../../components/StatusMessage";
import { textClasses } from "../../styles/componentClasses";
import { LocalTrackDetailDrawer } from "../localTracks/LocalTrackDetailDrawer";
import { FilterChips } from "./FilterChips";
import { filterPlaylistTracks, getPlaylistTrackFilterCounts, type PlaylistTrackFilter } from "./filterTracks";
import { PlaylistHeader } from "./PlaylistHeader";
import { PlaylistTrackActions } from "./PlaylistTrackActions";
import { TrackStatusDot } from "./TrackStatusDot";
import {
  deleteFinalLink,
  playlistQueryKeys,
  type PlaylistTrack,
  usePlaylistDetailQuery,
  usePlaylistTracksQuery,
} from "./queries";
import type { PlaylistSyncViewState } from "../shell/types";

type BulkUnlinkStatus = {
  body: string;
  status: "error" | "success";
  title: string;
};

const columnHelper = createColumnHelper<PlaylistTrack>();

function formatDuration(durationMs: number | null) {
  if (durationMs === null || durationMs < 0) {
    return "Unknown";
  }

  const totalSeconds = Math.floor(durationMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function getAlbumLabel(album: string | null) {
  if (album === null || album.trim().length === 0) {
    return "Single / unknown release";
  }

  return album;
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

export function PlaylistView({
  isActive,
  playlistResourceId,
  syncState,
}: {
  isActive: boolean;
  playlistResourceId: number;
  syncState?: PlaylistSyncViewState;
}) {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeFilter, setActiveFilter] = useState<PlaylistTrackFilter>("all");
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const [bulkUnlinkStatus, setBulkUnlinkStatus] = useState<BulkUnlinkStatus | null>(null);
  const [isUnlinking, setIsUnlinking] = useState(false);
  const playlistDetailQuery = usePlaylistDetailQuery(isActive ? playlistResourceId : null);
  const playlistTracksQuery = usePlaylistTracksQuery(isActive ? playlistResourceId : null);
  const tracks = useMemo(() => playlistTracksQuery.data?.tracks ?? [], [playlistTracksQuery.data?.tracks]);
  const filterCounts = useMemo(() => getPlaylistTrackFilterCounts(tracks), [tracks]);
  const filteredTracks = useMemo(() => filterPlaylistTracks(tracks, activeFilter), [activeFilter, tracks]);
  const selectedTracks = useMemo(() => tracks.filter((track) => rowSelection[String(track.id)]), [rowSelection, tracks]);
  const selectedLinkedTracks = useMemo(
    () => selectedTracks.filter((track) => track.status === "linked"),
    [selectedTracks],
  );
  const openTrackDetail = useCallback(
    (track: PlaylistTrack) => {
      if (track.status !== "linked" || track.local_track_id === null) {
        return;
      }

      const nextParams = new URLSearchParams(searchParams);
      nextParams.set("detail", String(track.local_track_id));
      setSearchParams(nextParams, { replace: false });
    },
    [searchParams, setSearchParams],
  );
  const columns = useMemo(
    () => [
      columnHelper.accessor("position", {
        cell: (info) => (
          <span className={`${textClasses.eyebrow} tabular-nums text-ctp-subtext0`}>{info.getValue()}</span>
        ),
        header: "#",
        meta: {
          align: "end",
          widthClass: "w-12",
        },
      }),
      columnHelper.accessor("status", {
        cell: (info) => <TrackStatusDot status={info.getValue()} />,
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
        cell: (info) => <span className="block max-w-[14rem] truncate">{getAlbumLabel(info.getValue())}</span>,
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
      columnHelper.accessor("provider_track_id", {
        cell: (info) => <span className="block max-w-[14rem] truncate font-mono text-[11px]">{info.getValue()}</span>,
        header: "Provider ID",
        meta: {
          hideBelow: "lg",
          widthClass: "min-w-[10rem]",
        },
      }),
      columnHelper.display({
        cell: (info) => (
          <div className="flex justify-end">
            <PlaylistTrackActions
              track={info.row.original}
              onOpenTrackDetail={openTrackDetail}
            />
          </div>
        ),
        enableSorting: false,
        header: "Actions",
        meta: {
          align: "end",
          widthClass: "w-28",
        },
      }),
    ],
    [openTrackDetail],
  );

  useEffect(() => {
    setActiveFilter("all");
    setRowSelection({});
    setBulkUnlinkStatus(null);
  }, [playlistResourceId]);

  function handleFilterChange(nextFilter: PlaylistTrackFilter) {
    setActiveFilter(nextFilter);
    setRowSelection({});
  }

  async function handleBulkUnlink() {
    const unlinkableTracks = selectedLinkedTracks.filter((track) => track.final_link_id !== null);
    const missingFinalLinkCount = selectedLinkedTracks.length - unlinkableTracks.length;

    if (selectedLinkedTracks.length === 0 || isUnlinking) {
      return;
    }

    setIsUnlinking(true);
    setBulkUnlinkStatus(null);

    const results = await settleInChunks(unlinkableTracks, 5, (track) => deleteFinalLink(track.final_link_id as number));
    const successCount = results.filter((result) => result.status === "fulfilled").length;
    const failureCount = results.filter((result) => result.status === "rejected").length + missingFinalLinkCount;

    await Promise.all([
      queryClient.invalidateQueries({ queryKey: playlistQueryKeys.detail(playlistResourceId) }),
      queryClient.invalidateQueries({ queryKey: playlistQueryKeys.tracks(playlistResourceId) }),
      queryClient.invalidateQueries({ queryKey: playlistQueryKeys.list() }),
    ]);

    setRowSelection({});
    setIsUnlinking(false);
    setBulkUnlinkStatus({
      body:
        failureCount > 0
          ? `${successCount} ${successCount === 1 ? "link was" : "links were"} removed and ${failureCount} ${failureCount === 1 ? "row failed" : "rows failed"}.`
          : `${successCount} ${successCount === 1 ? "link was" : "links were"} removed.`,
      status: failureCount > 0 ? "error" : "success",
      title: failureCount > 0 ? "Bulk unlink partially failed" : "Bulk unlink complete",
    });
  }

  if (playlistDetailQuery.isPending || playlistTracksQuery.isPending) {
    return (
      <EmptyStateCard
        body="Loading playlist overview..."
        className="text-left"
        title="Loading playlist overview"
      />
    );
  }

  if (playlistDetailQuery.isError || playlistTracksQuery.isError) {
    return (
      <EmptyStateCard
        body="Playlist overview is unavailable right now."
        className="text-left"
        title="Playlist unavailable"
        tone="error"
      />
    );
  }

  if (!playlistDetailQuery.data) {
    return null;
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-5">
      {syncState?.status === "pending" ? (
        <StatusMessage
          body="This playlist is being synced. Track counts and link status may update when the job finishes."
          status="pending"
          title="Playlist sync in progress"
        />
      ) : null}
      {syncState?.status === "error" ? (
        <StatusMessage
          body={playlistDetailQuery.data.playlist.last_sync_error ?? "The playlist sync request failed before the job could be queued."}
          status="error"
          title="Playlist sync failed"
        />
      ) : null}
      {bulkUnlinkStatus ? (
        <StatusMessage body={bulkUnlinkStatus.body} status={bulkUnlinkStatus.status} title={bulkUnlinkStatus.title} />
      ) : null}
      <PlaylistHeader playlist={playlistDetailQuery.data.playlist} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <FilterChips activeFilter={activeFilter} counts={filterCounts} onFilterChange={handleFilterChange} />
        <p className={`${textClasses.status} text-ctp-subtext0`}>
          Showing {filteredTracks.length} of {tracks.length} tracks
        </p>
      </div>
      <div aria-label="Playlist tracks" className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" role="region">
        {filteredTracks.length > 0 ? (
          <DataTable
            bulkActionSlot={
              <ActionButton
                className="inline-flex items-center gap-1.5"
                disabled={selectedLinkedTracks.length === 0 || isUnlinking}
                tone="danger"
                onClick={handleBulkUnlink}
              >
                <Unlink aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                {isUnlinking ? "Unlinking..." : "Unlink"}
              </ActionButton>
            }
            columns={columns}
            data={filteredTracks}
            rowId={(track) => String(track.id)}
            rowSelection={rowSelection}
            sorting={sorting}
            stickyHeader
            onActivate={openTrackDetail}
            onRowSelectionChange={setRowSelection}
            onSortingChange={setSorting}
          />
        ) : (
          <EmptyStateCard body="No tracks match this filter." title="No matching tracks" />
        )}
      </div>
      <LocalTrackDetailDrawer localTrackId={null} open={false} syncUrl onClose={() => undefined} />
    </section>
  );
}
