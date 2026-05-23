import { Volume2 } from "lucide-react";

import { endpoints } from "../../lib/api";
import { textClasses } from "../../styles/componentClasses";

type LocalTrackAudioPreviewProps = {
  className?: string;
  label?: string;
  localTrackId: number | string;
};

function localTrackAudioUrl(localTrackId: number | string) {
  return endpoints.api(`/local-tracks/${encodeURIComponent(String(localTrackId))}/audio`);
}

export function LocalTrackAudioPreview({
  className = "",
  label,
  localTrackId,
}: LocalTrackAudioPreviewProps) {
  const audioLabel = label ?? `Listen to local track ${localTrackId}`;

  return (
    <div className={`grid min-w-0 gap-1.5 ${className}`}>
      <div className="flex items-center gap-1.5 text-ctp-subtext0">
        <Volume2 aria-hidden="true" className="h-3.5 w-3.5" />
        <span className={textClasses.finePrint}>Local audio</span>
      </div>
      <audio
        aria-label={audioLabel}
        className="h-8 w-full min-w-0"
        controls
        preload="none"
        src={localTrackAudioUrl(localTrackId)}
      />
    </div>
  );
}
