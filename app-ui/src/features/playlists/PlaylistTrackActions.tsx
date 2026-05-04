import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ActionButton } from "../../components/ActionButton";
import { surfaceClasses, textClasses } from "../../styles/componentClasses";
import type { PlaylistTrack } from "./queries";

type PlaylistTrackActionsProps = {
  onReviewTrack?: (track: PlaylistTrack) => void;
  playlistId?: number | string;
  track: PlaylistTrack;
};

type RematchResponse = {
  job_id: string;
  local_track_id: number;
};

async function rematchLocalTrack(localTrackId: number): Promise<RematchResponse> {
  const response = await fetch(`/api/local-tracks/${encodeURIComponent(String(localTrackId))}/rematch`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Re-match request failed with status ${response.status}`);
  }

  return (await response.json()) as RematchResponse;
}

function buildProposalTrackUrl(track: PlaylistTrack) {
  const params = new URLSearchParams({ track_id: String(track.id) });

  if (track.proposal_id !== null) {
    params.set("proposal_id", String(track.proposal_id));
  }

  return `/proposals?${params.toString()}`;
}

export function PlaylistTrackActions({ onReviewTrack, playlistId, track }: PlaylistTrackActionsProps) {
  const [isLinkInfoOpen, setIsLinkInfoOpen] = useState(false);
  const queryClient = useQueryClient();
  const rematchMutation = useMutation({
    mutationFn: rematchLocalTrack,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["playlists"] });
      if (playlistId !== undefined) {
        await queryClient.invalidateQueries({ queryKey: ["playlists", playlistId] });
      }
    },
  });

  if (track.status === "linked") {
    return (
      <div className="relative">
        <ActionButton onClick={() => setIsLinkInfoOpen((current) => !current)}>Linked</ActionButton>
        {isLinkInfoOpen ? (
          <div
            className={`absolute right-0 top-[calc(100%+0.5rem)] z-10 w-56 text-left ${surfaceClasses.popover} ${surfaceClasses.popoverBody} border-ctp-green/30`}
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

  const canRematch = track.local_track_id !== null;
  const isPending = rematchMutation.isPending;

  return (
    <div className="flex flex-col items-start gap-1 lg:items-end">
      <ActionButton
        disabled={!canRematch || isPending}
        onClick={() => {
          if (track.local_track_id !== null) {
            rematchMutation.mutate(track.local_track_id);
          }
        }}
      >
        {isPending ? "Matching..." : "Match"}
      </ActionButton>
      {!canRematch ? <p className="text-[11px] text-ctp-subtext0">No local track to re-match.</p> : null}
      {rematchMutation.isSuccess ? <p className="text-[11px] text-ctp-green">Re-match queued.</p> : null}
      {rematchMutation.isError ? <p className="text-[11px] text-ctp-red">Re-match failed.</p> : null}
    </div>
  );
}
