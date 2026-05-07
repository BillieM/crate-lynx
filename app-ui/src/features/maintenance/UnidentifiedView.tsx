import { createColumnHelper, type RowSelectionState, type SortingState } from "@tanstack/react-table";
import { FileQuestion, HardDrive, WandSparkles, XCircle } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ActionButton } from "../../components/ActionButton";
import { DataTable } from "../../components/DataTable";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { StatusMessage } from "../../components/StatusMessage";
import { surfaceClasses, textClasses } from "../../styles/componentClasses";
import {
  maintenanceQueryKeys,
  rescueLocalTrackMetadata,
  type UnidentifiedResponse,
  type UnidentifiedTrack,
  useUnidentifiedTracksQuery,
} from "./queries";

type MaintenanceViewState = "ready" | "loading" | "error";

const emptyUnidentifiedTracks: UnidentifiedTrack[] = [];
const columnHelper = createColumnHelper<UnidentifiedTrack>();

type BulkRescueStatus = {
  body: string;
  status: "error" | "success";
  title: string;
};

function formatFailedAt(failedAt: string) {
  return failedAt.replace("T", " ").replace("Z", "").slice(0, 16);
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

function RescueAction({ rescueDisabled = false, track }: { rescueDisabled?: boolean; track: UnidentifiedTrack }) {
  const rescueMutation = useMutation({
    mutationFn: rescueLocalTrackMetadata,
  });
  const canRescue = track.local_track_id !== null;
  const rescueStatus = rescueMutation.isPending
    ? "Rescuing metadata..."
    : rescueMutation.isError
      ? "Rescue failed"
      : rescueMutation.isSuccess
        ? "Rescue complete"
        : !canRescue
          ? "No persisted local track available for rescue"
        : null;

  return (
      <div className="flex flex-wrap items-center justify-end gap-1.5">
        <ActionButton
          aria-label={`Rescue ${track.filename}`}
          className="inline-flex items-center gap-1.5"
          disabled={!canRescue || rescueDisabled || rescueMutation.isPending}
          onClick={() => {
            if (track.local_track_id !== null) {
              rescueMutation.mutate(track.local_track_id);
            }
          }}
        >
          <WandSparkles aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
          {!canRescue ? "Unavailable" : rescueMutation.isPending ? "Rescuing..." : "Rescue"}
        </ActionButton>
        {rescueStatus ? (
          <span
            aria-live="polite"
            className={`${textClasses.caption} ${rescueMutation.isError ? "text-ctp-red" : "text-ctp-subtext0"}`}
            role="status"
          >
            {rescueStatus}
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
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const [bulkRescueStatus, setBulkRescueStatus] = useState<BulkRescueStatus | null>(null);
  const [isBulkRescuing, setIsBulkRescuing] = useState(false);
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
  const actionsDisabled = resolvedState !== "ready" || isPending;
  const selectedTracks = useMemo(() => tracks.filter((track) => rowSelection[String(track.id)]), [rowSelection, tracks]);
  const selectedRescuableTracks = useMemo(
    () => selectedTracks.filter((track) => track.local_track_id !== null),
    [selectedTracks],
  );
  const columns = useMemo(
    () => [
      columnHelper.display({
        cell: () => (
          <span
            aria-label="Beets failed track"
            className="inline-flex h-2.5 w-2.5 rounded-full bg-ctp-red shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-red)_16%,transparent)]"
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
        cell: (info) => <span className="block max-w-[18rem] truncate font-semibold">{info.getValue()}</span>,
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
      columnHelper.accessor("failed_at", {
        cell: (info) => <span className="tabular-nums">{formatFailedAt(info.getValue())}</span>,
        header: "Failed",
        meta: {
          hideBelow: "md",
          widthClass: "w-36",
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
        cell: (info) => <span className="font-mono text-[11px]">{info.getValue() ?? "Unavailable"}</span>,
        header: "Local track ID",
        meta: {
          align: "end",
          hideBelow: "md",
          widthClass: "w-32",
        },
      }),
      columnHelper.display({
        cell: (info) => <RescueAction rescueDisabled={actionsDisabled || isBulkRescuing} track={info.row.original} />,
        enableSorting: false,
        header: "Actions",
        meta: {
          align: "end",
          widthClass: "w-44",
        },
      }),
    ],
    [actionsDisabled, isBulkRescuing],
  );

  async function handleBulkRescue() {
    if (selectedTracks.length === 0 || isBulkRescuing) {
      return;
    }

    setIsBulkRescuing(true);
    setBulkRescueStatus(null);

    const results = await settleInChunks(selectedRescuableTracks, 5, (track) =>
      rescueLocalTrackMetadata(track.local_track_id as number),
    );
    const skippedCount = selectedTracks.length - selectedRescuableTracks.length;
    const successCount = results.filter((result) => result.status === "fulfilled").length;
    const failureCount = results.filter((result) => result.status === "rejected").length;

    await queryClient.invalidateQueries({ queryKey: maintenanceQueryKeys.unidentified() });

    setRowSelection({});
    setIsBulkRescuing(false);
    setBulkRescueStatus({
      body:
        failureCount > 0 || skippedCount > 0
          ? `${successCount} ${successCount === 1 ? "track was" : "tracks were"} rescued, ${failureCount} ${failureCount === 1 ? "failed" : "failed"}, and ${skippedCount} ${skippedCount === 1 ? "row was" : "rows were"} skipped.`
          : `${successCount} ${successCount === 1 ? "track was" : "tracks were"} rescued.`,
      status: failureCount > 0 ? "error" : "success",
      title: failureCount > 0 ? "Bulk rescue partially failed" : "Bulk rescue complete",
    });
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
        <UnidentifiedSummaryCard icon={FileQuestion} label="Failed imports" value={tracks.length.toString()} />
        <UnidentifiedSummaryCard icon={XCircle} label="Needs review" value={tracks.length.toString()} />
        <UnidentifiedSummaryCard icon={HardDrive} label="Source" value="Ingest" />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" aria-label="Unidentified tracks" role="region">
        {bulkRescueStatus ? (
          <StatusMessage body={bulkRescueStatus.body} status={bulkRescueStatus.status} title={bulkRescueStatus.title} />
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
            <div className="flex items-center justify-between gap-3 px-1">
              <h2 className={textClasses.label}>Beets failed track list</h2>
              <p className={`${textClasses.caption} tabular-nums`}>{tracks.length} rows</p>
            </div>
            <DataTable
              bulkActionSlot={
                <ActionButton
                  className="inline-flex items-center gap-1.5"
                  disabled={selectedRescuableTracks.length === 0 || actionsDisabled || isBulkRescuing}
                  onClick={handleBulkRescue}
                >
                  <WandSparkles aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
                  {isBulkRescuing ? "Rescuing..." : "Rescue"}
                </ActionButton>
              }
              columns={columns}
              data={tracks}
              rowCanSelect={(track) => track.local_track_id !== null}
              rowId={(track) => String(track.id)}
              rowSelection={rowSelection}
              sorting={sorting}
              stickyHeader
              onRowSelectionChange={setRowSelection}
              onSortingChange={setSorting}
            />
          </div>
        ) : (
          <EmptyStateCard body="No failed Beets imports need review." className="text-left" title="No unidentified tracks" />
        )}
      </div>
    </section>
  );
}
