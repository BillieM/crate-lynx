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
    className:
      "bg-ctp-green shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-green)_14%,transparent)]",
  },
  pending: {
    ariaLabel: "Pending track",
    className:
      "bg-ctp-yellow shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-yellow)_16%,transparent)]",
  },
  unlinked: {
    ariaLabel: "Unlinked track",
    className:
      "bg-ctp-red shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-ctp-red)_16%,transparent)]",
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
