import { createColumnHelper, type SortingState } from "@tanstack/react-table";
import {
  EyeOff,
  FileQuestion,
  FolderOpen,
  History,
  RefreshCcw,
  RotateCcw,
  Undo2,
  WandSparkles,
  XCircle,
} from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { FilterChipGroup, type FilterChipOption } from "../../components/FilterChipGroup";
import { MetricCard } from "../../components/MetricCard";
import { StatusMessage } from "../../components/StatusMessage";
import { textClasses } from "../../styles/componentClasses";
import { LocalTrackDetailDrawer } from "../localTracks/LocalTrackDetailDrawer";
import {
  getMaintenanceRequestStatus,
  ignoreUnidentifiedTrack,
  invalidateUnidentifiedQueries,
  rematchLocalTrack,
  rescueLocalTrackMetadata,
  restoreUnidentifiedTrack,
  retryUnidentifiedTrack,
  type UnidentifiedResponse,
  type UnidentifiedTrack,
  useUnidentifiedTracksQuery,
} from "./queries";

type MaintenanceViewState = "ready" | "loading" | "error";
type UnidentifiedTab = "active" | "ignored";

const emptyUnidentifiedTracks: UnidentifiedTrack[] = [];
const columnHelper = createColumnHelper<UnidentifiedTrack>();

type RowActionStatus = {
  message: string;
  tone: "error" | "neutral";
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
  onOpenLocalTrack,
  track,
}: {
  actionsDisabled?: boolean;
  onOpenLocalTrack: (localTrackId: number) => void;
  track: UnidentifiedTrack;
}) {
  const queryClient = useQueryClient();
  const [statusMessage, setStatusMessage] = useState<RowActionStatus | null>(null);
  const retryMutation = useMutation({
    mutationFn: retryUnidentifiedTrack,
    onError: (error) => {
      if (getMaintenanceRequestStatus(error) === 404) {
        setStatusMessage({ message: "Source file missing; row refreshed", tone: "neutral" });
        void invalidateUnidentifiedQueries(queryClient);
        return;
      }

      setStatusMessage({ message: "Retry failed", tone: "error" });
    },
    onSuccess: async (response) => {
      setStatusMessage({ message: response.job_id ? "Retry queued" : "Retry already queued", tone: "neutral" });
      await invalidateUnidentifiedQueries(queryClient);
    },
  });
  const ignoreMutation = useMutation({
    mutationFn: ignoreUnidentifiedTrack,
    onError: () => setStatusMessage({ message: "Ignore failed", tone: "error" }),
    onSuccess: async () => {
      setStatusMessage({ message: "Source ignored", tone: "neutral" });
      await invalidateUnidentifiedQueries(queryClient);
    },
  });
  const restoreMutation = useMutation({
    mutationFn: restoreUnidentifiedTrack,
    onError: () => setStatusMessage({ message: "Restore failed", tone: "error" }),
    onSuccess: async () => {
      setStatusMessage({ message: "Source restored", tone: "neutral" });
      await invalidateUnidentifiedQueries(queryClient);
    },
  });
  const rematchMutation = useMutation({
    mutationFn: rematchLocalTrack,
    onError: () => setStatusMessage({ message: "Re-match failed", tone: "error" }),
    onSuccess: async () => {
      setStatusMessage({ message: "Re-match queued", tone: "neutral" });
      await invalidateUnidentifiedQueries(queryClient);
    },
  });
  const rescueMutation = useMutation({
    mutationFn: rescueLocalTrackMetadata,
    onError: () => setStatusMessage({ message: "Rescue failed", tone: "error" }),
    onSuccess: async () => {
      setStatusMessage({ message: "Rescue complete", tone: "neutral" });
      await invalidateUnidentifiedQueries(queryClient);
    },
  });
  const actionPending =
    retryMutation.isPending ||
    ignoreMutation.isPending ||
    restoreMutation.isPending ||
    rematchMutation.isPending ||
    rescueMutation.isPending;
  const disabled = actionsDisabled || actionPending;
  const pendingStatus = retryMutation.isPending
    ? "Queueing retry..."
    : ignoreMutation.isPending
      ? "Ignoring..."
      : restoreMutation.isPending
        ? "Restoring..."
        : rematchMutation.isPending
          ? "Queueing re-match..."
          : rescueMutation.isPending
            ? "Rescuing metadata..."
            : null;
  const hasLocalTrack = track.local_track_id !== null;
  const visibleStatus = pendingStatus ?? statusMessage?.message;
  const hasError = statusMessage?.tone === "error" && pendingStatus === null;

  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5">
      {track.ignored_at === null ? (
        <>
          <ActionButton
            aria-label={`Retry source ${track.filename}`}
            className="inline-flex items-center gap-1.5"
            disabled={disabled}
            onClick={() => {
              setStatusMessage(null);
              retryMutation.mutate(track.id);
            }}
          >
            <RefreshCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            {retryMutation.isPending ? "Retrying..." : "Retry source"}
          </ActionButton>
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
        </>
      ) : null}
      {track.ignored_at !== null ? (
        <ActionButton
          aria-label={`Restore ${track.filename}`}
          className="inline-flex items-center gap-1.5"
          disabled={disabled}
          onClick={() => {
            setStatusMessage(null);
            restoreMutation.mutate(track.id);
          }}
        >
          <Undo2 aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
          {restoreMutation.isPending ? "Restoring..." : "Restore"}
        </ActionButton>
      ) : null}
      {hasLocalTrack ? (
        <ActionButton
          aria-label={`Open local track ${track.local_track_id} for ${track.filename}`}
          className="inline-flex items-center gap-1.5"
          disabled={disabled}
          onClick={() => {
            if (track.local_track_id !== null) {
              onOpenLocalTrack(track.local_track_id);
            }
          }}
        >
          <FolderOpen aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
          Open local track
        </ActionButton>
      ) : null}
      {track.can_rematch_local_track && hasLocalTrack ? (
        <ActionButton
          aria-label={`Re-match ${track.filename}`}
          className="inline-flex items-center gap-1.5"
          disabled={disabled}
          onClick={() => {
            if (track.local_track_id !== null) {
              setStatusMessage(null);
              rematchMutation.mutate(track.local_track_id);
            }
          }}
        >
          <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
          {rematchMutation.isPending ? "Matching..." : "Re-match"}
        </ActionButton>
      ) : null}
      {track.can_rescue_metadata && hasLocalTrack ? (
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
      {visibleStatus ? (
        <span
          aria-live="polite"
          className={`${textClasses.caption} ${hasError ? "text-ctp-red" : "text-ctp-subtext0"}`}
          role="status"
        >
          {visibleStatus}
        </span>
      ) : null}
    </div>
  );
}

type UnidentifiedViewProps = {
  isPending?: boolean;
  state?: MaintenanceViewState;
  tracksResponse?: UnidentifiedResponse;
};

export function UnidentifiedView({ isPending = false, state, tracksResponse }: UnidentifiedViewProps = {}) {
  const unidentifiedQuery = useUnidentifiedTracksQuery({ enabled: tracksResponse === undefined });
  const [activeTab, setActiveTab] = useState<UnidentifiedTab>("active");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [openLocalTrackId, setOpenLocalTrackId] = useState<number | null>(null);
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
            onOpenLocalTrack={setOpenLocalTrackId}
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
    [actionsDisabled],
  );

  function handleTabChange(nextTab: UnidentifiedTab) {
    setActiveTab(nextTab);
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
        <MetricCard
          icon={FileQuestion}
          label="Failed sources"
          toneClass="bg-ctp-red/18 text-ctp-red ring-ctp-red/30"
          value={tracks.length}
        />
        <MetricCard
          icon={History}
          label="Total attempts"
          toneClass="bg-ctp-red/18 text-ctp-red ring-ctp-red/30"
          value={totalAttemptCount}
        />
        <MetricCard
          icon={XCircle}
          label="Active"
          toneClass="bg-ctp-red/18 text-ctp-red ring-ctp-red/30"
          value={activeTracks.length}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" aria-label="Unidentified tracks" role="region">
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
                columns={columns}
                data={visibleTracks}
                enableRowSelection={false}
                rowId={(track) => String(track.id)}
                sorting={sorting}
                stickyHeader
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
      <LocalTrackDetailDrawer
        localTrackId={openLocalTrackId}
        open={openLocalTrackId !== null}
        onClose={() => setOpenLocalTrackId(null)}
      />
    </section>
  );
}
