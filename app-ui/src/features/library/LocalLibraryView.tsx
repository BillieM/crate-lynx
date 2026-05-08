import { createColumnHelper, type ColumnFiltersState, type RowSelectionState, type SortingState } from "@tanstack/react-table";
import { FileAudio, RotateCcw, SlidersHorizontal, Unlink } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { FilterChipGroup, type FilterChipOption } from "../../components/FilterChipGroup";
import { StatusMessage } from "../../components/StatusMessage";
import { formatDuration } from "../../lib/formatters";
import { settleInChunks } from "../../lib/settleInChunks";
import { controlClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import { trackStatusDotClasses } from "../../styles/toneClasses";
import { LocalTrackDetailDrawer } from "../localTracks/LocalTrackDetailDrawer";
import { deleteFinalLink, playlistQueryKeys } from "../playlists/queries";
import {
  type LibraryLinkStatus,
  type LibraryStats,
  type LibraryTrack,
  type LibraryTracksResponse,
  libraryQueryKeys,
  useLibraryTracksQuery,
} from "./queries";

type LibraryViewState = "ready" | "loading" | "error";
type LibraryLinkStatusFilter = "all" | "linked" | "pending" | "unlinked";

const defaultLibraryStats = {
  linked: 0,
  pending: 0,
  total: 0,
  unlinked: 0,
} satisfies LibraryStats;
const emptyLibraryTracks: LibraryTrack[] = [];

type RematchResponse = {
  job_id: string;
  local_track_id: number;
};

type BulkLibraryStatus = {
  body: string;
  status: "error" | "success";
  title: string;
};

async function rematchLocalTrack(localTrackId: number): Promise<RematchResponse> {
  const response = await fetch(`/api/local-tracks/${encodeURIComponent(String(localTrackId))}/rematch`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Re-match request failed with status ${response.status}`);
  }

  return (await response.json()) as RematchResponse;
}

const linkStatusLabels = {
  linked: "Linked",
  pending: "Pending",
  unlinked: "Unlinked",
} satisfies Record<LibraryLinkStatus, string>;

const columnHelper = createColumnHelper<LibraryTrack>();

function buildLinkStatusFilters(stats: LibraryStats) {
  return [
    {
      count: stats.total,
      label: "All",
      tone: "all",
      value: "all",
    },
    {
      count: stats.linked,
      label: "Linked",
      tone: "linked",
      value: "linked",
    },
    {
      count: stats.pending,
      label: "Pending",
      tone: "pending",
      value: "pending",
    },
    {
      count: stats.unlinked,
      label: "Unlinked",
      tone: "unlinked",
      value: "unlinked",
    },
  ] satisfies FilterChipOption<LibraryLinkStatusFilter>[];
}

function LibraryFilterBar({
  disabled = false,
  linkStatusFilter,
  onLinkStatusFilterChange,
  onResetFilters,
  stats,
}: {
  disabled?: boolean;
  linkStatusFilter: LibraryLinkStatusFilter;
  onLinkStatusFilterChange: (value: LibraryLinkStatusFilter) => void;
  onResetFilters: () => void;
  stats: LibraryStats;
}) {
  const hasActiveFilters = linkStatusFilter !== "all";
  const linkStatusFilters = buildLinkStatusFilters(stats);

  return (
    <section
      aria-label="Library filters"
      className={`${surfaceClasses.compactCard} flex flex-wrap items-end justify-between gap-3`}
    >
      <div className="grid min-w-0 flex-1 gap-3">
        <div className="flex items-center gap-2 text-ctp-subtext0">
          <SlidersHorizontal aria-hidden="true" className="h-4 w-4" strokeWidth={1.8} />
          <h2 className={textClasses.label}>Library filters</h2>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="grid gap-1.5">
            <span className={textClasses.microEyebrow}>Link status</span>
            <FilterChipGroup
              activeValue={linkStatusFilter}
              ariaLabel="Library link status filters"
              density="compact"
              disabled={disabled}
              onValueChange={onLinkStatusFilterChange}
              options={linkStatusFilters}
            />
          </div>
        </div>
      </div>
      <ActionButton
        aria-label="Reset library filters"
        className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
        disabled={disabled || !hasActiveFilters}
        onClick={onResetFilters}
      >
        <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
        Reset
      </ActionButton>
    </section>
  );
}

function TrackStatusDot({ status }: { status: LibraryLinkStatus }) {
  return (
    <span
      aria-label={`${linkStatusLabels[status]} track`}
      className={`inline-flex h-2.5 w-2.5 rounded-full ${trackStatusDotClasses[status]}`}
      role="status"
    />
  );
}

type LocalLibraryViewProps = {
  isPending?: boolean;
  state?: LibraryViewState;
  tracksResponse?: LibraryTracksResponse;
};

export function LocalLibraryView({ isPending = false, state, tracksResponse }: LocalLibraryViewProps = {}) {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const [bulkStatus, setBulkStatus] = useState<BulkLibraryStatus | null>(null);
  const [isBulkRematching, setIsBulkRematching] = useState(false);
  const [isBulkUnlinking, setIsBulkUnlinking] = useState(false);
  const libraryTracksQuery = useLibraryTracksQuery({ enabled: tracksResponse === undefined });
  const queryTracks = useMemo(
    () => libraryTracksQuery.data?.pages.flatMap((page) => page.tracks) ?? emptyLibraryTracks,
    [libraryTracksQuery.data?.pages],
  );
  const resolvedState =
    state ??
    (tracksResponse
      ? "ready"
      : libraryTracksQuery.isPending
        ? "loading"
        : libraryTracksQuery.isError
          ? "error"
          : "ready");
  const stats = tracksResponse?.stats ?? libraryTracksQuery.data?.pages[0]?.stats ?? defaultLibraryStats;
  const tracks = tracksResponse?.tracks ?? queryTracks;
  const activeLinkStatusFilter =
    (columnFilters.find((filter) => filter.id === "link_status")?.value as LibraryLinkStatusFilter | undefined) ?? "all";
  const hasMatchingTracks =
    activeLinkStatusFilter === "all" ? tracks.length > 0 : tracks.some((track) => track.link_status === activeLinkStatusFilter);
  const selectedTracks = useMemo(() => tracks.filter((track) => rowSelection[String(track.id)]), [rowSelection, tracks]);
  const selectedRematchableTracks = useMemo(
    () => selectedTracks.filter((track) => track.link_status !== "linked"),
    [selectedTracks],
  );
  const selectedLinkedTracks = useMemo(
    () => selectedTracks.filter((track) => track.link_status === "linked"),
    [selectedTracks],
  );
  const controlsDisabled = resolvedState !== "ready" || isPending;
  const isBulkBusy = isBulkRematching || isBulkUnlinking;
  const openTrackDetail = useCallback(
    (track: LibraryTrack) => {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set("detail", String(track.id));
      setSearchParams(nextParams, { replace: false });
    },
    [searchParams, setSearchParams],
  );
  const columns = useMemo(
    () => [
      columnHelper.accessor("link_status", {
        cell: (info) => <TrackStatusDot status={info.getValue()} />,
        enableSorting: false,
        header: "Status",
        meta: {
          widthClass: "w-20",
        },
      }),
      columnHelper.accessor("title", {
        cell: (info) => (
          <span className="flex max-w-[18rem] items-center gap-2 truncate font-semibold">
            <FileAudio aria-hidden="true" className="h-4 w-4 shrink-0 text-ctp-subtext0" strokeWidth={1.8} />
            <span className="truncate">{info.getValue()}</span>
          </span>
        ),
        header: "Title",
        meta: {
          widthClass: "min-w-[12rem]",
        },
      }),
      columnHelper.accessor("artist", {
        cell: (info) => <span className="block max-w-[14rem] truncate">{info.getValue() ?? "Artist unavailable"}</span>,
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
      columnHelper.accessor((track) => track.library_root_rel_path || track.file_path, {
        cell: (info) => <span className="block max-w-[20rem] truncate font-mono text-[11px]">{info.getValue()}</span>,
        header: "File path",
        id: "file_path",
        meta: {
          hideBelow: "lg",
          widthClass: "min-w-[14rem]",
        },
      }),
    ],
    [],
  );

  const resetFilters = () => {
    setColumnFilters([]);
    setBulkStatus(null);
  };

  function handleLinkStatusFilterChange(value: LibraryLinkStatusFilter) {
    setColumnFilters(value === "all" ? [] : [{ id: "link_status", value }]);
    setBulkStatus(null);
  }

  async function invalidateLibraryTables() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: libraryQueryKeys.all }),
      queryClient.invalidateQueries({ queryKey: libraryQueryKeys.tracks() }),
      queryClient.invalidateQueries({ queryKey: playlistQueryKeys.all }),
      queryClient.invalidateQueries({ queryKey: playlistQueryKeys.proposals() }),
    ]);
  }

  async function handleBulkRematch() {
    const rematchableTracks = selectedRematchableTracks.filter((track) => track.link_status !== "linked");

    if (rematchableTracks.length === 0 || isBulkBusy) {
      return;
    }

    setIsBulkRematching(true);
    setBulkStatus(null);

    const results = await settleInChunks(rematchableTracks, 5, (track) => rematchLocalTrack(track.id));
    const successCount = results.filter((result) => result.status === "fulfilled").length;
    const failureCount = results.filter((result) => result.status === "rejected").length;

    await invalidateLibraryTables();

    setRowSelection({});
    setIsBulkRematching(false);
    setBulkStatus({
      body:
        failureCount > 0
          ? `${successCount} ${successCount === 1 ? "row was" : "rows were"} queued and ${failureCount} ${failureCount === 1 ? "row failed" : "rows failed"}.`
          : `${successCount} ${successCount === 1 ? "row was" : "rows were"} queued for matching.`,
      status: failureCount > 0 ? "error" : "success",
      title: failureCount > 0 ? "Bulk re-match partially failed" : "Bulk re-match queued",
    });
  }

  async function handleBulkUnlink() {
    const unlinkableTracks = selectedLinkedTracks.filter((track) => track.final_link_id !== null);
    const missingFinalLinkCount = selectedLinkedTracks.length - unlinkableTracks.length;

    if (selectedLinkedTracks.length === 0 || isBulkBusy) {
      return;
    }

    setIsBulkUnlinking(true);
    setBulkStatus(null);

    const results = await settleInChunks(unlinkableTracks, 5, (track) => deleteFinalLink(track.final_link_id as number));
    const successCount = results.filter((result) => result.status === "fulfilled").length;
    const failureCount = results.filter((result) => result.status === "rejected").length + missingFinalLinkCount;

    await invalidateLibraryTables();

    setRowSelection({});
    setIsBulkUnlinking(false);
    setBulkStatus({
      body:
        failureCount > 0
          ? `${successCount} ${successCount === 1 ? "link was" : "links were"} removed and ${failureCount} ${failureCount === 1 ? "row failed" : "rows failed"}.`
          : `${successCount} ${successCount === 1 ? "link was" : "links were"} removed.`,
      status: failureCount > 0 ? "error" : "success",
      title: failureCount > 0 ? "Bulk unlink partially failed" : "Bulk unlink complete",
    });
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      {isPending ? (
        <StatusMessage
          body="Library rows and counts may update when the maintenance job finishes."
          status="pending"
          title="Library refresh in progress"
        />
      ) : null}
      {bulkStatus ? <StatusMessage body={bulkStatus.body} status={bulkStatus.status} title={bulkStatus.title} /> : null}

      <section className="flex min-h-0 flex-1 flex-col gap-4">
        <LibraryFilterBar
          disabled={controlsDisabled}
          linkStatusFilter={activeLinkStatusFilter}
          onLinkStatusFilterChange={handleLinkStatusFilterChange}
          onResetFilters={resetFilters}
          stats={stats}
        />

        <div className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" aria-label="Local library tracks" role="region">
          {resolvedState === "loading" ? (
            <EmptyStateCard
              body="Fetching local track metadata, link states, and file availability."
              className="text-left"
              role="status"
              title="Loading library tracks"
            />
          ) : resolvedState === "error" ? (
            <EmptyStateCard
              body="Local library data could not be loaded."
              className="text-left"
              role="alert"
              title="Library unavailable"
              tone="error"
            />
          ) : hasMatchingTracks ? (
            <div className="grid gap-2.5">
              <DataTable
                bulkActionSlot={
                  <>
                    <ActionButton
                      className="inline-flex items-center gap-1.5"
                      disabled={selectedRematchableTracks.length === 0 || isBulkBusy}
                      onClick={handleBulkRematch}
                    >
                      <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                      {isBulkRematching ? "Matching..." : "Re-match"}
                    </ActionButton>
                    <ActionButton
                      className="inline-flex items-center gap-1.5"
                      disabled={selectedLinkedTracks.length === 0 || isBulkBusy}
                      tone="danger"
                      onClick={handleBulkUnlink}
                    >
                      <Unlink aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                      {isBulkUnlinking ? "Unlinking..." : "Unlink"}
                    </ActionButton>
                  </>
                }
                columnFilters={columnFilters}
                columns={columns}
                data={tracks}
                headerSlot={({ filteredRowCount, totalRowCount }) => (
                  <div className="flex items-center justify-between gap-3 px-1">
                    <h2 className={textClasses.label}>Local library track list</h2>
                    <p className={`${textClasses.caption} tabular-nums`}>
                      {activeLinkStatusFilter === "all" && stats.total > totalRowCount
                        ? `Showing ${totalRowCount} of ${stats.total} rows`
                        : `Showing ${filteredRowCount} of ${totalRowCount} rows`}
                    </p>
                  </div>
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
              {tracksResponse === undefined && libraryTracksQuery.hasNextPage ? (
                <div className="flex justify-center">
                  <ActionButton
                    className="inline-flex items-center gap-1.5"
                    disabled={libraryTracksQuery.isFetchingNextPage || controlsDisabled}
                    onClick={() => {
                      void libraryTracksQuery.fetchNextPage();
                    }}
                  >
                    {libraryTracksQuery.isFetchingNextPage ? "Loading..." : "Load more"}
                  </ActionButton>
                </div>
              ) : null}
            </div>
          ) : (
            <EmptyStateCard
              body="No tracks match the selected link-status filter."
              className="text-left"
              title="No matching library tracks"
            />
          )}
        </div>
      </section>
      <LocalTrackDetailDrawer localTrackId={null} open={false} syncUrl onClose={() => undefined} />
    </section>
  );
}
