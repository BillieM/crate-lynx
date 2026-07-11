import {
  createColumnHelper,
  type ColumnFiltersState,
  type RowSelectionState,
  type SortingState,
  type Updater,
} from "@tanstack/react-table";
import { FileAudio, RotateCcw, Search, SlidersHorizontal, Unlink } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { FilterChipGroup, type FilterChipOption } from "../../components/FilterChipGroup";
import { StatusMessage } from "../../components/StatusMessage";
import { TrackStatusDot } from "../../components/TrackStatusDot";
import { formatDuration } from "../../lib/formatters";
import { settleInChunks } from "../../lib/settleInChunks";
import { useDelayedInvalidate } from "../../lib/useDelayedInvalidate";
import { controlClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import { rematchLocalTrack, useRematchUnresolvedLocalTracksMutation } from "../localTracks/queries";
import { TrackDetailDrawer } from "../tracks/TrackDetailDrawer";
import { deleteFinalLink } from "../playlists/queries";
import {
  type LibraryLinkStatus,
  type LibraryStats,
  type LibraryTrack,
  type LibraryTracksResponse,
  invalidateLibraryLinkMutationQueries,
  libraryLinkMutationInvalidationKeys,
  useLibraryTracksQuery,
} from "./queries";

type LibraryViewState = "ready" | "loading" | "error";
type LibraryLinkStatusFilter = "all" | LibraryLinkStatus;

const defaultLibraryStats = {
  linked: 0,
  pending: 0,
  total: 0,
  unlinked: 0,
} satisfies LibraryStats;
const emptyLibraryTracks: LibraryTrack[] = [];

type BulkLibraryStatus = {
  body: string;
  status: "error" | "success";
  title: string;
};

type LibraryTrackWithFinalLink = LibraryTrack & {
  final_link_id: number;
};

function hasFinalLinkId(track: LibraryTrack): track is LibraryTrackWithFinalLink {
  return typeof track.final_link_id === "number" && Number.isFinite(track.final_link_id);
}

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
  onRematchUnresolved,
  onResetFilters,
  onSearchQueryChange,
  rematchUnresolvedBusy = false,
  searchQuery,
  stats,
}: {
  disabled?: boolean;
  linkStatusFilter: LibraryLinkStatusFilter;
  onLinkStatusFilterChange: (value: LibraryLinkStatusFilter) => void;
  onRematchUnresolved: () => void;
  onResetFilters: () => void;
  onSearchQueryChange: (value: string) => void;
  rematchUnresolvedBusy?: boolean;
  searchQuery: string;
  stats: LibraryStats;
}) {
  const hasActiveFilters = linkStatusFilter !== "all" || searchQuery.length > 0;
  const linkStatusFilters = buildLinkStatusFilters(stats);
  const unresolvedCount = stats.pending + stats.unlinked;

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
          <label className="grid min-w-56 gap-1.5">
            <span className={textClasses.microEyebrow}>Search library</span>
            <span className="relative">
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ctp-subtext0"
                strokeWidth={1.8}
              />
              <input
                aria-label="Search local library"
                className="min-h-9 w-full rounded-[8px] border border-ctp-surface1 bg-ctp-base px-3 pl-8 text-[13px] text-ctp-text outline-none transition focus:border-ctp-blue focus:ring-2 focus:ring-ctp-blue/25"
                disabled={disabled}
                maxLength={200}
                placeholder="Title, artist, album, or path"
                type="search"
                value={searchQuery}
                onChange={(event) => onSearchQueryChange(event.target.value)}
              />
            </span>
          </label>
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
      <div className="flex flex-wrap items-center justify-end gap-2">
        <ActionButton
          className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
          disabled={disabled || unresolvedCount === 0 || rematchUnresolvedBusy}
          onClick={onRematchUnresolved}
        >
          <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
          {rematchUnresolvedBusy ? "Queueing..." : "Re-match all unresolved"}
        </ActionButton>
        <ActionButton
          aria-label="Reset library filters"
          className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
          disabled={disabled || !hasActiveFilters}
          onClick={onResetFilters}
        >
          <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
          Reset
        </ActionButton>
      </div>
    </section>
  );
}

type LocalLibraryViewProps = {
  isPending?: boolean;
  state?: LibraryViewState;
  tracksResponse?: LibraryTracksResponse;
};

export function LocalLibraryView({ isPending = false, state, tracksResponse }: LocalLibraryViewProps = {}) {
  const queryClient = useQueryClient();
  const delayedInvalidate = useDelayedInvalidate();
  const [searchParams, setSearchParams] = useSearchParams();
  const searchQuery = searchParams.get("library_q") ?? "";
  const requestedLinkStatus = searchParams.get("library_status");
  const activeLinkStatusFilter: LibraryLinkStatusFilter =
    requestedLinkStatus === "linked" || requestedLinkStatus === "pending" || requestedLinkStatus === "unlinked"
      ? requestedLinkStatus
      : "all";
  const requestedSort = searchParams.get("library_sort");
  const sortField =
    requestedSort === "title" ||
    requestedSort === "artist" ||
    requestedSort === "album" ||
    requestedSort === "duration_ms" ||
    requestedSort === "link_status"
      ? requestedSort
      : "id";
  const sortDirection = searchParams.get("library_direction") === "desc" ? "desc" : "asc";
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>(
    activeLinkStatusFilter === "all" ? [] : [{ id: "link_status", value: activeLinkStatusFilter }],
  );
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>(sortField === "id" ? [] : [{ id: sortField, desc: sortDirection === "desc" }]);
  const [bulkStatus, setBulkStatus] = useState<BulkLibraryStatus | null>(null);
  const [isBulkRematching, setIsBulkRematching] = useState(false);
  const [isBulkUnlinking, setIsBulkUnlinking] = useState(false);
  const rematchUnresolvedMutation = useRematchUnresolvedLocalTracksMutation();
  const libraryTracksQuery = useLibraryTracksQuery({
    direction: sortDirection,
    enabled: tracksResponse === undefined,
    linkStatus: activeLinkStatusFilter === "all" ? null : activeLinkStatusFilter,
    query: searchQuery,
    sort: sortField,
  });
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
  const filteredTotal = tracksResponse?.filtered_total ?? libraryTracksQuery.data?.pages[0]?.filtered_total ?? 0;
  const tracks = tracksResponse?.tracks ?? queryTracks;
  const hasMatchingTracks = tracks.length > 0;
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
  const unresolvedCount = stats.pending + stats.unlinked;
  const isBulkBusy = isBulkRematching || isBulkUnlinking || rematchUnresolvedMutation.isPending;
  const openTrackDetail = useCallback(
    (track: LibraryTrack) => {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set("detail", `local:${track.id}`);
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
    setSorting([]);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete("library_q");
    nextParams.delete("library_status");
    nextParams.delete("library_sort");
    nextParams.delete("library_direction");
    setSearchParams(nextParams, { replace: true });
    setBulkStatus(null);
  };

  function handleLinkStatusFilterChange(value: LibraryLinkStatusFilter) {
    setColumnFilters(value === "all" ? [] : [{ id: "link_status", value }]);
    const nextParams = new URLSearchParams(searchParams);
    if (value === "all") {
      nextParams.delete("library_status");
    } else {
      nextParams.set("library_status", value);
    }
    setSearchParams(nextParams, { replace: true });
    setBulkStatus(null);
  }

  function handleSearchQueryChange(value: string) {
    const nextParams = new URLSearchParams(searchParams);
    if (value) {
      nextParams.set("library_q", value);
    } else {
      nextParams.delete("library_q");
    }
    setSearchParams(nextParams, { replace: true });
    setRowSelection({});
  }

  function handleSortingChange(updater: Updater<SortingState>) {
    const nextSorting = typeof updater === "function" ? updater(sorting) : updater;
    setSorting(nextSorting);
    const nextParams = new URLSearchParams(searchParams);
    const firstSort = nextSorting[0];
    if (!firstSort) {
      nextParams.delete("library_sort");
      nextParams.delete("library_direction");
    } else {
      nextParams.set("library_sort", firstSort.id);
      nextParams.set("library_direction", firstSort.desc ? "desc" : "asc");
    }
    setSearchParams(nextParams, { replace: true });
    setRowSelection({});
  }

  async function invalidateLibraryTables() {
    await invalidateLibraryLinkMutationQueries(queryClient);
  }

  function scheduleRematchRefresh() {
    delayedInvalidate(libraryLinkMutationInvalidationKeys());
  }

  async function handleRematchUnresolved() {
    if (unresolvedCount === 0 || controlsDisabled || rematchUnresolvedMutation.isPending) {
      return;
    }

    setBulkStatus(null);

    try {
      await rematchUnresolvedMutation.mutateAsync();
      await invalidateLibraryTables();
      scheduleRematchRefresh();
      setRowSelection({});
      setBulkStatus({
        body: "Pending and unlinked local tracks were queued for re-matching.",
        status: "success",
        title: "Unresolved re-match queued",
      });
    } catch {
      setBulkStatus({
        body: "Pending and unlinked local tracks could not be queued for re-matching.",
        status: "error",
        title: "Unresolved re-match failed",
      });
    }
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
    scheduleRematchRefresh();

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
    const unlinkableTracks = selectedLinkedTracks.filter(hasFinalLinkId);
    const missingFinalLinkCount = selectedLinkedTracks.length - unlinkableTracks.length;

    if (selectedLinkedTracks.length === 0 || isBulkBusy) {
      return;
    }

    setIsBulkUnlinking(true);
    setBulkStatus(null);

    const results = await settleInChunks(unlinkableTracks, 5, (track) => deleteFinalLink(track.final_link_id));
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
          disabled={controlsDisabled || isBulkBusy}
          linkStatusFilter={activeLinkStatusFilter}
          onLinkStatusFilterChange={handleLinkStatusFilterChange}
          onRematchUnresolved={handleRematchUnresolved}
          onResetFilters={resetFilters}
          onSearchQueryChange={handleSearchQueryChange}
          rematchUnresolvedBusy={rematchUnresolvedMutation.isPending}
          searchQuery={searchQuery}
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
                        ? `Showing ${totalRowCount} of ${filteredTotal} matching rows (${stats.total} total)`
                        : `Showing ${filteredRowCount} of ${filteredTotal} matching rows`}
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
                onSortingChange={handleSortingChange}
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
              body={
                stats.total === 0
                  ? "Import or sync local music to begin reviewing the library."
                  : "No tracks match the current search and link-status filters. Reset the filters to see the full library."
              }
              className="text-left"
              title={stats.total === 0 ? "Library is empty" : "No matching library tracks"}
            />
          )}
        </div>
      </section>
      <TrackDetailDrawer open={false} syncUrl onClose={() => undefined} />
    </section>
  );
}
