import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { JobRefreshProvider } from "./lib/JobRefreshProvider";
import type { StreamingPlaylist } from "./features/playlists/queries";
import { Sidebar } from "./features/shell/Sidebar";
import { Topbar } from "./features/shell/Topbar";
import { ViewShell } from "./features/shell/ViewShell";
import { useShellSummaryQuery } from "./features/shell/queries";
import type { PlaylistSyncViewState } from "./features/shell/types";
import {
  type AppViewEntry,
  buildGeneratedRunViewEntry,
  buildGeneratedRunNavItems,
  buildLibraryNavItems,
  buildMaintenanceNavItems,
  buildPlaylistNavItems,
  buildRouteFallbackViewEntry,
  buildSettingsNavItems,
  buildShellLoadingViewEntry,
  buildToolNavItems,
  buildViewEntries,
  getGeneratedRunIdFromViewId,
  getPlaylistViewId,
  getViewIdFromPath,
  getViewPath,
  routeFallbackViewId,
  settingsAuthenticationViewId,
  settingsGeneralViewId,
  settingsSyncYoutubeMusicViewId,
  shellLoadingViewId,
  soulseekQueueViewId,
  staticViewRoutes,
} from "./features/shell/viewRegistry";
import type { PlaylistGenerationRun } from "./features/sonic/queries";

const emptyStreamingPlaylists: StreamingPlaylist[] = [];
const emptySonicRuns: PlaylistGenerationRun[] = [];

function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [activeViewId, setActiveViewId] = useState(shellLoadingViewId);
  const [hasUserSelectedView, setHasUserSelectedView] = useState(false);
  const [playlistSyncState, setPlaylistSyncState] = useState<PlaylistSyncViewState>();
  const [isNavigationOpen, setIsNavigationOpen] = useState(false);
  const [settingsReturnLabel, setSettingsReturnLabel] = useState("Home");
  const navigationTriggerRef = useRef<HTMLButtonElement>(null);
  const navigationWasOpenRef = useRef(false);
  const settingsReturnPathRef = useRef<string | null>(null);
  const shellSummaryQuery = useShellSummaryQuery();
  const streamingPlaylists = shellSummaryQuery.data?.playlists ?? emptyStreamingPlaylists;
  const sonicRuns = shellSummaryQuery.data?.generated_runs ?? emptySonicRuns;
  const shellCounts = shellSummaryQuery.data?.counts;
  const defaultPlaylistViewId = streamingPlaylists[0] ? getPlaylistViewId(streamingPlaylists[0].id) : settingsSyncYoutubeMusicViewId;
  const libraryItems = useMemo(
    () => buildLibraryNavItems(shellCounts?.library_track_total),
    [shellCounts?.library_track_total],
  );
  const maintenanceItems = useMemo(
    () =>
      buildMaintenanceNavItems({
        proposalCount: shellCounts?.link_proposal_count,
        relationshipCount: shellCounts?.relationship_suggestion_count,
        soulseekCount: shellCounts?.soulseek_unlinked_count,
        unidentifiedCount: shellCounts?.unidentified_active_count,
      }),
    [
      shellCounts?.link_proposal_count,
      shellCounts?.relationship_suggestion_count,
      shellCounts?.soulseek_unlinked_count,
      shellCounts?.unidentified_active_count,
    ],
  );
  const playlistItems = useMemo(() => buildPlaylistNavItems(streamingPlaylists), [streamingPlaylists]);
  const generatedRunItems = useMemo(() => buildGeneratedRunNavItems(sonicRuns), [sonicRuns]);
  const settingsItems = useMemo(() => buildSettingsNavItems(), []);
  const toolItems = useMemo(() => buildToolNavItems(), []);
  const routedViewId = useMemo(() => getViewIdFromPath(location.pathname), [location.pathname]);
  const routedGeneratedRunId = getGeneratedRunIdFromViewId(routedViewId);
  const baseViewConfigs = useMemo(() => {
    const entries = buildViewEntries(streamingPlaylists, sonicRuns);
    if (
      routedGeneratedRunId !== null &&
      !entries.some((entry) => entry.id === getViewIdFromPath(`/generated-runs/${routedGeneratedRunId}`))
    ) {
      entries.push(buildGeneratedRunViewEntry(routedGeneratedRunId));
    }
    return entries;
  }, [routedGeneratedRunId, sonicRuns, streamingPlaylists]);
  const baseViewConfigById = useMemo(
    () => Object.fromEntries(baseViewConfigs.map((view) => [view.id, view])) as Record<string, AppViewEntry>,
    [baseViewConfigs],
  );
  const routedViewIsMissing =
    routedViewId !== null &&
    routedViewId !== routeFallbackViewId &&
    baseViewConfigById[routedViewId] === undefined &&
    !shellSummaryQuery.isPending;
  const shouldShowRouteFallback = routedViewId === routeFallbackViewId || routedViewIsMissing;
  const routeFallbackView = useMemo(() => buildRouteFallbackViewEntry(location.pathname), [location.pathname]);
  const shellLoadingView = useMemo(() => buildShellLoadingViewEntry(), []);
  const viewConfigs = useMemo(
    () => [
      shellLoadingView,
      ...baseViewConfigs,
      ...(shouldShowRouteFallback ? [routeFallbackView] : []),
    ],
    [baseViewConfigs, routeFallbackView, shellLoadingView, shouldShowRouteFallback],
  );
  const viewConfigById = useMemo(
    () => Object.fromEntries(viewConfigs.map((view) => [view.id, view])) as Record<string, AppViewEntry>,
    [viewConfigs],
  );
  const activeView = viewConfigById[activeViewId] ?? viewConfigById[routeFallbackViewId] ?? viewConfigById.proposals;
  const viewShellIds = useMemo(() => viewConfigs.map((view) => view.id), [viewConfigs]);
  const playlistEmptyMessage = shellSummaryQuery.isPending
    ? "Loading playlists..."
    : shellSummaryQuery.isError
      ? "Playlists unavailable."
      : "No full-sync playlists. Configure YouTube Music sync to choose playlists.";
  const playlistEmptyActionLabel = !shellSummaryQuery.isPending && !shellSummaryQuery.isError ? "Sync settings" : undefined;

  const closeNavigation = useCallback(() => setIsNavigationOpen(false), []);

  useEffect(() => {
    if (navigationWasOpenRef.current && !isNavigationOpen) {
      navigationTriggerRef.current?.focus();
    }
    navigationWasOpenRef.current = isNavigationOpen;
  }, [isNavigationOpen]);

  useEffect(() => {
    closeNavigation();
  }, [closeNavigation, location.pathname, location.search]);

  useEffect(() => {
    const normalizedPathname = location.pathname.replace(/\/$/, "") || "/";

    if (normalizedPathname === "/settings/sync") {
      navigate(staticViewRoutes[settingsSyncYoutubeMusicViewId], { replace: true });
    }

    if (normalizedPathname === "/playlists") {
      navigate(staticViewRoutes[settingsSyncYoutubeMusicViewId], { replace: true });
    }

    if (normalizedPathname === "/missing") {
      navigate(staticViewRoutes[soulseekQueueViewId], { replace: true });
    }
  }, [location.pathname, navigate]);

  useEffect(() => {
    if (!routedViewId) {
      return;
    }

    if (baseViewConfigById[routedViewId] !== undefined) {
      setHasUserSelectedView(true);
      setActiveViewId(routedViewId);
      return;
    }

    if (routedViewId === routeFallbackViewId || !shellSummaryQuery.isPending) {
      setHasUserSelectedView(true);
      setActiveViewId(routeFallbackViewId);
    }
  }, [baseViewConfigById, routedViewId, shellSummaryQuery.isPending]);

  useEffect(() => {
    if (shellSummaryQuery.isPending) {
      return;
    }

    if (routedViewId) {
      return;
    }

    if (!hasUserSelectedView || activeViewId === shellLoadingViewId || viewConfigById[activeViewId] === undefined) {
      setActiveViewId(defaultPlaylistViewId);
    }
  }, [
    activeViewId,
    defaultPlaylistViewId,
    hasUserSelectedView,
    routedViewId,
    shellSummaryQuery.isPending,
    viewConfigById,
  ]);

  function handleViewSelect(viewId: string) {
    closeNavigation();
    setHasUserSelectedView(true);
    setActiveViewId(viewId);
    navigate(getViewPath(viewId));
  }

  function handleNavigateHome() {
    settingsReturnPathRef.current = null;
    setSettingsReturnLabel("Home");
    handleViewSelect(defaultPlaylistViewId);
  }

  function handleOpenAppSettings() {
    settingsReturnPathRef.current = `${location.pathname}${location.search}`;
    setSettingsReturnLabel(activeView.title);
    handleViewSelect(settingsGeneralViewId);
  }

  function handleReturnFromSettings() {
    const returnPath = settingsReturnPathRef.current;
    settingsReturnPathRef.current = null;
    setSettingsReturnLabel("Home");

    if (returnPath) {
      navigate(returnPath);
      return;
    }

    handleNavigateHome();
  }

  const isSettingsView =
    activeViewId === settingsGeneralViewId ||
    activeViewId === settingsAuthenticationViewId ||
    activeViewId === settingsSyncYoutubeMusicViewId;

  return (
    <JobRefreshProvider>
      <div className="flex h-full min-h-0 w-full flex-1 flex-row overflow-hidden bg-ctp-base text-ctp-text">
      <Sidebar
        activeItemId={activeViewId}
        generatedRunItems={generatedRunItems}
        isOpen={isNavigationOpen}
        isSettingsMode={isSettingsView}
        libraryItems={libraryItems}
        maintenanceItems={maintenanceItems}
        onConfigureSync={() => handleViewSelect(settingsSyncYoutubeMusicViewId)}
        onClose={closeNavigation}
        onHome={handleNavigateHome}
        onSelect={handleViewSelect}
        playlistEmptyActionLabel={playlistEmptyActionLabel}
        playlistEmptyMessage={playlistEmptyMessage}
        playlistItems={playlistItems}
        settingsItems={settingsItems}
        toolItems={toolItems}
      />

      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-ctp-base">
        <Topbar
          isNavigationOpen={isNavigationOpen}
          isSettingsView={isSettingsView}
          navigationTriggerRef={navigationTriggerRef}
          onOpenNavigation={() => setIsNavigationOpen(true)}
          onReturnFromSettings={handleReturnFromSettings}
          onOpenAppSettings={handleOpenAppSettings}
          onPlaylistSyncStateChange={setPlaylistSyncState}
          settingsReturnLabel={settingsReturnLabel}
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
    </JobRefreshProvider>
  );
}

export default App;
