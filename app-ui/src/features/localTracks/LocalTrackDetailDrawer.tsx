import { TrackDetailDrawer } from "../tracks/TrackDetailDrawer";

type LocalTrackDetailDrawerProps = {
  localTrackId: number | null;
  onClose: () => void;
  open: boolean;
  syncUrl?: boolean;
};

export function LocalTrackDetailDrawer({
  localTrackId,
  onClose,
  open,
  syncUrl = false,
}: LocalTrackDetailDrawerProps) {
  return (
    <TrackDetailDrawer
      open={open}
      syncUrl={syncUrl}
      target={localTrackId === null ? null : { id: localTrackId, type: "local" }}
      onClose={onClose}
    />
  );
}
