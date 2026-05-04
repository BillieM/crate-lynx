/* eslint-disable react-refresh/only-export-components */

import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { EmptyStateCard } from "./components/EmptyStateCard";
import { StatusMessage } from "./components/StatusMessage";
import { FilterChips } from "./features/playlists/FilterChips";
import { PlaylistHeader } from "./features/playlists/PlaylistHeader";
import { PlaylistSyncConfiguration } from "./features/playlists/PlaylistSyncConfiguration";
import { PlaylistTrackActions } from "./features/playlists/PlaylistTrackActions";
import { PlaylistTrackRow } from "./features/playlists/PlaylistTrackRow";
import { LocalLibraryView } from "./features/library/LocalLibraryView";
import { useLibraryTracksQuery } from "./features/library/queries";
import { MissingLocallyView } from "./features/maintenance/MissingLocallyView";
import { UnidentifiedView } from "./features/maintenance/UnidentifiedView";
import { useMissingLocallyTracksQuery, useUnidentifiedTracksQuery } from "./features/maintenance/queries";
import {
  type StreamingPlaylist,
  useLinkProposalsQuery,
  usePlaylistDetailQuery,
  usePlaylistTracksQuery,
  useStreamingPlaylistsQuery,
} from "./features/playlists/queries";
import { LinkProposalsView } from "./features/proposals/LinkProposalsView";
import {
  filterPlaylistTracks,
  getPlaylistTrackFilterCounts,
  type PlaylistTrackFilter,
} from "./features/playlists/filterTracks";
import { Sidebar } from "./features/shell/Sidebar";
import { Topbar } from "./features/shell/Topbar";
import { getProgressColor } from "./features/shell/progress";
import { textClasses } from "./styles/componentClasses";
import type { NavItem, PlaylistSyncViewState, ViewConfig } from "./features/shell/types";

export { getProgressColor };
export type { ProgressColor, ProgressStatus } from "./features/shell/progress";

const baseViewConfigs = [
  {
    id: "proposals",
    title: "Link proposals",
    actionLabels: [],
    icon: "spark",
  },
  {
    id: "unidentified",
    title: "Unidentified",
    actionLabels: [],
    icon: "spark",
  },
  {
    id: "missing",
    title: "Missing locally",
    actionLabels: [],
    icon: "spark",
  },
  {
    id: "library",
    title: "All tracks",
    actionLabels: [],
    icon: "library",
  },
] satisfies ViewConfig[];

const emptyStreamingPlaylists: StreamingPlaylist[] = [];
const playlistCollectionViewId = "playlists";
const playlistCollectionViewConfig = {
  id: playlistCollectionViewId,
  title: "YouTube Music",
  actionLabels: [],
  icon: "playlist",
} satisfies ViewConfig;
const settingsSyncYoutubeMusicViewId = "settings-sync-youtube-music";
const settingsViewConfigs = [
  {
    id: settingsSyncYoutubeMusicViewId,
    title: "Settings",
    actionLabels: [],
    icon: "settings",
  },
] satisfies ViewConfig[];

const staticViewRoutes: Record<string, string> = {
  library: "/library",
  missing: "/missing",
  proposals: "/proposals",
  [settingsSyncYoutubeMusicViewId]: "/settings/sync/youtube-music",
  unidentified: "/unidentified",
};

function getPlaylistViewId(playlistId: number) {
  return `playlist-${playlistId}`;
}

function getViewPath(viewId: string) {
  if (viewId.startsWith("playlist-")) {
    return `/playlists/${viewId.replace("playlist-", "")}`;
  }

  return staticViewRoutes[viewId] ?? "/";
}

function getViewIdFromPath(pathname: string) {
  const playlistRouteMatch = /^\/playlists\/(?<playlistId>\d+)\/?$/.exec(pathname);

  if (playlistRouteMatch?.groups?.playlistId) {
    return getPlaylistViewId(Number(playlistRouteMatch.groups.playlistId));
  }

  const normalizedPathname = pathname.replace(/\/$/, "") || "/";

  if (normalizedPathname === "/") {
    return null;
  }

  if (normalizedPathname === "/settings" || normalizedPathname === "/settings/sync") {
    return settingsSyncYoutubeMusicViewId;
  }

  return Object.entries(staticViewRoutes).find(([, path]) => path === normalizedPathname)?.[0] ?? null;
}

function getPlaylistTone(playlist: StreamingPlaylist): NavItem["tone"] {
  return playlist.track_count > 0 ? "accent" : "unlinked";
}

function buildPlaylistNavItems(playlists: StreamingPlaylist[]): NavItem[] {
  return playlists.map((playlist) => ({
    id: getPlaylistViewId(playlist.id),
    label: playlist.title,
    badge: playlist.track_count,
    tone: getPlaylistTone(playlist),
  }));
}

function buildPlaylistViewConfigs(playlists: StreamingPlaylist[]): ViewConfig[] {
  return playlists.map((playlist) => ({
    id: getPlaylistViewId(playlist.id),
    title: playlist.title,
    playlistResourceId: playlist.id,
    actionLabels: ["Sync", "Export M3U"],
    icon: "playlist",
  }));
}

function buildMaintenanceNavItems({
  missingCount,
  proposalCount,
  unidentifiedCount,
}: {
  missingCount?: number;
  proposalCount?: number;
  unidentifiedCount?: number;
}): NavItem[] {
  return [
    { id: "proposals", label: "Link proposals", badge: proposalCount, tone: "pending" },
    { id: "unidentified", label: "Unidentified", badge: unidentifiedCount, tone: "alert" },
    { id: "missing", label: "Missing locally", badge: missingCount, tone: "accent" },
  ];
}

function buildLibraryNavItems(totalTrackCount?: number): NavItem[] {
  return [{ id: "library", label: "All tracks", badge: totalTrackCount, tone: "accent" }];
}

function buildSettingsNavItems(): NavItem[] {
  return [{ id: settingsSyncYoutubeMusicViewId, label: "YouTube Music sync", tone: "accent" }];
}

function PlaylistView({
  isActive,
  playlistResourceId,
  syncState,
}: {
  isActive: boolean;
  playlistResourceId: number;
  syncState?: PlaylistSyncViewState;
}) {
  const [activeFilter, setActiveFilter] = useState<PlaylistTrackFilter>("all");
  const playlistDetailQuery = usePlaylistDetailQuery(isActive ? playlistResourceId : null);
  const playlistTracksQuery = usePlaylistTracksQuery(isActive ? playlistResourceId : null);
  const tracks = useMemo(() => playlistTracksQuery.data?.tracks ?? [], [playlistTracksQuery.data?.tracks]);
  const filterCounts = useMemo(() => getPlaylistTrackFilterCounts(tracks), [tracks]);
  const filteredTracks = useMemo(() => filterPlaylistTracks(tracks, activeFilter), [activeFilter, tracks]);

  useEffect(() => {
    setActiveFilter("all");
  }, [playlistResourceId]);

  if (playlistDetailQuery.isPending || playlistTracksQuery.isPending) {
    return (
      <EmptyStateCard
        body="Loading playlist overview..."
        className="text-left"
        title="Loading playlist overview"
      />
    );
  }

  if (playlistDetailQuery.isError || playlistTracksQuery.isError) {
    return (
      <EmptyStateCard
        body="Playlist overview is unavailable right now."
        className="text-left"
        title="Playlist unavailable"
        tone="error"
      />
    );
  }

  if (!playlistDetailQuery.data) {
    return null;
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-5">
      {syncState?.status === "pending" ? (
        <StatusMessage
          body="This playlist is being synced. Track counts and link status may update when the job finishes."
          status="pending"
          title="Playlist sync in progress"
        />
      ) : null}
      {syncState?.status === "error" ? (
        <StatusMessage
          body={playlistDetailQuery.data.playlist.last_sync_error ?? "The playlist sync request failed before the job could be queued."}
          status="error"
          title="Playlist sync failed"
        />
      ) : null}
      <PlaylistHeader playlist={playlistDetailQuery.data.playlist} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <FilterChips activeFilter={activeFilter} counts={filterCounts} onFilterChange={setActiveFilter} />
        <p className={`${textClasses.status} text-ctp-subtext0`}>
          Showing {filteredTracks.length} of {tracks.length} tracks
        </p>
      </div>
      <div aria-label="Playlist tracks" className="min-h-0 flex-1 overflow-y-auto pb-1 pr-1" role="region">
        {filteredTracks.length > 0 ? (
          <div className="space-y-3">
            {filteredTracks.map((track) => (
              <PlaylistTrackRow
                actionSlot={<PlaylistTrackActions playlistId={playlistResourceId} track={track} />}
                key={track.id}
                track={track}
              />
            ))}
          </div>
        ) : (
          <EmptyStateCard body="No tracks match this filter." title="No matching tracks" />
        )}
      </div>
    </section>
  );
}

function ViewShell({
  activeViewId,
  playlistResourceId,
  playlistSyncState,
  viewId,
}: {
  activeViewId: string;
  playlistResourceId?: number;
  playlistSyncState?: PlaylistSyncViewState;
  viewId: string;
}) {
  const isActive = activeViewId === viewId;

  return (
    <div
      aria-hidden={!isActive}
      className={isActive ? "flex min-h-0 flex-1 flex-col overflow-hidden" : "hidden"}
      data-view-active={isActive ? "true" : "false"}
      id={viewId}
    >
      {isActive ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4 sm:p-6">
          {playlistResourceId !== undefined ? (
            <PlaylistView
              isActive={isActive}
              playlistResourceId={playlistResourceId}
              syncState={playlistSyncState?.playlistId === playlistResourceId ? playlistSyncState : undefined}
            />
          ) : viewId === playlistCollectionViewId ? (
            <PlaylistSyncConfiguration />
          ) : viewId === settingsSyncYoutubeMusicViewId ? (
            <PlaylistSyncConfiguration />
          ) : viewId === "proposals" ? (
            <LinkProposalsView />
          ) : viewId === "library" ? (
            <LocalLibraryView />
          ) : viewId === "missing" ? (
            <MissingLocallyView />
          ) : viewId === "unidentified" ? (
            <UnidentifiedView />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

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
  const unidentifiedQuery = useUnidentifiedTracksQuery();
  const streamingPlaylists = playlistsQuery.data?.playlists ?? emptyStreamingPlaylists;
  const defaultPlaylistViewId = streamingPlaylists[0] ? getPlaylistViewId(streamingPlaylists[0].id) : settingsSyncYoutubeMusicViewId;
  const libraryItems = useMemo(
    () => buildLibraryNavItems(libraryTracksQuery.data?.stats.total),
    [libraryTracksQuery.data?.stats.total],
  );
  const maintenanceItems = useMemo(
    () =>
      buildMaintenanceNavItems({
        missingCount: missingLocallyQuery.data?.tracks.length,
        proposalCount: linkProposalsQuery.data?.proposals.length,
        unidentifiedCount: unidentifiedQuery.data?.tracks.length,
      }),
    [
      linkProposalsQuery.data?.proposals.length,
      missingLocallyQuery.data?.tracks.length,
      unidentifiedQuery.data?.tracks.length,
    ],
  );
  const playlistItems = useMemo(() => buildPlaylistNavItems(streamingPlaylists), [streamingPlaylists]);
  const settingsItems = useMemo(() => buildSettingsNavItems(), []);
  const viewConfigs = useMemo(
    () => [...baseViewConfigs, playlistCollectionViewConfig, ...settingsViewConfigs, ...buildPlaylistViewConfigs(streamingPlaylists)],
    [streamingPlaylists],
  );
  const viewConfigById = useMemo(
    () => Object.fromEntries(viewConfigs.map((view) => [view.id, view])) as Record<string, ViewConfig>,
    [viewConfigs],
  );
  const activeView = viewConfigById[activeViewId] ?? viewConfigById.proposals;
  const viewShellIds = useMemo(() => viewConfigs.map((view) => view.id), [viewConfigs]);
  const playlistEmptyMessage = playlistsQuery.isPending
    ? "Loading playlists..."
    : playlistsQuery.isError
      ? "Playlists unavailable."
      : "No selected playlists. Configure YouTube Music sync to choose playlists.";
  const playlistEmptyActionLabel = !playlistsQuery.isPending && !playlistsQuery.isError ? "Sync settings" : undefined;
  const routedViewId = useMemo(() => getViewIdFromPath(location.pathname), [location.pathname]);

  useEffect(() => {
    const normalizedPathname = location.pathname.replace(/\/$/, "") || "/";

    if (normalizedPathname === "/settings" || normalizedPathname === "/settings/sync") {
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

  const isSettingsView = activeViewId === settingsSyncYoutubeMusicViewId;

  return (
    <div className="flex min-h-0 flex-1 flex-row overflow-hidden bg-ctp-base text-ctp-text max-md:flex-col">
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

      <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-ctp-base">
        <Topbar
          isSettingsView={isSettingsView}
          onNavigateHome={() => handleViewSelect("proposals")}
          onOpenAppSettings={() => handleViewSelect(settingsSyncYoutubeMusicViewId)}
          onPlaylistSyncStateChange={setPlaylistSyncState}
          view={activeView}
        />
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {viewShellIds.map((viewId) => (
            <ViewShell
              key={viewId}
              activeViewId={activeViewId}
              playlistResourceId={viewConfigById[viewId].playlistResourceId}
              playlistSyncState={playlistSyncState}
              viewId={viewId}
            />
          ))}
        </div>
      </main>
    </div>
  );
}

export default App;
