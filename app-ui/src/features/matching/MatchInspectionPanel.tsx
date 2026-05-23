import { LocalTrackAudioPreview } from "../localTracks/LocalTrackAudioPreview";
import { StreamingTrackPreview } from "./StreamingTrackPreview";
import { textClasses } from "../../styles/componentClasses";

export type MatchInspectionLocalAudio = {
  label: string;
  localTrackId: number | string;
};

export type MatchInspectionStreamingTrack = {
  artist?: string;
  providerTrackId: string;
  title: string;
};

type MatchInspectionPanelProps = {
  localAudio?: MatchInspectionLocalAudio | null;
  localAudios?: MatchInspectionLocalAudio[];
  streamingTracks: MatchInspectionStreamingTrack[];
};

export function MatchInspectionPanel({ localAudio, localAudios, streamingTracks }: MatchInspectionPanelProps) {
  const resolvedLocalAudios = localAudios ?? (localAudio ? [localAudio] : []);

  return (
    <div className="grid gap-3 rounded-[8px] border border-ctp-surface1/80 bg-ctp-base/62 p-3">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="min-w-0">
          <p className={`${textClasses.detail} text-ctp-subtext0`}>Local preview</p>
          {resolvedLocalAudios.length > 0 ? (
            <div className="mt-2 grid gap-2">
              {resolvedLocalAudios.map((audio) => (
                <LocalTrackAudioPreview
                  key={audio.localTrackId}
                  label={audio.label}
                  localTrackId={audio.localTrackId}
                />
              ))}
            </div>
          ) : (
            <p className={`mt-2 ${textClasses.caption}`}>No local audio is linked to this match.</p>
          )}
        </div>
        <div className="grid min-w-0 gap-2">
          <p className={`${textClasses.detail} text-ctp-subtext0`}>Streaming preview</p>
          {streamingTracks.map((track) => (
            <StreamingTrackPreview
              artist={track.artist}
              key={track.providerTrackId}
              providerTrackId={track.providerTrackId}
              title={track.title}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
