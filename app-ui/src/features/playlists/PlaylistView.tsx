import { createColumnHelper, type ColumnFiltersState, type RowSelectionState, type SortingState } from "@tanstack/react-table";
import { useQueryClient } from "@tanstack/react-query";
import { Unlink } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { StatusMessage } from "../../components/StatusMessage";
import { formatDuration, formatPlaylistTimestamp } from "../../lib/formatters";
import { settleInChunks } from "../../lib/settleInChunks";
import { textClasses } from "../../styles/componentClasses";
import { TrackDetailDrawer } from "../tracks/TrackDetailDrawer";
import { useStreamingAccountsQuery } from "../streamingAccounts/queries";
import { FilterChips } from "./FilterChips";
import { getPlaylistTrackFilterCounts, type PlaylistTrackFilter } from "./filterTracks";
import { PlaylistHeader } from "./PlaylistHeader";
import { PlaylistTrackActions } from "./PlaylistTrackActions";
import { TrackStatusDot } from "../../components/TrackStatusDot";
import {
  deleteFinalLink,
  invalidatePlaylistContentQueries,
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

function getAlbumLabel(album: string | null) {
  if (album === null || album.trim().length === 0) {
    return "Single / unknown release";
  }

  return album;
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
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const [bulkUnlinkStatus, setBulkUnlinkStatus] = useState<BulkUnlinkStatus | null>(null);
  const [isUnlinking, setIsUnlinking] = useState(false);
  const playlistDetailQuery = usePlaylistDetailQuery(isActive ? playlistResourceId : null);
  const playlistTracksQuery = usePlaylistTracksQuery(isActive ? playlistResourceId : null);
  const accountsQuery = useStreamingAccountsQuery();
  const tracks = useMemo(() => playlistTracksQuery.data?.tracks ?? [], [playlistTracksQuery.data?.tracks]);
  const filterCounts = useMemo(() => getPlaylistTrackFilterCounts(tracks), [tracks]);
  const activeFilter = (columnFilters[0]?.value as PlaylistTrackFilter | undefined) ?? "all";
  const selectedTracks = useMemo(() => tracks.filter((track) => rowSelection[String(track.id)]), [rowSelection, tracks]);
  const selectedLinkedTracks = useMemo(
    () => selectedTracks.filter((track) => track.status === "linked"),
    [selectedTracks],
  );
  const playlist = playlistDetailQuery.data?.playlist ?? null;
  const accounts = accountsQuery.data?.accounts ?? [];
  const activeAccount =
    playlist !== null
      ? (accounts.find((account) => account.id === playlist.account_id) ??
        accounts.find((account) => account.provider === "youtube_music") ??
        null)
      : null;
  const accountAuthError =
    activeAccount && (activeAccount.auth_state === "error" || activeAccount.auth_error !== null)
      ? {
          body: activeAccount.auth_error_at
            ? `${activeAccount.auth_error ?? "Authentication needs attention."} Reported ${formatPlaylistTimestamp(activeAccount.auth_error_at)}.`
            : (activeAccount.auth_error ?? "Authentication needs attention before sync can run."),
          title: "YouTube Music authentication needs attention",
        }
      : null;
  const openTrackDetail = useCallback(
    (track: PlaylistTrack) => {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set("detail", `streaming:${track.id}`);
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
          sticky: "right",
          widthClass: "w-28",
        },
      }),
    ],
    [openTrackDetail],
  );

  useEffect(() => {
    setColumnFilters([]);
    setRowSelection({});
    setBulkUnlinkStatus(null);
  }, [playlistResourceId]);

  function handleFilterChange(nextFilter: PlaylistTrackFilter) {
    setColumnFilters(nextFilter === "all" ? [] : [{ id: "status", value: nextFilter }]);
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

    await invalidatePlaylistContentQueries(queryClient, [playlistResourceId]);

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
        role="status"
        title="Loading playlist overview"
      />
    );
  }

  if (playlistDetailQuery.isError || playlistTracksQuery.isError) {
    return (
      <div className="grid justify-items-start gap-3">
        <EmptyStateCard
          body="Playlist overview is unavailable right now."
          className="text-left"
          role="alert"
          title="Playlist unavailable"
          tone="error"
        />
        <ActionButton
          onClick={() => {
            void playlistDetailQuery.refetch();
            void playlistTracksQuery.refetch();
          }}
        >
          Retry playlist
        </ActionButton>
      </div>
    );
  }

  if (!playlistDetailQuery.data) {
    return <EmptyStateCard body="No playlist detail was returned." className="text-left" title="Playlist missing" />;
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
      {accountAuthError ? (
        <StatusMessage body={accountAuthError.body} status="error" title={accountAuthError.title} />
      ) : null}
      {bulkUnlinkStatus ? (
        <StatusMessage body={bulkUnlinkStatus.body} status={bulkUnlinkStatus.status} title={bulkUnlinkStatus.title} />
      ) : null}
      <PlaylistHeader playlist={playlistDetailQuery.data.playlist} />
      <div className="flex flex-wrap items-center gap-3">
        <FilterChips activeFilter={activeFilter} counts={filterCounts} onFilterChange={handleFilterChange} />
      </div>
      <div aria-label="Playlist tracks" className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" role="region">
        {tracks.length === 0 ? (
          <EmptyStateCard
            body="This playlist has no imported tracks yet. Refresh metadata or run sync, then retry."
            className="text-left"
            title="No playlist tracks"
          />
        ) : filterCounts[activeFilter] === 0 ? (
          <div className="grid justify-items-start gap-3">
            <EmptyStateCard body="No tracks match the selected status." className="text-left" title="No matching tracks" />
            <ActionButton onClick={() => handleFilterChange("all")}>Show all tracks</ActionButton>
          </div>
        ) : (
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
            columnFilters={columnFilters}
            columns={columns}
            data={tracks}
            headerSlot={({ filteredRowCount, totalRowCount }) => (
              <p aria-live="polite" className={`${textClasses.status} text-ctp-subtext0`}>
                Showing {filteredRowCount} of {totalRowCount} tracks
              </p>
            )}
            rowId={(track) => String(track.id)}
            rowSelection={rowSelection}
            sorting={sorting}
            stickyHeader
            onActivate={openTrackDetail}
            onColumnFiltersChange={setColumnFilters}
            onRowSelectionChange={setRowSelection}
            onSortingChange={setSorting}
          />
        )}
      </div>
      <TrackDetailDrawer open={false} syncUrl onClose={() => undefined} />
    </section>
  );
}
