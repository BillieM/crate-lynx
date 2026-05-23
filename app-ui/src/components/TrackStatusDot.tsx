import { trackStatusDotClasses, type TrackStatusTone } from "../styles/toneClasses";

type TrackStatusDotProps = {
  ariaLabel?: string;
  className?: string;
  status: TrackStatusTone;
};

const statusLabels = {
  linked: "Linked",
  pending: "Pending",
  unlinked: "Unlinked",
} satisfies Record<TrackStatusTone, string>;

export function TrackStatusDot({ ariaLabel, className = "", status }: TrackStatusDotProps) {
  return (
    <span
      aria-label={ariaLabel ?? `${statusLabels[status]} track`}
      className={`inline-flex h-2.5 w-2.5 shrink-0 rounded-full ${trackStatusDotClasses[status]} ${className}`}
      role="status"
    />
  );
}
