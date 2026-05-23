import { ExternalLink, PlaySquare } from "lucide-react";
import { useState } from "react";

import { controlClasses, textClasses } from "../../styles/componentClasses";

type StreamingTrackPreviewProps = {
  artist?: string;
  className?: string;
  providerTrackId: string;
  title: string;
};

function youtubeMusicUrl(providerTrackId: string) {
  return `https://music.youtube.com/watch?v=${encodeURIComponent(providerTrackId)}`;
}

function youtubeEmbedUrl(providerTrackId: string) {
  const params = new URLSearchParams({
    playsinline: "1",
    rel: "0",
  });
  if (typeof window !== "undefined") {
    params.set("origin", window.location.origin);
  }

  return `https://www.youtube.com/embed/${encodeURIComponent(providerTrackId)}?${params.toString()}`;
}

export function StreamingTrackPreview({
  artist,
  className = "",
  providerTrackId,
  title,
}: StreamingTrackPreviewProps) {
  const [showEmbed, setShowEmbed] = useState(false);
  const openUrl = youtubeMusicUrl(providerTrackId);

  return (
    <div className={`grid min-w-0 gap-2 rounded-[8px] border border-ctp-surface1 bg-ctp-crust px-3 py-2 ${className}`}>
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className={`${textClasses.finePrint} font-semibold text-ctp-text`}>{title}</p>
          {artist ? <p className={`${textClasses.finePrint} text-ctp-subtext0`}>{artist}</p> : null}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <a
            className={`${controlClasses.actionButton} ${controlClasses.actionButtonCompact} inline-flex items-center justify-center gap-1.5 border-ctp-surface1 bg-ctp-surface0 text-ctp-text hover:bg-ctp-surface1`}
            href={openUrl}
            rel="noreferrer"
            target="_blank"
          >
            <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            <span>Open</span>
          </a>
          <button
            aria-expanded={showEmbed}
            className={`${controlClasses.actionButton} ${controlClasses.actionButtonCompact} inline-flex items-center justify-center gap-1.5 border-ctp-surface1 bg-ctp-surface0 text-ctp-text hover:bg-ctp-surface1`}
            type="button"
            onClick={() => setShowEmbed((current) => !current)}
          >
            <PlaySquare aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
            <span>{showEmbed ? "Hide preview" : "Preview"}</span>
          </button>
        </div>
      </div>
      {showEmbed ? (
        <iframe
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
          allowFullScreen
          className="h-[200px] w-full max-w-[360px] rounded-[8px] border border-ctp-surface0 bg-black"
          referrerPolicy="strict-origin-when-cross-origin"
          src={youtubeEmbedUrl(providerTrackId)}
          title={`YouTube preview for ${title}`}
        />
      ) : null}
    </div>
  );
}
