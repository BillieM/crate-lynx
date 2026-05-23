import { Pause, Play, RotateCcw } from "lucide-react";
import { useRef, useState } from "react";

import { controlClasses, textClasses } from "../../styles/componentClasses";

type AudioPreviewPlayerProps = {
  label: string;
  src: string;
};

function formatPlaybackTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "0:00";
  }

  const wholeSeconds = Math.floor(seconds);
  const minutes = Math.floor(wholeSeconds / 60);
  const remainingSeconds = String(wholeSeconds % 60).padStart(2, "0");
  return `${minutes}:${remainingSeconds}`;
}

export function AudioPreviewPlayer({ label, src }: AudioPreviewPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [hasError, setHasError] = useState(false);
  const progressMax = duration > 0 ? duration : 0;

  async function togglePlayback() {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }

    setHasError(false);
    if (!audio.paused) {
      audio.pause();
      return;
    }

    try {
      await audio.play();
    } catch {
      setHasError(true);
      setIsPlaying(false);
    }
  }

  function restart() {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }

    audio.currentTime = 0;
    setCurrentTime(0);
  }

  function updateProgress(value: string) {
    const nextTime = Number(value);
    if (!Number.isFinite(nextTime)) {
      return;
    }

    const audio = audioRef.current;
    if (audio) {
      audio.currentTime = nextTime;
    }
    setCurrentTime(nextTime);
  }

  return (
    <div className="grid min-w-0 gap-2 rounded-[8px] border border-ctp-surface1 bg-ctp-crust px-3 py-2 text-ctp-text shadow-sm shadow-ctp-crust/30">
      <audio
        aria-label={label}
        className="sr-only"
        onDurationChange={(event) => setDuration(event.currentTarget.duration || 0)}
        onEnded={() => setIsPlaying(false)}
        onError={() => setHasError(true)}
        onPause={() => setIsPlaying(false)}
        onPlay={() => setIsPlaying(true)}
        onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
        preload="none"
        ref={audioRef}
        src={src}
      />
      <div className="grid min-w-0 grid-cols-[auto_auto_minmax(0,1fr)_auto] items-center gap-2">
        <button
          aria-label={`${isPlaying ? "Pause" : "Play"} ${label}`}
          className={`${controlClasses.actionButton} ${controlClasses.actionButtonCompact} inline-flex h-8 w-8 items-center justify-center border-ctp-surface1 bg-ctp-surface0 px-0 text-ctp-text hover:bg-ctp-surface1`}
          type="button"
          onClick={togglePlayback}
        >
          {isPlaying ? (
            <Pause aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2} />
          ) : (
            <Play aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2} />
          )}
        </button>
        <button
          aria-label={`Restart ${label}`}
          className={`${controlClasses.actionButton} ${controlClasses.actionButtonCompact} inline-flex h-8 w-8 items-center justify-center border-ctp-surface1 bg-ctp-surface0 px-0 text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-text`}
          type="button"
          onClick={restart}
        >
          <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.9} />
        </button>
        <input
          aria-label={`${label} progress`}
          className="h-1.5 min-w-0 accent-ctp-mauve"
          disabled={progressMax === 0}
          max={progressMax}
          min={0}
          step="0.1"
          type="range"
          value={Math.min(currentTime, progressMax)}
          onChange={(event) => updateProgress(event.currentTarget.value)}
        />
        <span className={`${textClasses.finePrint} tabular-nums text-ctp-subtext0`}>
          {formatPlaybackTime(currentTime)} / {formatPlaybackTime(duration)}
        </span>
      </div>
      {hasError ? (
        <p className={`${textClasses.finePrint} font-medium text-ctp-red`}>
          Audio could not be loaded.
        </p>
      ) : null}
    </div>
  );
}
