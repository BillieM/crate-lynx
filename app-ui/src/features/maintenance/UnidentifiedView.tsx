import { FileQuestion, Fingerprint, HardDrive, WandSparkles } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { Pill } from "../../components/Pill";
import { StatusMessage } from "../../components/StatusMessage";
import { controlClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import {
  rescueLocalTrackMetadata,
  type UnidentifiedResponse,
  type UnidentifiedTrack,
  useUnidentifiedTracksQuery,
} from "./queries";

type MaintenanceViewState = "ready" | "loading" | "error";

const emptyUnidentifiedTracks: UnidentifiedTrack[] = [];

function formatFailedAt(failedAt: string) {
  return failedAt.replace("T", " ").replace("Z", "").slice(0, 16);
}

function UnidentifiedTrackRow({ rescueDisabled = false, track }: { rescueDisabled?: boolean; track: UnidentifiedTrack }) {
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
    <article className={`${surfaceClasses.rowCardCompact} sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center`}>
      <div className="grid min-w-0 gap-1.5">
        <div className="flex min-w-0 items-center gap-3">
          <span
            aria-label="Beets failed track"
            className="inline-flex h-2.5 w-2.5 shrink-0 rounded-full bg-ctp-red shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-red)_16%,transparent)]"
            role="status"
          />
          <FileQuestion aria-hidden="true" className="h-4 w-4 shrink-0 text-ctp-red" strokeWidth={1.8} />
          <p className={`min-w-0 flex-1 truncate ${textClasses.title}`}>{track.filename}</p>
          <Pill className="hidden shrink-0 sm:inline-flex" tone="danger">
            Beets failed
          </Pill>
        </div>

        <dl className={`grid min-w-0 gap-x-3 gap-y-1 pl-9 text-ctp-subtext0 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_auto] ${textClasses.bodyRelaxed}`}>
          <div className="flex min-w-0 items-baseline gap-1.5">
            <dt className="shrink-0 font-medium text-ctp-overlay1">File</dt>
            <dd className="truncate text-ctp-text">{track.source_path}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Fingerprint</dt>
            <dd className="truncate font-mono text-[11px] font-semibold text-ctp-text">{track.fingerprint ?? "Not captured"}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5 lg:justify-end">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Failed</dt>
            <dd className="font-medium tabular-nums text-ctp-text">{formatFailedAt(track.failed_at)}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5 lg:col-span-3">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Reason</dt>
            <dd className="truncate text-ctp-text">{track.failure_reason}</dd>
          </div>
        </dl>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 pl-9 sm:justify-end sm:pl-0">
        <Pill className="sm:hidden" tone="danger">
          Beets failed
        </Pill>
        <ActionButton
          aria-label={`Rescue ${track.filename}`}
          className={`${controlClasses.actionButtonCompact} inline-flex items-center gap-1.5`}
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
    </article>
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
  const unidentifiedQuery = useUnidentifiedTracksQuery({ enabled: tracksResponse === undefined });
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
  const fingerprintedCount = tracks.filter((track) => track.fingerprint !== null).length;
  const actionsDisabled = resolvedState !== "ready" || isPending;

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
        <UnidentifiedSummaryCard icon={Fingerprint} label="Fingerprinted" value={fingerprintedCount.toString()} />
        <UnidentifiedSummaryCard icon={HardDrive} label="Source" value="Ingest" />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" aria-label="Unidentified tracks" role="region">
        {resolvedState === "loading" ? (
          <EmptyStateCard
            body="Checking Beets-failed imports and fingerprint hashes."
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
            {tracks.map((track) => (
              <UnidentifiedTrackRow key={track.id} rescueDisabled={actionsDisabled} track={track} />
            ))}
          </div>
        ) : (
          <EmptyStateCard body="No failed Beets imports need review." className="text-left" title="No unidentified tracks" />
        )}
      </div>
    </section>
  );
}
