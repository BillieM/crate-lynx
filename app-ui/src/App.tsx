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
import {
  type StreamingPlaylist,
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
import { asRgb, getProgressColor, lerp, mixColors } from "./features/shell/progress";
import type { NavItem, PlaylistSyncViewState, ViewConfig } from "./features/shell/types";

export { asRgb, getProgressColor, lerp, mixColors };
export type { ProgressStatus, RgbColor } from "./features/shell/progress";

const maintenanceItems: NavItem[] = [
  { id: "proposals", label: "Link proposals", badge: 14, tone: "pending" },
  { id: "unidentified", label: "Unidentified", badge: 3, tone: "alert" },
  { id: "missing", label: "Missing locally", badge: 28, tone: "accent" },
];

const libraryItems: NavItem[] = [
  { id: "library", label: "All tracks", badge: 312, tone: "accent" },
];

const baseViewConfigs = [
  {
    id: "proposals",
    title: "Link proposals",
    pillLabel: "Needs approval",
    pillTone: "pill-pending",
    actionLabels: [],
    icon: "spark",
  },
  {
    id: "unidentified",
    title: "Unidentified",
    pillLabel: "Rescue queue",
    pillTone: "pill-info",
    actionLabels: [],
    icon: "spark",
  },
  {
    id: "missing",
    title: "Missing locally",
    pillLabel: "Gap report",
    pillTone: "pill-info",
    actionLabels: [],
    icon: "spark",
  },
  {
    id: "library",
    title: "All tracks",
    pillLabel: "Local library",
    pillTone: "pill-lib",
    actionLabels: [],
    icon: "library",
  },
] satisfies ViewConfig[];

const emptyStreamingPlaylists: StreamingPlaylist[] = [];
const playlistCollectionViewId = "playlists";
const playlistCollectionViewConfig = {
  id: playlistCollectionViewId,
  title: "YouTube Music",
  pillLabel: "Playlist sync",
  pillTone: "pill-info",
  actionLabels: [],
  icon: "playlist",
} satisfies ViewConfig;

const staticViewRoutes: Record<string, string> = {
  library: "/library",
  missing: "/missing",
  playlists: "/playlists",
  proposals: "/proposals",
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
    pillLabel: "YouTube Music",
    pillTone: "pill-info",
    playlistResourceId: playlist.id,
    actionLabels: ["Sync", "Export M3U"],
    icon: "playlist",
  }));
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
        <p className="text-[12px] font-medium text-ctp-subtext0">
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
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-6">
          {playlistResourceId !== undefined ? (
            <PlaylistView
              isActive={isActive}
              playlistResourceId={playlistResourceId}
              syncState={playlistSyncState?.playlistId === playlistResourceId ? playlistSyncState : undefined}
            />
          ) : viewId === playlistCollectionViewId ? (
            <PlaylistSyncConfiguration />
          ) : viewId === "proposals" ? (
            <LinkProposalsView />
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
  const playlistsQuery = useStreamingPlaylistsQuery();
  const streamingPlaylists = playlistsQuery.data?.playlists ?? emptyStreamingPlaylists;
  const defaultPlaylistViewId = streamingPlaylists[0] ? getPlaylistViewId(streamingPlaylists[0].id) : playlistCollectionViewId;
  const playlistItems = useMemo(() => buildPlaylistNavItems(streamingPlaylists), [streamingPlaylists]);
  const viewConfigs = useMemo(
    () => [...baseViewConfigs, playlistCollectionViewConfig, ...buildPlaylistViewConfigs(streamingPlaylists)],
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
  const playlistEmptyActionLabel = !playlistsQuery.isPending && !playlistsQuery.isError ? "Configure sync" : undefined;
  const routedViewId = useMemo(() => getViewIdFromPath(location.pathname), [location.pathname]);

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

  return (
    <div className="flex min-h-0 flex-1 flex-row overflow-hidden bg-ctp-base text-ctp-text">
      <Sidebar
        activeItemId={activeViewId}
        libraryItems={libraryItems}
        maintenanceItems={maintenanceItems}
        onConfigureSync={() => handleViewSelect(playlistCollectionViewId)}
        onSelect={handleViewSelect}
        playlistEmptyActionLabel={playlistEmptyActionLabel}
        playlistEmptyMessage={playlistEmptyMessage}
        playlistItems={playlistItems}
      />

      <main className="flex min-h-0 flex-1 flex-col bg-ctp-base">
        <Topbar
          onConfigureSync={() => handleViewSelect(playlistCollectionViewId)}
          onPlaylistSyncStateChange={setPlaylistSyncState}
          playlistCollectionViewId={playlistCollectionViewId}
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
