import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useLibraryTracksQuery } from "./features/library/queries";
import { useMissingLocallyTracksQuery, useUnidentifiedTracksQuery } from "./features/maintenance/queries";
import { type StreamingPlaylist, useLinkProposalsQuery, useStreamingPlaylistsQuery } from "./features/playlists/queries";
import { useStreamingRelationshipSuggestionsQuery } from "./features/relationships/queries";
import { Sidebar } from "./features/shell/Sidebar";
import { Topbar } from "./features/shell/Topbar";
import { ViewShell } from "./features/shell/ViewShell";
import type { PlaylistSyncViewState } from "./features/shell/types";
import {
  type AppViewEntry,
  buildLibraryNavItems,
  buildMaintenanceNavItems,
  buildPlaylistNavItems,
  buildSettingsNavItems,
  buildViewEntries,
  getPlaylistViewId,
  getViewIdFromPath,
  getViewPath,
  playlistCollectionViewId,
  settingsAuthenticationViewId,
  settingsGeneralViewId,
  settingsSyncYoutubeMusicViewId,
  staticViewRoutes,
} from "./features/shell/viewRegistry";

const emptyStreamingPlaylists: StreamingPlaylist[] = [];

function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [activeViewId, setActiveViewId] = useState(playlistCollectionViewId);
  const [hasUserSelectedView, setHasUserSelectedView] = useState(false);
  const [playlistSyncState, setPlaylistSyncState] = useState<PlaylistSyncViewState>();
  const libraryTracksQuery = useLibraryTracksQuery();
  const linkProposalsQuery = useLinkProposalsQuery();
  const missingLocallyQuery = useMissingLocallyTracksQuery();
  const playlistsQuery = useStreamingPlaylistsQuery();
  const relationshipSuggestionsQuery = useStreamingRelationshipSuggestionsQuery();
  const unidentifiedQuery = useUnidentifiedTracksQuery();
  const streamingPlaylists = playlistsQuery.data?.playlists ?? emptyStreamingPlaylists;
  const activeUnidentifiedCount = unidentifiedQuery.data?.tracks.filter((track) => track.ignored_at === null).length;
  const defaultPlaylistViewId = streamingPlaylists[0] ? getPlaylistViewId(streamingPlaylists[0].id) : settingsSyncYoutubeMusicViewId;
  const libraryStats = libraryTracksQuery.data?.pages[0]?.stats;
  const libraryItems = useMemo(
    () => buildLibraryNavItems(libraryStats?.total),
    [libraryStats?.total],
  );
  const maintenanceItems = useMemo(
    () =>
      buildMaintenanceNavItems({
        missingCount: missingLocallyQuery.data?.tracks.length,
        proposalCount: linkProposalsQuery.data?.total_count,
        relationshipCount: relationshipSuggestionsQuery.data?.total_count,
        unidentifiedCount: activeUnidentifiedCount,
      }),
    [
      activeUnidentifiedCount,
      linkProposalsQuery.data?.total_count,
      missingLocallyQuery.data?.tracks.length,
      relationshipSuggestionsQuery.data?.total_count,
    ],
  );
  const playlistItems = useMemo(() => buildPlaylistNavItems(streamingPlaylists), [streamingPlaylists]);
  const settingsItems = useMemo(() => buildSettingsNavItems(), []);
  const viewConfigs = useMemo(() => buildViewEntries(streamingPlaylists), [streamingPlaylists]);
  const viewConfigById = useMemo(
    () => Object.fromEntries(viewConfigs.map((view) => [view.id, view])) as Record<string, AppViewEntry>,
    [viewConfigs],
  );
  const activeView = viewConfigById[activeViewId] ?? viewConfigById.proposals;
  const viewShellIds = useMemo(() => viewConfigs.map((view) => view.id), [viewConfigs]);
  const playlistEmptyMessage = playlistsQuery.isPending
    ? "Loading playlists..."
    : playlistsQuery.isError
      ? "Playlists unavailable."
      : "No full-sync playlists. Configure YouTube Music sync to choose playlists.";
  const playlistEmptyActionLabel = !playlistsQuery.isPending && !playlistsQuery.isError ? "Sync settings" : undefined;
  const routedViewId = useMemo(() => getViewIdFromPath(location.pathname), [location.pathname]);

  useEffect(() => {
    const normalizedPathname = location.pathname.replace(/\/$/, "") || "/";

    if (normalizedPathname === "/settings/sync") {
      navigate(staticViewRoutes[settingsSyncYoutubeMusicViewId], { replace: true });
    }

    if (normalizedPathname === "/playlists") {
      navigate(staticViewRoutes[settingsSyncYoutubeMusicViewId], { replace: true });
    }
  }, [location.pathname, navigate]);

  useEffect(() => {
    if (!routedViewId || viewConfigById[routedViewId] === undefined) {
      return;
    }

    setHasUserSelectedView(true);
    setActiveViewId(routedViewId);
  }, [routedViewId, viewConfigById]);

  useEffect(() => {
    if (playlistsQuery.isPending) {
      return;
    }

    if (routedViewId) {
      return;
    }

    if (!hasUserSelectedView || viewConfigById[activeViewId] === undefined) {
      setActiveViewId(defaultPlaylistViewId);
    }
  }, [activeViewId, defaultPlaylistViewId, hasUserSelectedView, playlistsQuery.isPending, routedViewId, viewConfigById]);

  function handleViewSelect(viewId: string) {
    setHasUserSelectedView(true);
    setActiveViewId(viewId);
    navigate(getViewPath(viewId));
  }

  const isSettingsView =
    activeViewId === settingsGeneralViewId ||
    activeViewId === settingsAuthenticationViewId ||
    activeViewId === settingsSyncYoutubeMusicViewId;

  return (
    <div className="flex h-full min-h-0 w-full flex-1 flex-row overflow-hidden bg-ctp-base text-ctp-text max-md:flex-col">
      <Sidebar
        activeItemId={activeViewId}
        isSettingsMode={isSettingsView}
        libraryItems={libraryItems}
        maintenanceItems={maintenanceItems}
        onConfigureSync={() => handleViewSelect(settingsSyncYoutubeMusicViewId)}
        onHome={() => handleViewSelect("proposals")}
        onSelect={handleViewSelect}
        playlistEmptyActionLabel={playlistEmptyActionLabel}
        playlistEmptyMessage={playlistEmptyMessage}
        playlistItems={playlistItems}
        settingsItems={settingsItems}
      />

      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-ctp-base">
        <Topbar
          isSettingsView={isSettingsView}
          onNavigateHome={() => handleViewSelect("proposals")}
          onOpenAppSettings={() => handleViewSelect(settingsGeneralViewId)}
          onPlaylistSyncStateChange={setPlaylistSyncState}
          view={activeView}
        />
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {viewShellIds.map((viewId) => (
            <ViewShell
              key={viewId}
              activeViewId={activeViewId}
              playlistSyncState={playlistSyncState}
              view={viewConfigById[viewId]}
            />
          ))}
        </div>
      </main>
    </div>
  );
}

export default App;
