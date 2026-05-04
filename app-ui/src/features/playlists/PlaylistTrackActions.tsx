import { useState } from "react";

import { ActionButton } from "../../components/ActionButton";
import { controlClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import type { PlaylistTrack } from "./queries";

type PlaylistTrackActionsProps = {
  onReviewTrack?: (track: PlaylistTrack) => void;
  playlistId?: number | string;
  track: PlaylistTrack;
};

function buildProposalTrackUrl(track: PlaylistTrack) {
  const params = new URLSearchParams({ track_id: String(track.id) });

  if (track.proposal_id !== null) {
    params.set("proposal_id", String(track.proposal_id));
  }

  return `/proposals?${params.toString()}`;
}

export function PlaylistTrackActions({ onReviewTrack, track }: PlaylistTrackActionsProps) {
  const [isLinkInfoOpen, setIsLinkInfoOpen] = useState(false);

  if (track.status === "linked") {
    return (
      <div className="relative">
        <ActionButton onClick={() => setIsLinkInfoOpen((current) => !current)}>Linked</ActionButton>
        {isLinkInfoOpen ? (
          <div
            className={`absolute right-0 ${controlClasses.popoverOffset} z-10 w-56 text-left ${surfaceClasses.popover} ${surfaceClasses.popoverBody} border-ctp-green/30`}
            role="dialog"
          >
            <p className={`${textClasses.eyebrow} text-ctp-green`}>Final link info</p>
            <p className={`mt-2 ${textClasses.caption}`}>
              Final link #{track.final_link_id ?? "unknown"} maps this playlist track to local track #
              {track.local_track_id ?? "unknown"}.
            </p>
          </div>
        ) : null}
      </div>
    );
  }

  if (track.status === "pending") {
    const handleReview = () => {
      if (onReviewTrack) {
        onReviewTrack(track);
        return;
      }

      window.location.assign(buildProposalTrackUrl(track));
    };

    return <ActionButton onClick={handleReview}>Review</ActionButton>;
  }

  return null;
}
