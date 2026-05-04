import { ListMusic, Music2, RadioTower, SearchX } from "lucide-react";
import { EmptyStateCard } from "../../components/EmptyStateCard";
import { StatusMessage } from "../../components/StatusMessage";
import { surfaceClasses, textClasses } from "../../styles/componentClasses";

type MaintenanceViewState = "ready" | "loading" | "error";

type MissingStreamingTrack = {
  album: string | null;
  artist: string;
  durationMs: number | null;
  id: number;
  lastCheckedAt: string;
  playlistTitle: string;
  serviceTrackId: string;
  title: string;
};

const missingStreamingTracks = [
  {
    album: "Immunity",
    artist: "Jon Hopkins",
    durationMs: 270000,
    id: 5001,
    lastCheckedAt: "2026-05-03 19:42",
    playlistTitle: "Late Night Drive",
    serviceTrackId: "ytm:VLPL_missing_018",
    title: "Open Eye Signal",
  },
  {
    album: "Migration",
    artist: "Bonobo feat. Nick Murphy",
    durationMs: 360000,
    id: 5002,
    lastCheckedAt: "2026-05-03 19:40",
    playlistTitle: "Focus Queue",
    serviceTrackId: "ytm:VLPL_missing_024",
    title: "No Reason",
  },
  {
    album: null,
    artist: "Kelly Lee Owens",
    durationMs: 221000,
    id: 5003,
    lastCheckedAt: "2026-05-03 19:37",
    playlistTitle: "New Imports",
    serviceTrackId: "ytm:VLPL_missing_031",
    title: "Melt!",
  },
] satisfies MissingStreamingTrack[];

function formatDuration(durationMs: number | null) {
  if (durationMs === null || durationMs < 0) {
    return "Unknown";
  }

  const totalSeconds = Math.floor(durationMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function MissingSummaryCard({
  icon: Icon,
  label,
  toneClass,
  value,
}: {
  icon: typeof Music2;
  label: string;
  toneClass: string;
  value: string;
}) {
  return (
    <section className={`${surfaceClasses.compactCard} min-h-24`} aria-label={label}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={`${textClasses.microEyebrow} text-ctp-subtext0`}>{label}</p>
          <p className="mt-2 text-[24px] font-semibold leading-none tabular-nums text-ctp-text">{value}</p>
        </div>
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] ring-1 ring-inset ${toneClass}`}>
          <Icon aria-hidden="true" className="h-[18px] w-[18px]" strokeWidth={1.8} />
        </div>
      </div>
    </section>
  );
}

function MissingTrackRow({ track }: { track: MissingStreamingTrack }) {
  return (
    <article className={surfaceClasses.rowCardCompact}>
      <div className="grid min-w-0 gap-1.5">
        <div className="flex min-w-0 items-center gap-3">
          <span
            aria-label="Streaming track missing local match"
            className="inline-flex h-2.5 w-2.5 shrink-0 rounded-full bg-ctp-yellow shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-yellow)_16%,transparent)]"
            role="status"
          />
          <SearchX aria-hidden="true" className="h-4 w-4 shrink-0 text-ctp-yellow" strokeWidth={1.8} />
          <p className={`min-w-0 flex-1 truncate ${textClasses.title}`}>{track.title}</p>
          <span className={`${textClasses.metric} hidden shrink-0 sm:inline`}>{formatDuration(track.durationMs)}</span>
        </div>

        <dl
          className={`grid min-w-0 gap-x-3 gap-y-1 pl-9 text-ctp-subtext0 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] ${textClasses.bodyRelaxed}`}
        >
          <div className="flex min-w-0 items-baseline gap-1.5">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Artist</dt>
            <dd className="truncate text-ctp-text">{track.artist}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Album</dt>
            <dd className="truncate text-ctp-text">{track.album ?? "Album unavailable"}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5 lg:justify-end">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Playlist</dt>
            <dd className="truncate font-medium text-ctp-text lg:max-w-[14rem]">{track.playlistTitle}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Streaming ID</dt>
            <dd className="truncate font-mono text-[11px] font-semibold text-ctp-text">{track.serviceTrackId}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Checked</dt>
            <dd className="font-medium tabular-nums text-ctp-text">{track.lastCheckedAt}</dd>
          </div>
          <div className="flex items-baseline gap-1.5 sm:hidden">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Duration</dt>
            <dd className="font-medium tabular-nums text-ctp-text">{formatDuration(track.durationMs)}</dd>
          </div>
        </dl>
      </div>
    </article>
  );
}

type MissingLocallyViewProps = {
  isPending?: boolean;
  state?: MaintenanceViewState;
  tracks?: readonly MissingStreamingTrack[];
};

export function MissingLocallyView({ isPending = false, state = "ready", tracks = missingStreamingTracks }: MissingLocallyViewProps = {}) {
  const playlistCount = new Set(tracks.map((track) => track.playlistTitle)).size;

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      {isPending ? (
        <StatusMessage
          body="Missing-local-match results may update when playlist matching finishes."
          status="pending"
          title="Missing locally scan in progress"
        />
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2" aria-label="Missing locally summary">
        <MissingSummaryCard
          icon={SearchX}
          label="Missing tracks"
          toneClass="bg-ctp-yellow/18 text-ctp-yellow ring-ctp-yellow/30"
          value={tracks.length.toString()}
        />
        <MissingSummaryCard
          icon={ListMusic}
          label="Affected playlists"
          toneClass="bg-ctp-blue/18 text-ctp-blue ring-ctp-blue/30"
          value={playlistCount.toString()}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" aria-label="Missing local tracks" role="region">
        {state === "loading" ? (
          <EmptyStateCard
            body="Checking synced streaming tracks against the local library."
            className="text-left"
            role="status"
            title="Loading missing tracks"
          />
        ) : state === "error" ? (
          <EmptyStateCard
            body="The missing locally report could not be loaded."
            className="text-left"
            role="alert"
            title="Missing locally unavailable"
            tone="error"
          />
        ) : tracks.length > 0 ? (
          <div className="grid gap-2.5">
            <div className="flex items-center justify-between gap-3 px-1">
              <div className="flex items-center gap-2 text-ctp-subtext0">
                <RadioTower aria-hidden="true" className="h-4 w-4" strokeWidth={1.8} />
                <h2 className={textClasses.label}>Streaming tracks without local matches</h2>
              </div>
              <p className={`${textClasses.caption} tabular-nums`}>{tracks.length} rows</p>
            </div>
            {tracks.map((track) => (
              <MissingTrackRow key={track.id} track={track} />
            ))}
          </div>
        ) : (
          <EmptyStateCard body="Every synced streaming track has a local match." className="text-left" title="No missing tracks" />
        )}
      </div>
    </section>
  );
}
