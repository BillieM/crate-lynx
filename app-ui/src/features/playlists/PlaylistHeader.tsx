import { AlertTriangle } from "lucide-react";
import { Pill } from "../../components/Pill";
import { surfaceClasses, textClasses } from "../../styles/componentClasses";
import type { PlaylistDetail } from "./queries";

type PlaylistHeaderProps = {
  playlist: PlaylistDetail;
};

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
        <p className={`mt-2 leading-5 text-ctp-text ${textClasses.input}`}>{playlist.last_sync_error}</p>
        <p className={`mt-1 ${textClasses.caption}`}>Failed {formatSyncErrorTime(playlist.last_sync_error_at)}</p>
      </div>
    </div>
  );
}

export function PlaylistHeader({ playlist }: PlaylistHeaderProps) {
  return (
    <section
      aria-label="Playlist toolbar"
      className={`${surfaceClasses.compactCard} flex flex-wrap items-center justify-between gap-3`}
    >
      <div className="min-w-0">
        <h2 className={`truncate ${textClasses.playlistTitle}`}>{playlist.name}</h2>
        <p className={textClasses.bodyMuted}>{formatRelativeSyncTime(playlist.synced_at)}</p>
      </div>

      <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
        <div className="flex flex-wrap gap-2">
          <CountPill label="Linked" tone="success" value={playlist.linked_count} />
          <CountPill label="Pending" tone="pending" value={playlist.pending_count} />
          <CountPill label="Unlinked" tone="danger" value={playlist.unlinked_count} />
        </div>

        <PlaylistSyncError playlist={playlist} />
      </div>
    </section>
  );
}
