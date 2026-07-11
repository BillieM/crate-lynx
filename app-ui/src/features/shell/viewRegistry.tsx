import { createElement, lazy, type ComponentType, type LazyExoticComponent, type ReactNode } from "react";
import type { StreamingPlaylist } from "../playlists/queries";
import type { PlaylistGenerationRun } from "../sonic/queries";
import { RouteFallbackView } from "./RouteFallbackView";
import { routeFallbackKindFromPath, routeFallbackTitle } from "./routeFallback";
import type { NavItem, PlaylistSyncViewState, ViewConfig } from "./types";

const loadLocalDedupeView = () => import("../localDedupe/LocalDedupeView").then((module) => ({ default: module.LocalDedupeView }));
const loadLocalLibraryView = () => import("../library/LocalLibraryView").then((module) => ({ default: module.LocalLibraryView }));
const loadUnidentifiedView = () => import("../maintenance/UnidentifiedView").then((module) => ({ default: module.UnidentifiedView }));
const loadPlaylistSyncConfiguration = () =>
  import("../playlists/PlaylistSyncConfiguration").then((module) => ({ default: module.PlaylistSyncConfiguration }));
const loadPlaylistM3uExportView = () =>
  import("../playlists/PlaylistM3uExportView").then((module) => ({ default: module.PlaylistM3uExportView }));
const loadPlaylistView = () => import("../playlists/PlaylistView").then((module) => ({ default: module.PlaylistView }));
const loadLinkProposalsView = () => import("../proposals/LinkProposalsView").then((module) => ({ default: module.LinkProposalsView }));
const loadStreamingRelationshipsView = () =>
  import("../relationships/StreamingRelationshipsView").then((module) => ({ default: module.StreamingRelationshipsView }));
const loadAuthenticationSettingsView = () =>
  import("../settings/AuthenticationSettingsView").then((module) => ({ default: module.AuthenticationSettingsView }));
const loadGeneralSettingsView = () =>
  import("../settings/GeneralSettingsView").then((module) => ({ default: module.GeneralSettingsView }));
const loadGeneratedRunView = () => import("../sonic/GeneratedRunView").then((module) => ({ default: module.GeneratedRunView }));
const loadPlaylistGeneratorView = () =>
  import("../sonic/PlaylistGeneratorView").then((module) => ({ default: module.PlaylistGeneratorView }));
const loadSoulseekQueueView = () => import("../soulseek/SoulseekQueueView").then((module) => ({ default: module.SoulseekQueueView }));

export const localDedupeViewId = "local-dedupe";
export const playlistExportViewId = "playlist-export";
export const playlistGeneratorViewId = "playlist-generator";
export const routeFallbackViewId = "route-fallback";
export const soulseekQueueViewId = "soulseek-queue";
export const shellLoadingViewId = "shell-loading";
export const streamingRelationshipsViewId = "streaming-relationships";
export const settingsAuthenticationViewId = "settings-authentication";
export const settingsGeneralViewId = "settings-general";
export const settingsSyncYoutubeMusicViewId = "settings-sync-youtube-music";

type AppViewContext = {
  isActive: boolean;
  playlistSyncState?: PlaylistSyncViewState;
  retryKey: number;
};

export type AppViewEntry = ViewConfig & {
  path?: string;
  render: (context: AppViewContext) => ReactNode;
};

type LazyViewLoader<TProps extends object> = () => Promise<{ default: ComponentType<TProps> }>;
const retryableLazyViewCache = new WeakMap<
  LazyViewLoader<object>,
  Map<number, LazyExoticComponent<ComponentType<object>>>
>();

function getRetryableLazyView<TProps extends object>(loader: LazyViewLoader<TProps>, retryKey: number) {
  const cacheKey = loader as LazyViewLoader<object>;
  const loaderCache = retryableLazyViewCache.get(cacheKey) ?? new Map();
  const cachedView = loaderCache.get(retryKey);
  if (cachedView) {
    return cachedView as LazyExoticComponent<ComponentType<TProps>>;
  }

  const View = lazy(loader);
  loaderCache.set(retryKey, View as LazyExoticComponent<ComponentType<object>>);
  retryableLazyViewCache.set(cacheKey, loaderCache);
  return View;
}

// This internal component must live beside the route loaders so retries share
// the module-level lazy cache.
// eslint-disable-next-line react-refresh/only-export-components
function RetryableLazyView<TProps extends object>({
  loader,
  props,
  retryKey,
}: {
  loader: LazyViewLoader<TProps>;
  props: TProps;
  retryKey: number;
}) {
  // React.lazy caches a rejected import. Cache by retry key outside React so
  // initial suspension does not recreate the lazy component on every render.
  const View = getRetryableLazyView(loader, retryKey);

  const ResolvedView = View as unknown as ComponentType<Record<string, unknown>>;
  return createElement(ResolvedView, props as Record<string, unknown>);
}

const staticViewEntries = [
  {
    id: "proposals",
    title: "Link proposals",
    actionLabels: [],
    icon: "spark",
    path: "/proposals",
    render: ({ retryKey }) => <RetryableLazyView loader={loadLinkProposalsView} props={{}} retryKey={retryKey} />,
  },
  {
    id: soulseekQueueViewId,
    title: "Soulseek Queue",
    actionLabels: [],
    icon: "tool",
    path: "/soulseek",
    render: ({ retryKey }) => <RetryableLazyView loader={loadSoulseekQueueView} props={{}} retryKey={retryKey} />,
  },
  {
    id: streamingRelationshipsViewId,
    title: "Streaming relationships",
    actionLabels: [],
    icon: "spark",
    path: "/relationships",
    render: ({ retryKey }) => <RetryableLazyView loader={loadStreamingRelationshipsView} props={{}} retryKey={retryKey} />,
  },
  {
    id: "unidentified",
    title: "Unidentified",
    actionLabels: [],
    icon: "spark",
    path: "/unidentified",
    render: ({ retryKey }) => <RetryableLazyView loader={loadUnidentifiedView} props={{}} retryKey={retryKey} />,
  },
  {
    id: "library",
    title: "All tracks",
    actionLabels: [],
    icon: "library",
    path: "/library",
    render: ({ retryKey }) => <RetryableLazyView loader={loadLocalLibraryView} props={{}} retryKey={retryKey} />,
  },
  {
    id: localDedupeViewId,
    title: "Deduplicate tracks",
    actionLabels: [],
    icon: "tool",
    path: "/tools/dedupe",
    render: ({ retryKey }) => <RetryableLazyView loader={loadLocalDedupeView} props={{}} retryKey={retryKey} />,
  },
  {
    id: playlistExportViewId,
    title: "M3U export",
    actionLabels: [],
    icon: "playlist",
    path: "/playlists/export",
    render: ({ retryKey }) => <RetryableLazyView loader={loadPlaylistM3uExportView} props={{}} retryKey={retryKey} />,
  },
  {
    id: playlistGeneratorViewId,
    title: "Playlist generator",
    actionLabels: [],
    icon: "tool",
    path: "/playlist-generator",
    render: ({ retryKey }) => <RetryableLazyView loader={loadPlaylistGeneratorView} props={{}} retryKey={retryKey} />,
  },
  {
    id: settingsGeneralViewId,
    title: "Settings",
    actionLabels: [],
    icon: "settings",
    path: "/settings",
    render: ({ retryKey }) => <RetryableLazyView loader={loadGeneralSettingsView} props={{}} retryKey={retryKey} />,
  },
  {
    id: settingsAuthenticationViewId,
    title: "Settings",
    actionLabels: [],
    icon: "settings",
    path: "/settings/authentication",
    render: ({ retryKey }) => <RetryableLazyView loader={loadAuthenticationSettingsView} props={{}} retryKey={retryKey} />,
  },
  {
    id: settingsSyncYoutubeMusicViewId,
    title: "Settings",
    actionLabels: [],
    icon: "settings",
    path: "/settings/sync/youtube-music",
    render: ({ retryKey }) => <RetryableLazyView loader={loadPlaylistSyncConfiguration} props={{}} retryKey={retryKey} />,
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

export function getGeneratedRunIdFromViewId(viewId: string | null): number | null {
  const match = /^generated-run-(?<runId>\d+)$/.exec(viewId ?? "");
  return match?.groups?.runId ? Number(match.groups.runId) : null;
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

  if (/^\/proposals\/\d+$/.test(normalizedPathname)) {
    return "proposals";
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

  if (normalizedPathname === "/missing") {
    return soulseekQueueViewId;
  }

  if (normalizedPathname === "/settings/sync") {
    return settingsSyncYoutubeMusicViewId;
  }

  return Object.entries(staticViewRoutes).find(([, path]) => path === normalizedPathname)?.[0] ?? routeFallbackViewId;
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

export function buildToolNavItems(dedupeCount?: number): NavItem[] {
  return [
    { id: localDedupeViewId, label: "Deduplicate tracks", badge: dedupeCount, tone: "pending" },
    { id: playlistGeneratorViewId, label: "Playlist generator", tone: "accent" },
    { id: playlistExportViewId, label: "M3U export", tone: "accent" },
  ];
}

export function buildGeneratedRunNavItems(runs: PlaylistGenerationRun[]): NavItem[] {
  return runs.map((run) => ({
    id: getGeneratedRunViewId(run.id),
    label: `Generation ${run.generation_number}`,
    badge: run.playlist_count,
    tone: run.status === "failed" ? "alert" : run.status === "completed" ? "linked" : "pending",
  }));
}

export function buildMaintenanceNavItems({
  proposalCount,
  relationshipCount,
  soulseekCount,
  unidentifiedCount,
}: {
  proposalCount?: number;
  relationshipCount?: number;
  soulseekCount?: number;
  unidentifiedCount?: number;
}): NavItem[] {
  return [
    { id: "proposals", label: "Link proposals", badge: proposalCount, tone: "pending" },
    { id: soulseekQueueViewId, label: "Soulseek queue", badge: soulseekCount, tone: "accent" },
    { id: streamingRelationshipsViewId, label: "Streaming relationships", badge: relationshipCount, tone: "pending" },
    { id: "unidentified", label: "Unidentified", badge: unidentifiedCount, tone: "alert" },
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
    render: ({ isActive, playlistSyncState, retryKey }) => (
      <RetryableLazyView
        loader={loadPlaylistView}
        props={{
          isActive,
          playlistResourceId: playlist.id,
          syncState: playlistSyncState?.playlistId === playlist.id ? playlistSyncState : undefined,
        }}
        retryKey={retryKey}
      />
    ),
  }));
}

export function buildGeneratedRunViewEntry(runId: number, run?: PlaylistGenerationRun): AppViewEntry {
  return {
    id: getGeneratedRunViewId(runId),
    title: run ? `Generation ${run.generation_number}` : `Generated run ${runId}`,
    actionLabels: [],
    icon: "tool",
    path: getViewPath(getGeneratedRunViewId(runId)),
    render: ({ retryKey }) => (
      <RetryableLazyView loader={loadGeneratedRunView} props={{ runId }} retryKey={retryKey} />
    ),
  };
}

function buildGeneratedRunViewEntries(runs: PlaylistGenerationRun[]): AppViewEntry[] {
  return runs.map((run) => buildGeneratedRunViewEntry(run.id, run));
}

export function buildRouteFallbackViewEntry(pathname: string): AppViewEntry {
  const kind = routeFallbackKindFromPath(pathname);

  return {
    id: routeFallbackViewId,
    title: routeFallbackTitle(kind),
    actionLabels: [],
    icon: "tool",
    render: () => <RouteFallbackView kind={kind} />,
  };
}

export function buildShellLoadingViewEntry(): AppViewEntry {
  return {
    id: shellLoadingViewId,
    title: "Loading",
    actionLabels: [],
    icon: "tool",
    render: () => <RouteFallbackView kind="loading" />,
  };
}

export function buildViewEntries(playlists: StreamingPlaylist[], runs: PlaylistGenerationRun[] = []): AppViewEntry[] {
  return [
    ...staticViewEntries,
    ...buildPlaylistViewEntries(playlists),
    ...buildGeneratedRunViewEntries(runs),
  ];
}
