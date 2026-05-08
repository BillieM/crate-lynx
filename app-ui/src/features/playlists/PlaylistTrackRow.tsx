import type { ReactNode } from "react";

import { formatDuration } from "../../lib/formatters";
import { surfaceClasses, textClasses } from "../../styles/componentClasses";
import { TrackStatusDot } from "./TrackStatusDot";
import type { PlaylistTrack } from "./queries";

type PlaylistTrackRowProps = {
  actionSlot?: ReactNode;
  track: PlaylistTrack;
};

function getAlbumLabel(album: string | null) {
  if (album === null || album.trim().length === 0) {
    return "Single / unknown release";
  }

  return album;
}

export function PlaylistTrackRow({ actionSlot, track }: PlaylistTrackRowProps) {
  return (
    <article className={`${surfaceClasses.rowCardCompact} sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center`}>
      <div className="grid min-w-0 gap-1.5">
        <div className="flex min-w-0 items-center gap-3">
          <TrackStatusDot status={track.status} />
          <span className={`${textClasses.eyebrow} w-7 shrink-0 text-right tabular-nums text-ctp-subtext0`}>
            {track.position}
          </span>
          <p className={`min-w-0 flex-1 truncate ${textClasses.title}`}>{track.title}</p>
        </div>

        <dl className={`grid min-w-0 gap-x-3 gap-y-1 pl-12 text-ctp-subtext0 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] ${textClasses.bodyRelaxed}`}>
          <div className="flex min-w-0 items-baseline gap-1.5">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Artist</dt>
            <dd className="truncate text-ctp-text">{track.artist}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Album</dt>
            <dd className="truncate text-ctp-text">{getAlbumLabel(track.album)}</dd>
          </div>
          <div className="flex min-w-0 items-baseline gap-1.5 sm:justify-end">
            <dt className="shrink-0 font-medium text-ctp-overlay1">Duration</dt>
            <dd className="font-medium tabular-nums text-ctp-text">{formatDuration(track.duration_ms)}</dd>
          </div>
        </dl>
      </div>

      <div className="flex items-center justify-start pl-12 sm:justify-end sm:pl-0">{actionSlot ?? null}</div>
    </article>
  );
}
