import { X } from "lucide-react";
import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";

import { ActionButton } from "../../components/ActionButton";
import { controlClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import type { PlaylistTrack } from "./queries";

type PlaylistTrackActionsProps = {
  onOpenTrackDetail?: (track: PlaylistTrack) => void;
  onReviewTrack?: (track: PlaylistTrack) => void;
  playlistId?: number | string;
  track: PlaylistTrack;
};

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function buildProposalTrackUrl(track: PlaylistTrack) {
  const params = new URLSearchParams({ track_id: String(track.id) });

  if (track.proposal_id !== null) {
    params.set("proposal_id", String(track.proposal_id));
  }

  return `/proposals?${params.toString()}`;
}

export function PlaylistTrackActions({ onOpenTrackDetail, onReviewTrack, track }: PlaylistTrackActionsProps) {
  const [isLinkInfoOpen, setIsLinkInfoOpen] = useState(false);
  const dialogId = useId();
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isLinkInfoOpen) {
      return;
    }

    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    window.setTimeout(() => {
      const firstFocusable = panelRef.current?.querySelector<HTMLElement>(focusableSelector);
      (firstFocusable ?? panelRef.current)?.focus();
    }, 0);

    return () => {
      returnFocusRef.current?.focus();
      returnFocusRef.current = null;
    };
  }, [isLinkInfoOpen]);

  function closeLinkInfo() {
    setIsLinkInfoOpen(false);
  }

  function handleDialogKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeLinkInfo();
      return;
    }

    if (event.key !== "Tab") {
      return;
    }

    const focusable = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? []);

    if (focusable.length === 0) {
      event.preventDefault();
      panelRef.current?.focus();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  if (track.status === "linked") {
    const handleLinkedAction = () => {
      if (onOpenTrackDetail && track.local_track_id !== null) {
        onOpenTrackDetail(track);
        return;
      }

      setIsLinkInfoOpen((current) => !current);
    };

    return (
      <div className="relative">
        <ActionButton
          aria-controls={isLinkInfoOpen ? dialogId : undefined}
          aria-expanded={isLinkInfoOpen}
          onClick={handleLinkedAction}
        >
          Linked
        </ActionButton>
        {isLinkInfoOpen ? (
          <div
            aria-describedby={descriptionId}
            aria-labelledby={titleId}
            aria-modal="true"
            className={`absolute right-0 ${controlClasses.popoverOffset} z-10 w-56 text-left ${surfaceClasses.popover} ${surfaceClasses.popoverBody} border-ctp-green/30`}
            id={dialogId}
            ref={panelRef}
            role="dialog"
            tabIndex={-1}
            onKeyDown={handleDialogKeyDown}
          >
            <div className="flex items-start justify-between gap-3">
              <p className={`${textClasses.eyebrow} text-ctp-green`} id={titleId}>
                Final link info
              </p>
              <button
                aria-label="Close final link info"
                className={`${controlClasses.actionButton} ${controlClasses.actionButtonCompact} border-ctp-surface1 bg-ctp-surface0 px-1.5 py-1 text-ctp-text hover:bg-ctp-surface1`}
                type="button"
                onClick={closeLinkInfo}
              >
                <X aria-hidden="true" className="h-3.5 w-3.5" />
              </button>
            </div>
            <p className={`mt-2 ${textClasses.caption}`} id={descriptionId}>
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
