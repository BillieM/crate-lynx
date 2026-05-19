import { createColumnHelper, type RowSelectionState, type SortingState } from "@tanstack/react-table";
import { EyeOff, FileQuestion, History, RefreshCcw, WandSparkles, XCircle } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { FilterChipGroup, type FilterChipOption } from "../../components/FilterChipGroup";
import { StatusMessage } from "../../components/StatusMessage";
import { settleInChunks } from "../../lib/settleInChunks";
import { surfaceClasses, textClasses } from "../../styles/componentClasses";
import {
  ignoreUnidentifiedTrack,
  invalidateUnidentifiedQueries,
  rescueLocalTrackMetadata,
  retryUnidentifiedTrack,
  type UnidentifiedResponse,
  type UnidentifiedTrack,
  useUnidentifiedTracksQuery,
} from "./queries";

type MaintenanceViewState = "ready" | "loading" | "error";
type UnidentifiedTab = "active" | "ignored";

const emptyUnidentifiedTracks: UnidentifiedTrack[] = [];
const columnHelper = createColumnHelper<UnidentifiedTrack>();

type BulkActionStatus = {
  body: string;
  status: "error" | "success";
  title: string;
};

function formatTimestamp(timestamp: string | null) {
  if (!timestamp) {
    return "Not available";
  }

  return timestamp.replace("T", " ").replace("Z", "").slice(0, 16);
}

function formatSourceSize(sourceSize: number | null) {
  if (sourceSize === null) {
    return "Unknown";
  }

  return `${sourceSize.toLocaleString()} B`;
}

function UnidentifiedRowActions({
  actionsDisabled = false,
  bulkActionRunning = false,
  track,
}: {
  actionsDisabled?: boolean;
  bulkActionRunning?: boolean;
  track: UnidentifiedTrack;
}) {
  const queryClient = useQueryClient();
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const retryMutation = useMutation({
    mutationFn: retryUnidentifiedTrack,
    onError: () => setStatusMessage("Retry failed"),
    onSuccess: async (response) => {
      setStatusMessage(response.job_id ? "Retry queued" : "Retry already queued");
      await invalidateUnidentifiedQueries(queryClient);
    },
  });
  const ignoreMutation = useMutation({
    mutationFn: ignoreUnidentifiedTrack,
    onError: () => setStatusMessage("Ignore failed"),
    onSuccess: async () => {
      setStatusMessage("Source ignored");
      await invalidateUnidentifiedQueries(queryClient);
    },
  });
  const rescueMutation = useMutation({
    mutationFn: rescueLocalTrackMetadata,
    onError: () => setStatusMessage("Rescue failed"),
    onSuccess: () => setStatusMessage("Rescue complete"),
  });
  const actionPending = retryMutation.isPending || ignoreMutation.isPending || rescueMutation.isPending;
  const disabled = actionsDisabled || bulkActionRunning || actionPending;
  const canRescue = track.local_track_id !== null;
  const pendingStatus = retryMutation.isPending
    ? "Queueing retry..."
    : ignoreMutation.isPending
      ? "Ignoring..."
      : rescueMutation.isPending
        ? "Rescuing metadata..."
        : null;
  const hasError = retryMutation.isError || ignoreMutation.isError || rescueMutation.isError;

  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5">
      <ActionButton
        aria-label={`Retry ${track.filename}`}
        className="inline-flex items-center gap-1.5"
        disabled={disabled}
        onClick={() => {
          setStatusMessage(null);
          retryMutation.mutate(track.id);
        }}
      >
        <RefreshCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
        {retryMutation.isPending ? "Retrying..." : "Retry"}
      </ActionButton>
      {track.ignored_at === null ? (
        <ActionButton
          aria-label={`Ignore ${track.filename}`}
          className="inline-flex items-center gap-1.5"
          disabled={disabled}
          onClick={() => {
            setStatusMessage(null);
            ignoreMutation.mutate(track.id);
          }}
        >
          <EyeOff aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
          {ignoreMutation.isPending ? "Ignoring..." : "Ignore"}
        </ActionButton>
      ) : null}
      {canRescue ? (
        <ActionButton
          aria-label={`Rescue ${track.filename}`}
          className="inline-flex items-center gap-1.5"
          disabled={disabled}
          onClick={() => {
            if (track.local_track_id !== null) {
              setStatusMessage(null);
              rescueMutation.mutate(track.local_track_id);
            }
          }}
        >
          <WandSparkles aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
          {rescueMutation.isPending ? "Rescuing..." : "Rescue"}
        </ActionButton>
      ) : null}
      {pendingStatus || statusMessage ? (
        <span
          aria-live="polite"
          className={`${textClasses.caption} ${hasError ? "text-ctp-red" : "text-ctp-subtext0"}`}
          role="status"
        >
          {pendingStatus ?? statusMessage}
        </span>
      ) : null}
    </div>
  );
}

function UnidentifiedSummaryCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof FileQuestion;
  label: string;
  value: string;
}) {
  return (
    <section className={`${surfaceClasses.compactCard} min-h-24`} aria-label={label}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={`${textClasses.microEyebrow} text-ctp-subtext0`}>{label}</p>
          <p className="mt-2 text-[24px] font-semibold leading-none tabular-nums text-ctp-text">{value}</p>
        </div>
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] bg-ctp-red/18 text-ctp-red ring-1 ring-inset ring-ctp-red/30">
          <Icon aria-hidden="true" className="h-[18px] w-[18px]" strokeWidth={1.8} />
        </div>
      </div>
    </section>
  );
}

type UnidentifiedViewProps = {
  isPending?: boolean;
  state?: MaintenanceViewState;
  tracksResponse?: UnidentifiedResponse;
};

export function UnidentifiedView({ isPending = false, state, tracksResponse }: UnidentifiedViewProps = {}) {
  const queryClient = useQueryClient();
  const unidentifiedQuery = useUnidentifiedTracksQuery({ enabled: tracksResponse === undefined });
  const [activeTab, setActiveTab] = useState<UnidentifiedTab>("active");
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const [bulkActionStatus, setBulkActionStatus] = useState<BulkActionStatus | null>(null);
  const [isBulkActionRunning, setIsBulkActionRunning] = useState(false);
  const resolvedState =
    state ??
    (tracksResponse
      ? "ready"
      : unidentifiedQuery.isPending
        ? "loading"
        : unidentifiedQuery.isError
          ? "error"
          : "ready");
  const tracks = tracksResponse?.tracks ?? unidentifiedQuery.data?.tracks ?? emptyUnidentifiedTracks;
  const activeTracks = useMemo(() => tracks.filter((track) => track.ignored_at === null), [tracks]);
  const ignoredTracks = useMemo(() => tracks.filter((track) => track.ignored_at !== null), [tracks]);
  const visibleTracks = activeTab === "active" ? activeTracks : ignoredTracks;
  const totalAttemptCount = tracks.reduce((total, track) => total + track.attempt_count, 0);
  const actionsDisabled = resolvedState !== "ready" || isPending;
  const selectedTracks = useMemo(
    () => visibleTracks.filter((track) => rowSelection[String(track.id)]),
    [rowSelection, visibleTracks],
  );
  const selectedIgnorableTracks = useMemo(
    () => selectedTracks.filter((track) => track.ignored_at === null),
    [selectedTracks],
  );
  const tabOptions = useMemo<FilterChipOption<UnidentifiedTab>[]>(
    () => [
      { count: activeTracks.length, label: "Active", tone: "unlinked", value: "active" },
      { count: ignoredTracks.length, label: "Ignored", tone: "pending", value: "ignored" },
    ],
    [activeTracks.length, ignoredTracks.length],
  );
  const columns = useMemo(
    () => [
      columnHelper.display({
        cell: (info) => (
          <span
            aria-label={info.row.original.ignored_at === null ? "Active failed source" : "Ignored failed source"}
            className={`inline-flex h-2.5 w-2.5 rounded-full ${
              info.row.original.ignored_at === null
                ? "bg-ctp-red shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-red)_16%,transparent)]"
                : "bg-ctp-yellow shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-yellow)_16%,transparent)]"
            }`}
            role="status"
          />
        ),
        enableSorting: false,
        header: "Status",
        meta: {
          widthClass: "w-20",
        },
      }),
      columnHelper.accessor("filename", {
        cell: (info) => (
          <span className="block max-w-[18rem] truncate font-semibold">
            {info.getValue()}
            {info.row.original.ignored_at !== null ? (
              <span className="ml-2 rounded-full bg-ctp-yellow/18 px-2 py-0.5 text-[10px] font-semibold uppercase text-ctp-yellow ring-1 ring-inset ring-ctp-yellow/30">
                Ignored
              </span>
            ) : null}
          </span>
        ),
        header: "Filename",
        meta: {
          widthClass: "min-w-[12rem]",
        },
      }),
      columnHelper.accessor("source_path", {
        cell: (info) => <span className="block max-w-[18rem] truncate">{info.getValue()}</span>,
        header: "Source path",
        meta: {
          widthClass: "min-w-[14rem]",
        },
      }),
      columnHelper.accessor("attempt_count", {
        cell: (info) => <span className="tabular-nums">{info.getValue()}</span>,
        header: "Attempts",
        meta: {
          align: "end",
          widthClass: "w-24",
        },
      }),
      columnHelper.accessor("first_failed_at", {
        cell: (info) => <span className="tabular-nums">{formatTimestamp(info.getValue())}</span>,
        header: "First failed",
        meta: {
          hideBelow: "lg",
          widthClass: "w-36",
        },
      }),
      columnHelper.accessor("failed_at", {
        cell: (info) => <span className="tabular-nums">{formatTimestamp(info.getValue())}</span>,
        header: "Last failed",
        meta: {
          hideBelow: "md",
          widthClass: "w-36",
        },
      }),
      columnHelper.accessor("source_size", {
        cell: (info) => <span className="tabular-nums">{formatSourceSize(info.getValue())}</span>,
        header: "Size",
        meta: {
          align: "end",
          hideBelow: "lg",
          widthClass: "w-28",
        },
      }),
      columnHelper.accessor("failure_reason", {
        cell: (info) => <span className="block max-w-[18rem] truncate">{info.getValue()}</span>,
        header: "Reason",
        meta: {
          hideBelow: "lg",
          widthClass: "min-w-[14rem]",
        },
      }),
      columnHelper.accessor("local_track_id", {
        cell: (info) => <span className="font-mono text-[11px]">{info.getValue() ?? "None"}</span>,
        header: "Local track ID",
        meta: {
          align: "end",
          hideBelow: "md",
          widthClass: "w-32",
        },
      }),
      columnHelper.display({
        cell: (info) => (
          <UnidentifiedRowActions
            actionsDisabled={actionsDisabled}
            bulkActionRunning={isBulkActionRunning}
            track={info.row.original}
          />
        ),
        enableSorting: false,
        header: "Actions",
        meta: {
          align: "end",
          widthClass: "w-64",
        },
      }),
    ],
    [actionsDisabled, isBulkActionRunning],
  );

  async function handleBulkRetry() {
    if (selectedTracks.length === 0 || isBulkActionRunning) {
      return;
    }

    setIsBulkActionRunning(true);
    setBulkActionStatus(null);
    try {
      const results = await settleInChunks(selectedTracks, 5, (track) => retryUnidentifiedTrack(track.id));
      const successCount = results.filter((result) => result.status === "fulfilled").length;
      const failureCount = results.filter((result) => result.status === "rejected").length;

      await invalidateUnidentifiedQueries(queryClient);
      setRowSelection({});
      setBulkActionStatus({
        body:
          failureCount > 0
            ? `${successCount} ${successCount === 1 ? "source was" : "sources were"} queued, and ${failureCount} ${failureCount === 1 ? "failed" : "failed"}.`
            : `${successCount} ${successCount === 1 ? "source was" : "sources were"} queued for retry.`,
        status: failureCount > 0 ? "error" : "success",
        title: failureCount > 0 ? "Bulk retry partially failed" : "Bulk retry queued",
      });
    } finally {
      setIsBulkActionRunning(false);
    }
  }

  async function handleBulkIgnore() {
    if (selectedIgnorableTracks.length === 0 || isBulkActionRunning) {
      return;
    }

    setIsBulkActionRunning(true);
    setBulkActionStatus(null);
    try {
      const results = await settleInChunks(selectedIgnorableTracks, 5, (track) => ignoreUnidentifiedTrack(track.id));
      const skippedCount = selectedTracks.length - selectedIgnorableTracks.length;
      const successCount = results.filter((result) => result.status === "fulfilled").length;
      const failureCount = results.filter((result) => result.status === "rejected").length;

      await invalidateUnidentifiedQueries(queryClient);
      setRowSelection({});
      setBulkActionStatus({
        body:
          failureCount > 0 || skippedCount > 0
            ? `${successCount} ${successCount === 1 ? "source was" : "sources were"} ignored, ${failureCount} ${failureCount === 1 ? "failed" : "failed"}, and ${skippedCount} ${skippedCount === 1 ? "row was" : "rows were"} skipped.`
            : `${successCount} ${successCount === 1 ? "source was" : "sources were"} ignored.`,
        status: failureCount > 0 ? "error" : "success",
        title: failureCount > 0 ? "Bulk ignore partially failed" : "Bulk ignore complete",
      });
    } finally {
      setIsBulkActionRunning(false);
    }
  }

  function handleTabChange(nextTab: UnidentifiedTab) {
    setActiveTab(nextTab);
    setRowSelection({});
    setBulkActionStatus(null);
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      {isPending ? (
        <StatusMessage
          body="Metadata rescue availability may update when the import review finishes."
          status="pending"
          title="Unidentified review in progress"
        />
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3" aria-label="Unidentified summary">
        <UnidentifiedSummaryCard icon={FileQuestion} label="Failed sources" value={tracks.length.toString()} />
        <UnidentifiedSummaryCard icon={History} label="Total attempts" value={totalAttemptCount.toString()} />
        <UnidentifiedSummaryCard icon={XCircle} label="Active" value={activeTracks.length.toString()} />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" aria-label="Unidentified tracks" role="region">
        {bulkActionStatus ? (
          <StatusMessage body={bulkActionStatus.body} status={bulkActionStatus.status} title={bulkActionStatus.title} />
        ) : null}
        {resolvedState === "loading" ? (
          <EmptyStateCard
            body="Checking Beets-failed imports."
            className="text-left"
            role="status"
            title="Loading unidentified tracks"
          />
        ) : resolvedState === "error" ? (
          <EmptyStateCard
            body="The unidentified import queue could not be loaded."
            className="text-left"
            role="alert"
            title="Unidentified queue unavailable"
            tone="error"
          />
        ) : tracks.length > 0 ? (
          <div className="grid gap-2.5">
            <div className="flex flex-wrap items-center justify-between gap-3 px-1">
              <div className="grid gap-2">
                <h2 className={textClasses.label}>Beets failed source list</h2>
                <FilterChipGroup
                  activeValue={activeTab}
                  ariaLabel="Unidentified status"
                  density="compact"
                  options={tabOptions}
                  onValueChange={handleTabChange}
                />
              </div>
              <p className={`${textClasses.caption} tabular-nums`}>
                {visibleTracks.length} {visibleTracks.length === 1 ? "source" : "sources"}
              </p>
            </div>
            {visibleTracks.length > 0 ? (
              <DataTable
                bulkActionSlot={
                  <>
                    <ActionButton
                      className="inline-flex items-center gap-1.5"
                      disabled={selectedTracks.length === 0 || actionsDisabled || isBulkActionRunning}
                      onClick={handleBulkRetry}
                    >
                      <RefreshCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                      {isBulkActionRunning ? "Working..." : "Retry"}
                    </ActionButton>
                    <ActionButton
                      className="inline-flex items-center gap-1.5"
                      disabled={selectedIgnorableTracks.length === 0 || actionsDisabled || isBulkActionRunning}
                      onClick={handleBulkIgnore}
                    >
                      <EyeOff aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                      {isBulkActionRunning ? "Working..." : "Ignore"}
                    </ActionButton>
                  </>
                }
                columns={columns}
                data={visibleTracks}
                rowId={(track) => String(track.id)}
                rowSelection={rowSelection}
                sorting={sorting}
                stickyHeader
                onRowSelectionChange={setRowSelection}
                onSortingChange={setSorting}
              />
            ) : (
              <EmptyStateCard
                body={
                  activeTab === "active"
                    ? "No failed imports are waiting for action."
                    : "No failed imports are currently ignored."
                }
                className="text-left"
                title={activeTab === "active" ? "No active unidentified tracks" : "No ignored unidentified tracks"}
              />
            )}
          </div>
        ) : (
          <EmptyStateCard body="No failed Beets imports need review." className="text-left" title="No unidentified tracks" />
        )}
      </div>
    </section>
  );
}
