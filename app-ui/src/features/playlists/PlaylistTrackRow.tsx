import type { ReactNode } from "react";

import { surfaceClasses, textClasses } from "../../styles/componentClasses";
import { TrackStatusDot } from "./TrackStatusDot";
import type { PlaylistTrack } from "./queries";

type PlaylistTrackRowProps = {
  actionSlot?: ReactNode;
  track: PlaylistTrack;
};

function formatDuration(durationMs: number | null) {
  if (durationMs === null || durationMs < 0) {
    return "Unknown";
  }

  const totalSeconds = Math.floor(durationMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function getAlbumLabel(album: string | null) {
  if (album === null || album.trim().length === 0) {
    return "Single / unknown release";
  }

  return album;
}

export function PlaylistTrackRow({ actionSlot, track }: PlaylistTrackRowProps) {
  return (
    <article className={`grid gap-4 px-5 py-4 lg:grid-cols-[minmax(0,1.8fr)_minmax(0,1.1fr)_minmax(0,1fr)_auto_auto] lg:items-center ${surfaceClasses.trackCard}`}>
      <div className="flex min-w-0 items-start gap-3">
        <div className="flex items-center gap-3 pt-1">
          <TrackStatusDot status={track.status} />
          <span className={`${textClasses.eyebrow} text-ctp-subtext0`}>
            {track.position}
          </span>
        </div>
        <div className="min-w-0">
          <p className={`truncate ${textClasses.title}`}>{track.title}</p>
          <p className={`mt-1 truncate ${textClasses.bodyMuted}`}>{track.artist}</p>
        </div>
      </div>

      <div className="min-w-0">
        <p className={`${textClasses.eyebrow} text-ctp-subtext0`}>Artist</p>
        <p className="mt-1 truncate text-[13px] text-ctp-text">{track.artist}</p>
      </div>

      <div className="min-w-0">
        <p className={`${textClasses.eyebrow} text-ctp-subtext0`}>Album</p>
        <p className="mt-1 truncate text-[13px] text-ctp-text">{getAlbumLabel(track.album)}</p>
      </div>

      <div>
        <p className={`${textClasses.eyebrow} text-ctp-subtext0`}>Duration</p>
        <p className="mt-1 text-[13px] font-medium tabular-nums text-ctp-text">{formatDuration(track.duration_ms)}</p>
      </div>

      <div className="flex items-center justify-start lg:justify-end">{actionSlot ?? null}</div>
    </article>
  );
}
