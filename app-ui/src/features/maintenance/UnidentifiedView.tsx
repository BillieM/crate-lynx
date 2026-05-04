import { FileQuestion, Fingerprint, HardDrive, WandSparkles } from "lucide-react";
import { ActionButton } from "../../components/ActionButton";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { Pill } from "../../components/Pill";
import { controlClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";

type UnidentifiedTrack = {
  failedAt: string;
  filename: string;
  fingerprintHash: string;
  id: number;
  reason: string;
  sourcePath: string;
};

const unidentifiedTracks = [
  {
    failedAt: "2026-05-02 21:44",
    filename: "unknown-import-9a4f.mp3",
    fingerprintHash: "fp_7d91c2a8e4b0",
    id: 4001,
    reason: "Beets could not identify metadata",
    sourcePath: "ingestion/failed/unknown-import-9a4f.mp3",
  },
  {
    failedAt: "2026-05-02 22:03",
    filename: "side-b-live-rip.flac",
    fingerprintHash: "fp_2c0f88b4aa17",
    id: 4002,
    reason: "Multiple low-confidence candidates",
    sourcePath: "ingestion/failed/side-b-live-rip.flac",
  },
  {
    failedAt: "2026-05-03 09:18",
    filename: "cassette-transfer-03.wav",
    fingerprintHash: "fp_b62e14d973c5",
    id: 4003,
    reason: "No Beets match returned",
    sourcePath: "ingestion/failed/cassette-transfer-03.wav",
  },
] satisfies UnidentifiedTrack[];

function UnidentifiedTrackRow({ track }: { track: UnidentifiedTrack }) {
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
            <dd className="truncate text-ctp-text">{track.sourcePath}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Fingerprint</dt>
            <dd className="truncate font-mono text-[11px] font-semibold text-ctp-text">{track.fingerprintHash}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5 lg:justify-end">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Failed</dt>
            <dd className="font-medium tabular-nums text-ctp-text">{track.failedAt}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5 lg:col-span-3">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Reason</dt>
            <dd className="truncate text-ctp-text">{track.reason}</dd>
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
          disabled
        >
          <WandSparkles aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
          Rescue
        </ActionButton>
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

export function UnidentifiedView() {
  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-3" aria-label="Unidentified summary">
        <UnidentifiedSummaryCard icon={FileQuestion} label="Failed imports" value={unidentifiedTracks.length.toString()} />
        <UnidentifiedSummaryCard icon={Fingerprint} label="Fingerprinted" value={unidentifiedTracks.length.toString()} />
        <UnidentifiedSummaryCard icon={HardDrive} label="Source" value="Beets" />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" aria-label="Unidentified tracks" role="region">
        {unidentifiedTracks.length > 0 ? (
          <div className="grid gap-2.5">
            <div className="flex items-center justify-between gap-3 px-1">
              <h2 className={textClasses.label}>Beets failed track list</h2>
              <p className={`${textClasses.caption} tabular-nums`}>{unidentifiedTracks.length} rows</p>
            </div>
            {unidentifiedTracks.map((track) => (
              <UnidentifiedTrackRow key={track.id} track={track} />
            ))}
          </div>
        ) : (
          <EmptyStateCard body="No failed Beets imports need review." className="text-left" title="No unidentified tracks" />
        )}
      </div>
    </section>
  );
}
