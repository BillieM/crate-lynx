import { createColumnHelper, type RowSelectionState, type SortingState } from "@tanstack/react-table";
import { Clock3, FileAudio, Link2, Music2, RotateCcw, SlidersHorizontal, Unlink } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { FilterChipGroup, type FilterChipOption } from "../../components/FilterChipGroup";
import { Pill, type PillTone } from "../../components/Pill";
import { StatusMessage } from "../../components/StatusMessage";
import { controlClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import { trackStatusDotClasses } from "../../styles/toneClasses";
import { LocalTrackDetailDrawer } from "../localTracks/LocalTrackDetailDrawer";
import { deleteFinalLink, playlistQueryKeys } from "../playlists/queries";
import {
  type LibraryFileStatus,
  type LibraryLinkStatus,
  type LibraryStats,
  type LibraryTrack,
  type LibraryTracksResponse,
  libraryQueryKeys,
  useLibraryTracksQuery,
} from "./queries";

type LibraryViewState = "ready" | "loading" | "error";
type LibraryLinkStatusFilter = "all" | "linked" | "pending" | "unlinked";
type LibraryMatchMethodFilter = "all" | "isrc" | "tag" | "manual";
type LibraryFileStatusFilter = "all" | "available" | "missing" | "beets_failed";

type LibraryStat = {
  description: string;
  icon: typeof Music2;
  label: string;
  toneClass: string;
  value: number;
};

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

const libraryStatConfigs = [
  {
    description: "All imported local tracks",
    icon: Music2,
    label: "Total",
    statKey: "total",
    toneClass: "bg-ctp-blue/18 text-ctp-blue ring-ctp-blue/30",
  },
  {
    description: "Tracks with approved streaming links",
    icon: Link2,
    label: "Linked",
    statKey: "linked",
    toneClass: "bg-ctp-green/18 text-ctp-green ring-ctp-green/30",
  },
  {
    description: "Tracks with suggested links awaiting review",
    icon: Clock3,
    label: "Pending",
    statKey: "pending",
    toneClass: "bg-ctp-yellow/18 text-ctp-yellow ring-ctp-yellow/30",
  },
  {
    description: "Tracks without a usable match",
    icon: Unlink,
    label: "Unlinked",
    statKey: "unlinked",
    toneClass: "bg-ctp-red/18 text-ctp-red ring-ctp-red/30",
  },
] satisfies (Omit<LibraryStat, "value"> & { statKey: keyof LibraryStats })[];

const matchMethodFilters = [
  { label: "All methods", value: "all" },
  { label: "ISRC", value: "isrc" },
  { label: "Tag", value: "tag" },
  { label: "Manual", value: "manual" },
] satisfies { label: string; value: LibraryMatchMethodFilter }[];

const fileStatusFilters = [
  { label: "All files", value: "all" },
  { label: "Available locally", value: "available" },
  { label: "Missing locally", value: "missing" },
  { label: "Beets failed", value: "beets_failed" },
] satisfies { label: string; value: LibraryFileStatusFilter }[];

const linkStatusLabels = {
  linked: "Linked",
  pending: "Pending",
  unlinked: "Unlinked",
} satisfies Record<LibraryLinkStatus, string>;

const matchMethodLabels = {
  isrc: "ISRC",
  manual: "Manual",
  tag: "Tag",
} satisfies Record<Exclude<LibraryMatchMethodFilter, "all">, string>;

const fileStatusLabels = {
  available: "Available",
  beets_failed: "Beets failed",
  missing: "Missing",
} satisfies Record<LibraryFileStatus, string>;

const fileStatusTones = {
  available: "success",
  beets_failed: "danger",
  missing: "pending",
} satisfies Record<LibraryFileStatus, PillTone>;

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

function formatDuration(durationMs: number | null) {
  if (durationMs === null || durationMs < 0) {
    return "Unknown";
  }

  const totalSeconds = Math.floor(durationMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatMatchMethod(matchMethod: LibraryTrack["match_method"]) {
  if (matchMethod === null) {
    return "No match";
  }

  return matchMethodLabels[matchMethod as Exclude<LibraryMatchMethodFilter, "all">] ?? matchMethod;
}

function filterLibraryTracks(
  tracks: LibraryTrack[],
  linkStatusFilter: LibraryLinkStatusFilter,
  matchMethodFilter: LibraryMatchMethodFilter,
  fileStatusFilter: LibraryFileStatusFilter,
) {
  return tracks.filter((track) => {
    const matchesLinkStatus = linkStatusFilter === "all" || track.link_status === linkStatusFilter;
    const matchesMatchMethod =
      matchMethodFilter === "all" || (track.match_method !== null && track.match_method === matchMethodFilter);
    const matchesFileStatus = fileStatusFilter === "all" || track.file_status === fileStatusFilter;

    return matchesLinkStatus && matchesMatchMethod && matchesFileStatus;
  });
}

function LibraryStatCard({ stat }: { stat: LibraryStat }) {
  const Icon = stat.icon;

  return (
    <section className={`${surfaceClasses.compactCard} min-h-28`} aria-label={`${stat.label} tracks`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={`${textClasses.microEyebrow} text-ctp-subtext0`}>{stat.label}</p>
          <p className="mt-2 text-[28px] font-semibold leading-none tabular-nums text-ctp-text">
            {stat.value.toLocaleString()}
          </p>
        </div>
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] ring-1 ring-inset ${stat.toneClass}`}>
          <Icon aria-hidden="true" className="h-[18px] w-[18px]" strokeWidth={1.8} />
        </div>
      </div>
      <p className={`mt-3 ${textClasses.caption}`}>{stat.description}</p>
    </section>
  );
}

function LibrarySelectFilter<TValue extends string>({
  disabled = false,
  label,
  onValueChange,
  options,
  value,
}: {
  disabled?: boolean;
  label: string;
  onValueChange: (value: TValue) => void;
  options: { label: string; value: TValue }[];
  value: TValue;
}) {
  return (
    <label className="grid min-w-[11rem] gap-1.5">
      <span className={textClasses.microEyebrow}>{label}</span>
      <select
        className={`${controlClasses.controlRadius} min-h-9 border border-ctp-surface1 bg-ctp-surface0 px-2.5 text-[12px] font-semibold text-ctp-text outline-none transition-colors hover:border-ctp-overlay0 focus:border-ctp-blue focus:ring-2 focus:ring-ctp-blue/20`}
        disabled={disabled}
        onChange={(event) => onValueChange(event.target.value as TValue)}
        value={value}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function LibraryFilterBar({
  disabled = false,
  fileStatusFilter,
  linkStatusFilter,
  matchMethodFilter,
  onFileStatusFilterChange,
  onLinkStatusFilterChange,
  onMatchMethodFilterChange,
  onResetFilters,
  stats,
}: {
  disabled?: boolean;
  fileStatusFilter: LibraryFileStatusFilter;
  linkStatusFilter: LibraryLinkStatusFilter;
  matchMethodFilter: LibraryMatchMethodFilter;
  onFileStatusFilterChange: (value: LibraryFileStatusFilter) => void;
  onLinkStatusFilterChange: (value: LibraryLinkStatusFilter) => void;
  onMatchMethodFilterChange: (value: LibraryMatchMethodFilter) => void;
  onResetFilters: () => void;
  stats: LibraryStats;
}) {
  const hasActiveFilters = linkStatusFilter !== "all" || matchMethodFilter !== "all" || fileStatusFilter !== "all";
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
          <LibrarySelectFilter
            disabled={disabled}
            label="Match method"
            onValueChange={onMatchMethodFilterChange}
            options={matchMethodFilters}
            value={matchMethodFilter}
          />
          <LibrarySelectFilter
            disabled={disabled}
            label="File status"
            onValueChange={onFileStatusFilterChange}
            options={fileStatusFilters}
            value={fileStatusFilter}
          />
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

function LibraryTrackActions({
  onOpenTrackDetail,
  track,
}: {
  onOpenTrackDetail: (track: LibraryTrack) => void;
  track: LibraryTrack;
}) {
  const queryClient = useQueryClient();
  const rematchMutation = useMutation({
    mutationFn: rematchLocalTrack,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: libraryQueryKeys.all }),
        queryClient.invalidateQueries({ queryKey: libraryQueryKeys.tracks() }),
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.all }),
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.proposals() }),
      ]);
    },
  });
  const canRematch = track.link_status === "unlinked";

  return (
    <div className="flex flex-col items-end gap-1">
      <ActionButton className={controlClasses.actionButtonCompact} onClick={() => onOpenTrackDetail(track)}>
        Details
      </ActionButton>
      {canRematch ? (
        <div className="flex flex-col items-end gap-1">
          <ActionButton
            className={controlClasses.actionButtonCompact}
            disabled={rematchMutation.isPending}
            onClick={() => rematchMutation.mutate(track.id)}
          >
            {rematchMutation.isPending ? "Matching..." : "Re-match"}
          </ActionButton>
          {rematchMutation.isSuccess ? <p className={`${textClasses.finePrint} text-ctp-green`}>Re-match queued.</p> : null}
          {rematchMutation.isError ? <p className={`${textClasses.finePrint} text-ctp-red`}>Re-match failed.</p> : null}
        </div>
      ) : null}
    </div>
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
  const [linkStatusFilter, setLinkStatusFilter] = useState<LibraryLinkStatusFilter>("all");
  const [matchMethodFilter, setMatchMethodFilter] = useState<LibraryMatchMethodFilter>("all");
  const [fileStatusFilter, setFileStatusFilter] = useState<LibraryFileStatusFilter>("all");
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const [bulkStatus, setBulkStatus] = useState<BulkLibraryStatus | null>(null);
  const [isBulkRematching, setIsBulkRematching] = useState(false);
  const [isBulkUnlinking, setIsBulkUnlinking] = useState(false);
  const libraryTracksQuery = useLibraryTracksQuery();
  const resolvedState =
    state ?? (libraryTracksQuery.isPending ? "loading" : libraryTracksQuery.isError ? "error" : "ready");
  const stats = tracksResponse?.stats ?? libraryTracksQuery.data?.stats ?? defaultLibraryStats;
  const tracks = tracksResponse?.tracks ?? libraryTracksQuery.data?.tracks ?? emptyLibraryTracks;
  const libraryStats = libraryStatConfigs.map((stat) => ({
    ...stat,
    value: stats[stat.statKey],
  }));
  const visibleTracks = useMemo(
    () => filterLibraryTracks([...tracks], linkStatusFilter, matchMethodFilter, fileStatusFilter),
    [fileStatusFilter, linkStatusFilter, matchMethodFilter, tracks],
  );
  const selectedTracks = useMemo(() => tracks.filter((track) => rowSelection[String(track.id)]), [rowSelection, tracks]);
  const selectedUnlinkedTracks = useMemo(
    () => selectedTracks.filter((track) => track.link_status === "unlinked"),
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
      columnHelper.accessor("match_method", {
        cell: (info) => {
          const value = info.getValue();
          return <Pill tone={value === null ? "neutral" : "info"}>{formatMatchMethod(value)}</Pill>;
        },
        header: "Match method",
        meta: {
          hideBelow: "lg",
          widthClass: "w-32",
        },
      }),
      columnHelper.accessor("file_status", {
        cell: (info) => <Pill tone={fileStatusTones[info.getValue()]}>{fileStatusLabels[info.getValue()]}</Pill>,
        header: "File status",
        meta: {
          widthClass: "w-32",
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
      columnHelper.display({
        cell: (info) => (
          <div className="flex justify-end">
            <LibraryTrackActions track={info.row.original} onOpenTrackDetail={openTrackDetail} />
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

  const resetFilters = () => {
    setLinkStatusFilter("all");
    setMatchMethodFilter("all");
    setFileStatusFilter("all");
    setRowSelection({});
    setBulkStatus(null);
  };

  function handleLinkStatusFilterChange(value: LibraryLinkStatusFilter) {
    setLinkStatusFilter(value);
    setRowSelection({});
    setBulkStatus(null);
  }

  function handleMatchMethodFilterChange(value: LibraryMatchMethodFilter) {
    setMatchMethodFilter(value);
    setRowSelection({});
    setBulkStatus(null);
  }

  function handleFileStatusFilterChange(value: LibraryFileStatusFilter) {
    setFileStatusFilter(value);
    setRowSelection({});
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
    if (selectedUnlinkedTracks.length === 0 || isBulkBusy) {
      return;
    }

    setIsBulkRematching(true);
    setBulkStatus(null);

    const results = await settleInChunks(selectedUnlinkedTracks, 5, (track) => rematchLocalTrack(track.id));
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

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Library stats">
        {libraryStats.map((stat) => (
          <LibraryStatCard key={stat.label} stat={stat} />
        ))}
      </div>

      <section className="flex min-h-0 flex-1 flex-col gap-4">
        <LibraryFilterBar
          disabled={controlsDisabled}
          fileStatusFilter={fileStatusFilter}
          linkStatusFilter={linkStatusFilter}
          matchMethodFilter={matchMethodFilter}
          onFileStatusFilterChange={handleFileStatusFilterChange}
          onLinkStatusFilterChange={handleLinkStatusFilterChange}
          onMatchMethodFilterChange={handleMatchMethodFilterChange}
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
          ) : visibleTracks.length > 0 ? (
            <div className="grid gap-2.5">
              <div className="flex items-center justify-between gap-3 px-1">
                <h2 className={textClasses.label}>Local library track list</h2>
                <p className={`${textClasses.caption} tabular-nums`}>
                  Showing {visibleTracks.length} of {tracks.length} rows
                </p>
              </div>
              <DataTable
                bulkActionSlot={
                  <>
                    <ActionButton
                      className="inline-flex items-center gap-1.5"
                      disabled={selectedUnlinkedTracks.length === 0 || isBulkBusy}
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
                columns={columns}
                data={visibleTracks}
                rowId={(track) => String(track.id)}
                rowSelection={rowSelection}
                sorting={sorting}
                stickyHeader
                onActivate={openTrackDetail}
                onRowSelectionChange={setRowSelection}
                onSortingChange={setSorting}
              />
            </div>
          ) : (
            <EmptyStateCard
              body="No tracks match the selected facets."
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
