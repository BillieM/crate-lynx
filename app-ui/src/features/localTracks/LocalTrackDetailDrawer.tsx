import { useSearchParams } from "react-router-dom";

import { Drawer } from "../../components/Drawer";
import { textClasses } from "../../styles/componentClasses";
import { useLocalTrackDetailQuery } from "./queries";

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
  const [searchParams, setSearchParams] = useSearchParams();
  const detailId = syncUrl ? searchParams.get("detail") : localTrackId;
  const effectiveOpen = open || (syncUrl && detailId !== null);
  const query = useLocalTrackDetailQuery(detailId, effectiveOpen);

  function handleClose() {
    if (syncUrl) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.delete("detail");
      setSearchParams(nextParams, { replace: true });
    }

    onClose();
  }

  return (
    <Drawer open={effectiveOpen} title={detailId ? `Track #${detailId}` : "Track detail"} onClose={handleClose}>
      {query.isLoading ? <p className={textClasses.caption}>Loading track detail...</p> : null}
      {query.isError ? <p className="text-[12px] font-medium text-ctp-red">Track detail could not be loaded.</p> : null}
      {query.data ? (
        <pre className="max-h-full overflow-auto whitespace-pre-wrap rounded-[8px] bg-ctp-mantle p-3 text-[11px] leading-5 text-ctp-subtext0">
          {JSON.stringify(query.data, null, 2)}
        </pre>
      ) : null}
    </Drawer>
  );
}
