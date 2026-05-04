import { AlertTriangle, ListMusic } from "lucide-react";
import { Pill } from "../../components/Pill";
import { surfaceClasses, textClasses } from "../../styles/componentClasses";
import type { PlaylistDetail } from "./queries";

type PlaylistHeaderProps = {
  playlist: PlaylistDetail;
};

function getProgressPercentage(playlist: PlaylistDetail) {
  if (playlist.track_count <= 0) {
    return 0;
  }

  return Math.max(0, Math.min(100, (playlist.linked_count / playlist.track_count) * 100));
}

function formatRelativeSyncTime(timestamp: string | null) {
  if (timestamp === null) {
    return "Awaiting first sync";
  }

  const syncedAt = new Date(timestamp);

  if (Number.isNaN(syncedAt.getTime())) {
    return "Sync timestamp unavailable";
  }

  const formatter = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

  return `Synced ${formatter.format(syncedAt)}`;
}

function formatSyncErrorTime(timestamp: string | null) {
  if (timestamp === null) {
    return "time unavailable";
  }

  const failedAt = new Date(timestamp);

  if (Number.isNaN(failedAt.getTime())) {
    return "time unavailable";
  }

  const formatter = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

  return formatter.format(failedAt);
}

function CoverArt({ playlist }: { playlist: PlaylistDetail }) {
  if (playlist.cover_art_url) {
    return (
      <img
        alt={`${playlist.name} cover art`}
        className={`h-16 w-16 object-cover sm:h-[72px] sm:w-[72px] ${surfaceClasses.raisedArtwork}`}
        src={playlist.cover_art_url}
      />
    );
  }

  return (
    <div
      className={`flex h-16 w-16 items-center justify-center bg-ctp-surface0 text-ctp-blue sm:h-[72px] sm:w-[72px] ${surfaceClasses.raisedArtwork}`}
    >
      <ListMusic aria-hidden="true" className="h-7 w-7" strokeWidth={1.7} />
    </div>
  );
}

function CoverageMeter({ playlist }: { playlist: PlaylistDetail }) {
  const percentage = getProgressPercentage(playlist);

  return (
    <div className="min-w-[11rem] space-y-2 sm:min-w-[13rem]">
      <div className="flex items-center justify-between gap-3">
        <span className={`${textClasses.eyebrow} text-ctp-subtext0`}>Coverage</span>
        <span className="text-[12px] font-semibold tabular-nums text-ctp-text">
          {playlist.linked_count} / {playlist.track_count}
        </span>
      </div>
      <div
        aria-label={`Coverage ${Math.round(percentage)}%`}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={Math.round(percentage)}
        className="h-2 rounded-full bg-ctp-surface0 ring-1 ring-inset ring-ctp-surface1"
        role="progressbar"
      >
        <div className="h-full rounded-full bg-ctp-green" style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}

function CountPill({
  label,
  tone,
  value,
}: {
  label: string;
  tone: "danger" | "pending" | "success";
  value: number;
}) {
  return (
    <Pill className="inline-flex items-center gap-1.5 py-1" tone={tone}>
      <span className="tabular-nums">{value}</span>
      <span>{label}</span>
    </Pill>
  );
}

function PlaylistSyncError({ playlist }: { playlist: PlaylistDetail }) {
  if (!playlist.last_sync_error) {
    return null;
  }

  return (
    <div
      className={`${surfaceClasses.panelRadius} flex min-w-0 items-start gap-2 border border-ctp-red/35 bg-ctp-red/10 px-3 py-2`}
    >
      <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-ctp-red" />
      <div className="min-w-0">
        <p className={`${textClasses.eyebrow} text-ctp-red`}>Last sync error</p>
        <p className="mt-2 text-[13px] leading-5 text-ctp-text">{playlist.last_sync_error}</p>
        <p className={`mt-1 ${textClasses.caption}`}>Failed {formatSyncErrorTime(playlist.last_sync_error_at)}</p>
      </div>
    </div>
  );
}

export function PlaylistHeader({ playlist }: PlaylistHeaderProps) {
  return (
    <section className={`${surfaceClasses.elevatedPanel} py-4`}>
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex min-w-0 gap-3 sm:gap-4">
          <div className="shrink-0">
            <CoverArt playlist={playlist} />
          </div>
          <div className="min-w-0 space-y-2">
            <div className="min-w-0">
              <p className={`${textClasses.eyebrow} text-ctp-lavender`}>Playlist overview</p>
              <h2 className="mt-1 truncate text-[22px] font-semibold text-ctp-text sm:text-[24px]">{playlist.name}</h2>
              <p className={textClasses.bodyMuted}>{formatRelativeSyncTime(playlist.synced_at)}</p>
            </div>

            <div className="flex flex-wrap gap-2">
              <CountPill label="Linked" tone="success" value={playlist.linked_count} />
              <CountPill label="Pending" tone="pending" value={playlist.pending_count} />
              <CountPill label="Unlinked" tone="danger" value={playlist.unlinked_count} />
            </div>
          </div>
        </div>

        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between xl:items-center">
          <CoverageMeter playlist={playlist} />
          <PlaylistSyncError playlist={playlist} />
        </div>
      </div>
    </section>
  );
}
