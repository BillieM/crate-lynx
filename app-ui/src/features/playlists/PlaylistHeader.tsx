import type { PlaylistDetail } from "./queries";

type PlaylistHeaderProps = {
  playlist: PlaylistDetail;
};

const ringRadius = 44;
const ringCircumference = 2 * Math.PI * ringRadius;

function getProgressPercentage(playlist: PlaylistDetail) {
  if (playlist.track_count <= 0) {
    return 0;
  }

  return Math.max(0, Math.min(100, (playlist.linked_count / playlist.track_count) * 100));
}

function getStrokeDashoffset(percentage: number) {
  return ringCircumference - (ringCircumference * percentage) / 100;
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
        className="h-28 w-28 rounded-[24px] object-cover shadow-[0_18px_42px_color-mix(in_srgb,var(--color-ctp-crust)_32%,transparent)] ring-1 ring-inset ring-ctp-surface1/80"
        src={playlist.cover_art_url}
      />
    );
  }

  return (
    <div className="flex h-28 w-28 items-center justify-center rounded-[24px] bg-ctp-surface0 text-ctp-blue shadow-[0_18px_42px_color-mix(in_srgb,var(--color-ctp-crust)_24%,transparent)] ring-1 ring-inset ring-ctp-surface1/80">
      <svg aria-hidden="true" className="h-10 w-10" fill="none" viewBox="0 0 24 24">
        <path
          d="M8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0Zm10-3a2 2 0 1 1-4 0 2 2 0 0 1 4 0Zm-4 0V6l6-1.5v9"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.7"
        />
      </svg>
    </div>
  );
}

function ProgressRing({ playlist }: { playlist: PlaylistDetail }) {
  const percentage = getProgressPercentage(playlist);
  const dashOffset = getStrokeDashoffset(percentage);

  return (
    <div className="flex items-center gap-4 rounded-[24px] bg-ctp-surface0/72 px-5 py-4 ring-1 ring-inset ring-ctp-surface1/80">
      <div className="relative h-28 w-28 shrink-0">
        <svg aria-hidden="true" className="h-28 w-28 -rotate-90" viewBox="0 0 120 120">
          <circle
            cx="60"
            cy="60"
            fill="none"
            r={ringRadius}
            stroke="color-mix(in srgb, var(--color-ctp-surface1) 95%, transparent)"
            strokeWidth="10"
          />
          <circle
            cx="60"
            cy="60"
            fill="none"
            r={ringRadius}
            stroke="var(--color-ctp-green)"
            strokeDasharray={ringCircumference}
            strokeDashoffset={dashOffset}
            strokeLinecap="round"
            strokeWidth="10"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[28px] font-semibold leading-none text-ctp-text">{playlist.linked_count}</span>
          <span className="mt-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ctp-subtext0">
            linked
          </span>
        </div>
      </div>
      <div className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ctp-subtext0">Coverage</p>
        <p className="text-[18px] font-semibold text-ctp-text">
          {playlist.linked_count} / {playlist.track_count}
        </p>
        <p className="max-w-[12rem] text-[12px] leading-5 text-ctp-subtext0">
          {playlist.unlinked_count === 0 && playlist.pending_count === 0
            ? "Every track in this playlist has a final local match."
            : "Linked tracks are ready for export while pending and unlinked rows still need attention."}
        </p>
      </div>
    </div>
  );
}

function StatCard({
  label,
  toneClassName,
  value,
}: {
  label: string;
  toneClassName: string;
  value: number;
}) {
  return (
    <div className="rounded-[18px] bg-ctp-surface0/72 px-4 py-3 ring-1 ring-inset ring-ctp-surface1/80">
      <div className="flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${toneClassName}`} />
        <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-ctp-subtext0">{label}</span>
      </div>
      <p className="mt-3 text-[24px] font-semibold leading-none text-ctp-text">{value}</p>
    </div>
  );
}

function PlaylistSyncError({ playlist }: { playlist: PlaylistDetail }) {
  if (!playlist.last_sync_error) {
    return null;
  }

  return (
    <div className="rounded-[18px] border border-ctp-red/35 bg-ctp-red/10 px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-ctp-red">
        Last sync error
      </p>
      <p className="mt-2 text-[13px] leading-5 text-ctp-text">{playlist.last_sync_error}</p>
      <p className="mt-1 text-[12px] text-ctp-subtext0">
        Failed {formatSyncErrorTime(playlist.last_sync_error_at)}
      </p>
    </div>
  );
}

export function PlaylistHeader({ playlist }: PlaylistHeaderProps) {
  return (
    <section className="rounded-[30px] border border-ctp-surface1/80 bg-[linear-gradient(135deg,color-mix(in_srgb,var(--color-ctp-base)_96%,transparent),color-mix(in_srgb,var(--color-ctp-surface0)_92%,transparent))] px-6 py-6 shadow-[0_24px_64px_color-mix(in_srgb,var(--color-ctp-crust)_24%,transparent)]">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex min-w-0 flex-col gap-5 sm:flex-row">
          <CoverArt playlist={playlist} />
          <div className="min-w-0 space-y-4">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-ctp-lavender">
                Playlist overview
              </p>
              <h2 className="mt-2 text-[30px] font-semibold tracking-[-0.03em] text-ctp-text">
                {playlist.name}
              </h2>
              <p className="mt-2 text-[13px] text-ctp-subtext0">{formatRelativeSyncTime(playlist.synced_at)}</p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <StatCard label="Linked" toneClassName="bg-ctp-green" value={playlist.linked_count} />
              <StatCard label="Pending" toneClassName="bg-ctp-yellow" value={playlist.pending_count} />
              <StatCard label="Unlinked" toneClassName="bg-ctp-red" value={playlist.unlinked_count} />
            </div>
            <PlaylistSyncError playlist={playlist} />
          </div>
        </div>

        <ProgressRing playlist={playlist} />
      </div>
    </section>
  );
}
