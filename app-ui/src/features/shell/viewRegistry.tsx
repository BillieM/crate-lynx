import type { ReactNode } from "react";
import { LocalLibraryView } from "../library/LocalLibraryView";
import { MissingLocallyView } from "../maintenance/MissingLocallyView";
import { UnidentifiedView } from "../maintenance/UnidentifiedView";
import { PlaylistSyncConfiguration } from "../playlists/PlaylistSyncConfiguration";
import { PlaylistM3uExportView } from "../playlists/PlaylistM3uExportView";
import { PlaylistView } from "../playlists/PlaylistView";
import type { StreamingPlaylist } from "../playlists/queries";
import { LinkProposalsView } from "../proposals/LinkProposalsView";
import { StreamingRelationshipsView } from "../relationships/StreamingRelationshipsView";
import { AuthenticationSettingsView } from "../settings/AuthenticationSettingsView";
import { GeneralSettingsView } from "../settings/GeneralSettingsView";
import { GeneratedRunView } from "../sonic/GeneratedRunView";
import { PlaylistGeneratorView } from "../sonic/PlaylistGeneratorView";
import type { PlaylistGenerationRun } from "../sonic/queries";
import type { NavItem, PlaylistSyncViewState, ViewConfig } from "./types";

export const playlistCollectionViewId = "playlists";
export const playlistExportViewId = "playlist-export";
export const playlistGeneratorViewId = "playlist-generator";
export const streamingRelationshipsViewId = "streaming-relationships";
export const settingsAuthenticationViewId = "settings-authentication";
export const settingsGeneralViewId = "settings-general";
export const settingsSyncYoutubeMusicViewId = "settings-sync-youtube-music";

type AppViewContext = {
  isActive: boolean;
  playlistSyncState?: PlaylistSyncViewState;
};

export type AppViewEntry = ViewConfig & {
  path?: string;
  render: (context: AppViewContext) => ReactNode;
};

const staticViewEntries = [
  {
    id: "proposals",
    title: "Link proposals",
    actionLabels: [],
    icon: "spark",
    path: "/proposals",
    render: () => <LinkProposalsView />,
  },
  {
    id: streamingRelationshipsViewId,
    title: "Streaming relationships",
    actionLabels: [],
    icon: "spark",
    path: "/relationships",
    render: () => <StreamingRelationshipsView />,
  },
  {
    id: "unidentified",
    title: "Unidentified",
    actionLabels: [],
    icon: "spark",
    path: "/unidentified",
    render: () => <UnidentifiedView />,
  },
  {
    id: "missing",
    title: "Missing locally",
    actionLabels: [],
    icon: "spark",
    path: "/missing",
    render: () => <MissingLocallyView />,
  },
  {
    id: "library",
    title: "All tracks",
    actionLabels: [],
    icon: "library",
    path: "/library",
    render: () => <LocalLibraryView />,
  },
  {
    id: playlistCollectionViewId,
    title: "YouTube Music",
    actionLabels: [],
    icon: "playlist",
    render: () => <PlaylistSyncConfiguration />,
  },
  {
    id: playlistExportViewId,
    title: "M3U export",
    actionLabels: [],
    icon: "playlist",
    path: "/playlists/export",
    render: () => <PlaylistM3uExportView />,
  },
  {
    id: playlistGeneratorViewId,
    title: "Playlist generator",
    actionLabels: [],
    icon: "tool",
    path: "/playlist-generator",
    render: () => <PlaylistGeneratorView />,
  },
  {
    id: settingsGeneralViewId,
    title: "Settings",
    actionLabels: [],
    icon: "settings",
    path: "/settings",
    render: () => <GeneralSettingsView />,
  },
  {
    id: settingsAuthenticationViewId,
    title: "Settings",
    actionLabels: [],
    icon: "settings",
    path: "/settings/authentication",
    render: () => <AuthenticationSettingsView />,
  },
  {
    id: settingsSyncYoutubeMusicViewId,
    title: "Settings",
    actionLabels: [],
    icon: "settings",
    path: "/settings/sync/youtube-music",
    render: () => <PlaylistSyncConfiguration />,
  },
] satisfies AppViewEntry[];

export const staticViewRoutes = Object.fromEntries(
  staticViewEntries.flatMap((entry) => (entry.path ? [[entry.id, entry.path]] : [])),
) as Record<string, string>;

export function getPlaylistViewId(playlistId: number) {
  return `playlist-${playlistId}`;
}

export function getGeneratedRunViewId(runId: number) {
  return `generated-run-${runId}`;
}

export function getViewPath(viewId: string) {
  if (/^generated-run-\d+$/.test(viewId)) {
    return `/generated-runs/${viewId.replace("generated-run-", "")}`;
  }

  if (/^playlist-\d+$/.test(viewId)) {
    return `/playlists/${viewId.replace("playlist-", "")}`;
  }

  return staticViewRoutes[viewId] ?? "/";
}

export function getViewIdFromPath(pathname: string) {
  const normalizedPathname = pathname.replace(/\/$/, "") || "/";

  if (normalizedPathname === "/playlists/export") {
    return playlistExportViewId;
  }

  const playlistRouteMatch = /^\/playlists\/(?<playlistId>\d+)\/?$/.exec(pathname);

  if (playlistRouteMatch?.groups?.playlistId) {
    return getPlaylistViewId(Number(playlistRouteMatch.groups.playlistId));
  }

  const generatedRunRouteMatch = /^\/generated-runs\/(?<runId>\d+)\/?$/.exec(pathname);

  if (generatedRunRouteMatch?.groups?.runId) {
    return getGeneratedRunViewId(Number(generatedRunRouteMatch.groups.runId));
  }

  if (normalizedPathname === "/") {
    return null;
  }

  if (normalizedPathname === "/settings/sync") {
    return settingsSyncYoutubeMusicViewId;
  }

  return Object.entries(staticViewRoutes).find(([, path]) => path === normalizedPathname)?.[0] ?? null;
}

function getPlaylistTone(playlist: StreamingPlaylist): NavItem["tone"] {
  return playlist.imported_track_count > 0 ? "accent" : "unlinked";
}

export function buildPlaylistNavItems(playlists: StreamingPlaylist[]): NavItem[] {
  return playlists.map((playlist) => ({
    id: getPlaylistViewId(playlist.id),
    label: playlist.title,
    badge: playlist.imported_track_count,
    tone: getPlaylistTone(playlist),
  }));
}

export function buildToolNavItems(): NavItem[] {
  return [
    { id: playlistGeneratorViewId, label: "Playlist generator", tone: "accent" },
    { id: playlistExportViewId, label: "M3U export", tone: "accent" },
  ];
}

export function buildGeneratedRunNavItems(runs: PlaylistGenerationRun[]): NavItem[] {
  return runs.map((run) => ({
    id: getGeneratedRunViewId(run.id),
    label: `Run #${run.id}`,
    badge: run.playlist_count,
    tone: run.status === "failed" ? "alert" : run.status === "completed" ? "linked" : "pending",
  }));
}

export function buildMaintenanceNavItems({
  missingCount,
  proposalCount,
  relationshipCount,
  unidentifiedCount,
}: {
  missingCount?: number;
  proposalCount?: number;
  relationshipCount?: number;
  unidentifiedCount?: number;
}): NavItem[] {
  return [
    { id: "proposals", label: "Link proposals", badge: proposalCount, tone: "pending" },
    { id: streamingRelationshipsViewId, label: "Streaming relationships", badge: relationshipCount, tone: "pending" },
    { id: "unidentified", label: "Unidentified", badge: unidentifiedCount, tone: "alert" },
    { id: "missing", label: "Missing locally", badge: missingCount, tone: "accent" },
  ];
}

export function buildLibraryNavItems(totalTrackCount?: number): NavItem[] {
  return [{ id: "library", label: "All tracks", badge: totalTrackCount, tone: "accent" }];
}

export function buildSettingsNavItems(): NavItem[] {
  return [
    { id: settingsGeneralViewId, label: "General", tone: "accent" },
    { id: settingsAuthenticationViewId, label: "Authentication", tone: "accent" },
    { id: settingsSyncYoutubeMusicViewId, label: "YouTube Music sync", tone: "accent" },
  ];
}

function buildPlaylistViewEntries(playlists: StreamingPlaylist[]): AppViewEntry[] {
  return playlists.map((playlist) => ({
    id: getPlaylistViewId(playlist.id),
    title: playlist.title,
    playlistResourceId: playlist.id,
    actionLabels: ["Sync", "Export M3U"],
    icon: "playlist",
    render: ({ isActive, playlistSyncState }) => (
      <PlaylistView
        isActive={isActive}
        playlistResourceId={playlist.id}
        syncState={playlistSyncState?.playlistId === playlist.id ? playlistSyncState : undefined}
      />
    ),
  }));
}

function buildGeneratedRunViewEntries(runs: PlaylistGenerationRun[]): AppViewEntry[] {
  return runs.map((run) => ({
    id: getGeneratedRunViewId(run.id),
    title: `Generated run #${run.id}`,
    actionLabels: [],
    icon: "tool",
    path: getViewPath(getGeneratedRunViewId(run.id)),
    render: () => <GeneratedRunView runId={run.id} />,
  }));
}

export function buildViewEntries(playlists: StreamingPlaylist[], runs: PlaylistGenerationRun[] = []): AppViewEntry[] {
  return [
    ...staticViewEntries,
    ...buildPlaylistViewEntries(playlists),
    ...buildGeneratedRunViewEntries(runs),
  ];
}
