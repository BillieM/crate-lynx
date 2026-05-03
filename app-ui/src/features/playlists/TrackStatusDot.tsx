import type { PlaylistTrackStatus } from "./queries";

type TrackStatusDotProps = {
  status: PlaylistTrackStatus;
};

const statusConfig: Record<
  PlaylistTrackStatus,
  {
    ariaLabel: string;
    className: string;
  }
> = {
  linked: {
    ariaLabel: "Linked track",
    className: "bg-ctp-green shadow-[0_0_0_4px_rgba(166,227,161,0.14)]",
  },
  pending: {
    ariaLabel: "Pending track",
    className: "bg-ctp-yellow shadow-[0_0_0_4px_rgba(249,226,175,0.16)]",
  },
  unlinked: {
    ariaLabel: "Unlinked track",
    className: "bg-ctp-red shadow-[0_0_0_4px_rgba(243,139,168,0.16)]",
  },
};

export function TrackStatusDot({ status }: TrackStatusDotProps) {
  const config = statusConfig[status];

  return (
    <span
      aria-label={config.ariaLabel}
      className={`inline-flex h-2.5 w-2.5 shrink-0 rounded-full ${config.className}`}
      role="status"
    />
  );
}
