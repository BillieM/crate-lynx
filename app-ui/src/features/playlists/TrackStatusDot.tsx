import type { PlaylistTrackStatus } from "./queries";
import { trackStatusDotClasses } from "../../styles/toneClasses";

type TrackStatusDotProps = {
  status: PlaylistTrackStatus;
};

const statusConfig: Record<
  PlaylistTrackStatus,
  {
    ariaLabel: string;
  }
> = {
  linked: {
    ariaLabel: "Linked track",
  },
  pending: {
    ariaLabel: "Pending track",
  },
  unlinked: {
    ariaLabel: "Unlinked track",
  },
};

export function TrackStatusDot({ status }: TrackStatusDotProps) {
  const config = statusConfig[status];

  return (
    <span
      aria-label={config.ariaLabel}
      className={`inline-flex h-2.5 w-2.5 shrink-0 rounded-full ${trackStatusDotClasses[status]}`}
      role="status"
    />
  );
}
