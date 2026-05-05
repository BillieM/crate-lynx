import type { PlaylistSyncViewState } from "./types";
import type { AppViewEntry } from "./viewRegistry";

export function ViewShell({
  activeViewId,
  playlistSyncState,
  view,
}: {
  activeViewId: string;
  playlistSyncState?: PlaylistSyncViewState;
  view: AppViewEntry;
}) {
  const isActive = activeViewId === view.id;

  return (
    <div
      aria-hidden={!isActive}
      className={isActive ? "flex min-h-0 flex-1 flex-col overflow-hidden" : "hidden"}
      data-view-active={isActive ? "true" : "false"}
      id={view.id}
    >
      {isActive ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4 sm:p-6">
          {view.render({ isActive, playlistSyncState })}
        </div>
      ) : null}
    </div>
  );
}
