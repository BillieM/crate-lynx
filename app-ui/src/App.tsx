/* eslint-disable react-refresh/only-export-components */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FilterChips } from "./features/playlists/FilterChips";
import { PlaylistHeader } from "./features/playlists/PlaylistHeader";
import { PlaylistTrackActions } from "./features/playlists/PlaylistTrackActions";
import { PlaylistTrackRow } from "./features/playlists/PlaylistTrackRow";
import {
  exportPlaylistM3u,
  playlistQueryKeys,
  refreshStreamingAccountMetadata,
  type StreamingPlaylist,
  type StreamingPlaylistConfig,
  type StreamingSyncResponse,
  updateStreamingPlaylistConfig,
  usePlaylistDetailQuery,
  useStreamingPlaylistConfigQuery,
  useStreamingPlaylistsQuery,
  usePlaylistTracksQuery,
} from "./features/playlists/queries";
import {
  filterPlaylistTracks,
  getPlaylistTrackFilterCounts,
  type PlaylistTrackFilter,
} from "./features/playlists/filterTracks";

export type ProgressStatus = "unlinked" | "pending" | "linked";

export type RgbColor = {
  blue: number;
  green: number;
  red: number;
};

const progressPalette = {
  linked: { red: 166, green: 227, blue: 161 },
  pending: { red: 249, green: 226, blue: 175 },
  unlinked: { red: 108, green: 112, blue: 134 },
} satisfies Record<ProgressStatus, RgbColor>;

function clampPercentage(matchPercentage: number) {
  return Math.max(0, Math.min(100, matchPercentage));
}

export function lerp(start: number, end: number, amount: number) {
  return Math.round(start + (end - start) * amount);
}

export function mixColors(start: RgbColor, end: RgbColor, amount: number): RgbColor {
  return {
    red: lerp(start.red, end.red, amount),
    green: lerp(start.green, end.green, amount),
    blue: lerp(start.blue, end.blue, amount),
  };
}

export function getProgressColor(matchPercentage: number): RgbColor {
  const normalized = clampPercentage(matchPercentage) / 100;

  if (normalized <= 0.5) {
    return mixColors(progressPalette.unlinked, progressPalette.pending, normalized / 0.5);
  }

  return mixColors(progressPalette.pending, progressPalette.linked, (normalized - 0.5) / 0.5);
}

export function asRgb(color: RgbColor, alpha = 1) {
  return `rgba(${color.red}, ${color.green}, ${color.blue}, ${alpha})`;
}

type NavItem = {
  badge?: number;
  id: string;
  label: string;
  progress?: {
    complete: number;
    total: number;
  };
  tone: ProgressStatus | "alert" | "accent";
};

type TopbarPillTone = "pill-info" | "pill-pending" | "pill-lib";

type SearchResult = {
  id: number;
  kind: "playlist" | "streaming_track" | "local_track";
  route_path: string;
  subtitle: string;
  title: string;
};

type SearchResponse = {
  query: string;
  results: SearchResult[];
};

type ViewConfig = {
  actionLabels: string[];
  icon: "spark" | "playlist" | "library";
  id: string;
  playlistResourceId?: number;
  pillLabel: string;
  pillTone: TopbarPillTone;
  title: string;
};

type PlaylistCollectionStatus = "empty" | "error" | "loading" | "ready";

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

const searchKindLabels: Record<SearchResult["kind"], string> = {
  playlist: "Playlist",
  streaming_track: "Streaming",
  local_track: "Local",
};

function getPlaylistViewId(playlistId: number) {
  return `playlist-${playlistId}`;
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

function formatPlaylistTimestamp(timestamp: string | null) {
  if (!timestamp) {
    return "Not synced yet";
  }

  return timestamp.replace("T", " ").replace(/(?:\.\d+)?Z?$/, "");
}

function getSelectedPlaylistCount(playlists: StreamingPlaylistConfig[]) {
  return playlists.filter((playlist) => playlist.selected_for_sync).length;
}

function useDebouncedValue(value: string, delayMs: number) {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setDebouncedValue(value);
    }, delayMs);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [delayMs, value]);

  return debouncedValue;
}

async function fetchSearchResults(query: string) {
  const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);

  if (!response.ok) {
    throw new Error(`Search request failed with status ${response.status}`);
  }

  return (await response.json()) as SearchResponse;
}

async function syncStreamingAccount(accountId: number): Promise<StreamingSyncResponse> {
  const response = await fetch(`/api/streaming/accounts/${encodeURIComponent(String(accountId))}/sync`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Sync request failed with status ${response.status}`);
  }

  return (await response.json()) as StreamingSyncResponse;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");

  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

function getBadgeClasses(tone: NavItem["tone"]) {
  switch (tone) {
    case "pending":
      return "bg-ctp-yellow/18 text-ctp-yellow ring-1 ring-inset ring-ctp-yellow/30";
    case "alert":
      return "bg-ctp-red/18 text-ctp-red ring-1 ring-inset ring-ctp-red/30";
    case "accent":
      return "bg-ctp-mauve/20 text-ctp-mauve ring-1 ring-inset ring-ctp-mauve/30";
    case "linked":
      return "bg-ctp-green/18 text-ctp-green ring-1 ring-inset ring-ctp-green/30";
    case "unlinked":
      return "bg-ctp-overlay0/25 text-ctp-subtext0 ring-1 ring-inset ring-ctp-surface1/70";
  }
}

function getTopbarPillClasses(tone: TopbarPillTone) {
  switch (tone) {
    case "pill-pending":
      return "bg-ctp-yellow/18 text-ctp-yellow ring-1 ring-inset ring-ctp-yellow/30";
    case "pill-lib":
      return "bg-ctp-mauve/20 text-ctp-mauve ring-1 ring-inset ring-ctp-mauve/30";
    case "pill-info":
      return "bg-ctp-surface0 text-ctp-subtext0 ring-1 ring-inset ring-ctp-surface1/70";
  }
}

function TopbarIcon({ icon }: { icon: ViewConfig["icon"] }) {
  if (icon === "playlist") {
    return (
      <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 24 24">
        <path
          d="M8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0Zm10-3a2 2 0 1 1-4 0 2 2 0 0 1 4 0Zm-4 0V6l6-1.5v9"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.7"
        />
      </svg>
    );
  }

  if (icon === "library") {
    return (
      <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 24 24">
        <path
          d="M5 6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v11a1.5 1.5 0 0 1-1.5 1.5h-10A2.5 2.5 0 0 1 5 16.5v-10Z"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.7"
        />
        <path d="M8.5 8.5h7m-7 3h7m-7 3h4" stroke="currentColor" strokeLinecap="round" strokeWidth="1.7" />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 24 24">
      <path
        d="m12 3 1.9 4.97L19 10l-5.1 2.03L12 17l-1.9-4.97L5 10l5.1-2.03L12 3Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.7"
      />
    </svg>
  );
}

function SidebarSection({
  activeItemId,
  emptyMessage,
  items,
  onSelect,
  title,
}: {
  activeItemId: string;
  emptyMessage?: string;
  items: NavItem[];
  onSelect: (itemId: string) => void;
  title: string;
}) {
  return (
    <section className="space-y-3">
      <h2 className="px-4 text-[11px] font-semibold uppercase tracking-[0.24em] text-ctp-subtext0">
        {title}
      </h2>
      <div className="space-y-1.5">
        {items.length === 0 && emptyMessage ? (
          <p className="px-4 py-2.5 text-[12px] text-ctp-subtext0">{emptyMessage}</p>
        ) : null}
        {items.map((item) => (
          <button
            key={item.id}
            className={`flex w-full items-center gap-3 rounded-[10px] px-4 py-2.5 text-left transition-colors hover:bg-ctp-surface0/80 ${
              item.id === activeItemId ? "bg-ctp-surface0 text-ctp-text" : "text-ctp-subtext1"
            }`}
            onClick={() => onSelect(item.id)}
            type="button"
          >
            <span className="min-w-0 flex-1 truncate text-[14px] font-medium">
              {item.label}
            </span>
            {item.progress ? (
              <ProgressFraction complete={item.progress.complete} total={item.progress.total} />
            ) : null}
            {item.badge ? (
              <span
                className={`rounded-full px-2.5 py-1 text-[11px] font-semibold tabular-nums ${getBadgeClasses(item.tone)}`}
              >
                {item.badge}
              </span>
            ) : null}
          </button>
        ))}
      </div>
    </section>
  );
}

function ProgressFraction({ complete, total }: { complete: number; total: number }) {
  const color = getProgressColor((complete / total) * 100);

  return (
    <span className="ml-auto flex shrink-0 items-baseline text-[11px] font-semibold tabular-nums">
      <span className="min-w-[2ch] text-right" style={{ color: asRgb(color, 1) }}>
        {complete}
      </span>
      <span className="px-0.5 text-ctp-overlay1">/</span>
      <span className="min-w-[2ch] text-left text-ctp-subtext0">{total}</span>
    </span>
  );
}

function Topbar({ onConfigureSync, view }: { onConfigureSync: () => void; view: ViewConfig }) {
  const queryClient = useQueryClient();
  const playlistDetailQuery = usePlaylistDetailQuery(view.playlistResourceId ?? null);
  const playlist = playlistDetailQuery.data?.playlist;
  const exportMutation = useMutation({
    mutationFn: exportPlaylistM3u,
    onSuccess: ({ blob, filename }) => {
      downloadBlob(blob, filename);
    },
  });
  const syncMutation = useMutation({
    mutationFn: syncStreamingAccount,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["playlists"] });
      if (view.playlistResourceId !== undefined) {
        await queryClient.invalidateQueries({ queryKey: ["playlists", view.playlistResourceId] });
      }
    },
  });

  function renderActionButton(actionLabel: string) {
    if (actionLabel === "Sync") {
      const canSync = playlist !== undefined && !syncMutation.isPending;

      return (
        <button
          aria-live="polite"
          className="rounded-[10px] border border-ctp-surface1 bg-ctp-surface0 px-3 py-1.5 text-[12px] font-semibold text-ctp-text transition-colors hover:border-ctp-overlay0 hover:bg-ctp-surface1 disabled:cursor-not-allowed disabled:border-ctp-surface0 disabled:text-ctp-overlay1 disabled:hover:bg-ctp-surface0"
          disabled={!canSync}
          key={actionLabel}
          onClick={() => {
            if (playlist) {
              syncMutation.mutate(playlist.account_id);
            }
          }}
          type="button"
        >
          {syncMutation.isPending ? "Syncing..." : actionLabel}
        </button>
      );
    }

    if (actionLabel === "Export M3U") {
      const canExport = view.playlistResourceId !== undefined && !exportMutation.isPending;

      return (
        <button
          aria-live="polite"
          className="rounded-[10px] border border-ctp-surface1 bg-ctp-surface0 px-3 py-1.5 text-[12px] font-semibold text-ctp-text transition-colors hover:border-ctp-overlay0 hover:bg-ctp-surface1 disabled:cursor-not-allowed disabled:border-ctp-surface0 disabled:text-ctp-overlay1 disabled:hover:bg-ctp-surface0"
          disabled={!canExport}
          key={actionLabel}
          onClick={() => {
            if (view.playlistResourceId !== undefined) {
              exportMutation.mutate(view.playlistResourceId);
            }
          }}
          type="button"
        >
          {exportMutation.isPending ? "Exporting..." : actionLabel}
        </button>
      );
    }

    return (
      <button
        key={actionLabel}
        className="rounded-[10px] border border-ctp-surface1 bg-ctp-surface0 px-3 py-1.5 text-[12px] font-semibold text-ctp-text transition-colors hover:border-ctp-overlay0 hover:bg-ctp-surface1"
        type="button"
      >
        {actionLabel}
      </button>
    );
  }

  return (
    <header className="flex h-11 items-center justify-between border-b border-ctp-surface0 bg-ctp-mantle px-5">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-ctp-surface0 text-ctp-mauve">
          <TopbarIcon icon={view.icon} />
        </span>
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="truncate text-[15px] font-semibold text-ctp-text">{view.title}</h1>
          <span
            className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] ${getTopbarPillClasses(view.pillTone)}`}
          >
            {view.pillLabel}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {syncMutation.isSuccess ? <span className="text-[11px] font-medium text-ctp-green">Sync queued.</span> : null}
        {syncMutation.isError ? <span className="text-[11px] font-medium text-ctp-red">Sync failed.</span> : null}
        {exportMutation.isSuccess ? <span className="text-[11px] font-medium text-ctp-green">M3U ready.</span> : null}
        {exportMutation.isError ? <span className="text-[11px] font-medium text-ctp-red">Export failed.</span> : null}
        {view.id !== playlistCollectionViewId ? (
          <button
            className="rounded-[10px] border border-ctp-surface1 bg-ctp-surface0 px-3 py-1.5 text-[12px] font-semibold text-ctp-text transition-colors hover:border-ctp-overlay0 hover:bg-ctp-surface1"
            onClick={onConfigureSync}
            type="button"
          >
            Configure sync
          </button>
        ) : null}
        {view.actionLabels.map((actionLabel) => renderActionButton(actionLabel))}
      </div>
    </header>
  );
}

function SearchPanel() {
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query.trim(), 250);
  const hasQuery = debouncedQuery.length > 0;
  const { data, error, isFetching } = useQuery({
    queryKey: ["sidebar-search", debouncedQuery],
    queryFn: () => fetchSearchResults(debouncedQuery),
    enabled: hasQuery,
    retry: false,
  });

  const results = data?.results ?? [];
  const isOpen = query.trim().length > 0;

  return (
    <div className="relative">
      <label className="sr-only" htmlFor="sidebar-search">
        Search library
      </label>
      <div className="flex items-center gap-2 rounded-[10px] bg-ctp-surface0 px-3 py-2.5 text-ctp-subtext0 ring-1 ring-inset ring-ctp-surface1/70 focus-within:text-ctp-text focus-within:ring-ctp-overlay0">
        <svg aria-hidden="true" className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24">
          <path
            d="m21 21-4.35-4.35m1.85-5.15a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z"
            stroke="currentColor"
            strokeLinecap="round"
            strokeWidth="1.8"
          />
        </svg>
        <input
          autoComplete="off"
          className="w-full border-0 bg-transparent p-0 text-[13px] text-ctp-text outline-none placeholder:text-ctp-subtext0"
          id="sidebar-search"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search tracks, artists, playlists"
          type="search"
          value={query}
        />
      </div>

      {isOpen ? (
        <div className="absolute inset-x-0 top-[calc(100%+0.5rem)] z-10 overflow-hidden rounded-[12px] border border-ctp-surface1 bg-ctp-mantle shadow-[0_20px_48px_color-mix(in_srgb,var(--color-ctp-crust)_38%,transparent)]">
          {isFetching ? (
            <p className="px-3 py-3 text-[12px] text-ctp-subtext0">Searching library…</p>
          ) : null}

          {!isFetching && error ? (
            <p className="px-3 py-3 text-[12px] text-ctp-red">Search unavailable right now.</p>
          ) : null}

          {!isFetching && !error && hasQuery && results.length === 0 ? (
            <p className="px-3 py-3 text-[12px] text-ctp-subtext0">No matching playlists or tracks.</p>
          ) : null}

          {!isFetching && !error && results.length > 0 ? (
            <div className="py-1.5">
              {results.map((result) => (
                <button
                  key={`${result.kind}-${result.id}`}
                  className="flex w-full items-start gap-3 px-3 py-2.5 text-left transition-colors hover:bg-ctp-surface0/80"
                  type="button"
                >
                  <span className="mt-0.5 rounded-full bg-ctp-surface0 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-ctp-subtext0 ring-1 ring-inset ring-ctp-surface1/70">
                    {searchKindLabels[result.kind]}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12px] font-semibold text-ctp-text">
                      {result.title}
                    </span>
                    <span className="mt-1 block truncate text-[11px] text-ctp-subtext0">
                      {result.subtitle}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function PlaylistView({ isActive, playlistResourceId }: { isActive: boolean; playlistResourceId: number }) {
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
      <section className="rounded-[30px] border border-ctp-surface1/80 bg-ctp-mantle px-6 py-6 text-[13px] text-ctp-subtext0">
        Loading playlist overview…
      </section>
    );
  }

  if (playlistDetailQuery.isError || playlistTracksQuery.isError) {
    return (
      <section className="rounded-[30px] border border-ctp-red/30 bg-ctp-surface0/60 px-6 py-6 text-[13px] text-ctp-red">
        Playlist overview is unavailable right now.
      </section>
    );
  }

  if (!playlistDetailQuery.data) {
    return null;
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-5">
      <PlaylistHeader playlist={playlistDetailQuery.data.playlist} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <FilterChips activeFilter={activeFilter} counts={filterCounts} onFilterChange={setActiveFilter} />
        <p className="text-[12px] font-medium text-ctp-subtext0">
          Showing {filteredTracks.length} of {tracks.length} tracks
        </p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
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
          <div className="rounded-[24px] border border-ctp-surface1/80 bg-ctp-mantle px-5 py-6 text-[13px] text-ctp-subtext0">
            No tracks match this filter.
          </div>
        )}
      </div>
    </section>
  );
}

function PlaylistCollectionState({ status }: { status: PlaylistCollectionStatus }) {
  const copy = {
    empty: {
      title: "No synced playlists",
      body: "Sync a YouTube Music account to review playlist metadata, track matches, and M3U exports here.",
    },
    error: {
      title: "Playlists unavailable",
      body: "The synced playlist list could not be loaded. Try again after the backend is reachable.",
    },
    loading: {
      title: "Loading playlists",
      body: "Checking for synced YouTube Music playlists.",
    },
    ready: {
      title: "Playlist sync configuration",
      body: "Review discovered YouTube Music playlists and choose which ones appear in the sync queue.",
    },
  } satisfies Record<PlaylistCollectionStatus, { body: string; title: string }>;

  return (
    <section className="flex min-h-0 flex-1 items-center justify-center">
      <div className="max-w-[420px] rounded-[24px] border border-ctp-surface1/80 bg-ctp-mantle px-6 py-7 text-center">
        <h2 className="text-[18px] font-semibold text-ctp-text">{copy[status].title}</h2>
        <p className="mt-2 text-[13px] leading-6 text-ctp-subtext0">{copy[status].body}</p>
      </div>
    </section>
  );
}

function PlaylistActionStatus({
  errorText,
  isError,
  isPending,
  isSuccess,
  pendingText,
  successText,
}: {
  errorText: string;
  isError: boolean;
  isPending: boolean;
  isSuccess: boolean;
  pendingText: string;
  successText: string;
}) {
  if (isPending) {
    return (
      <p className="text-[12px] font-medium text-ctp-yellow" role="status">
        {pendingText}
      </p>
    );
  }

  if (isError) {
    return (
      <p className="text-[12px] font-medium text-ctp-red" role="alert">
        {errorText}
      </p>
    );
  }

  if (isSuccess) {
    return (
      <p className="text-[12px] font-medium text-ctp-green" role="status">
        {successText}
      </p>
    );
  }

  return null;
}

function PlaylistSyncToggle({
  isPending,
  onToggle,
  playlist,
}: {
  isPending: boolean;
  onToggle: (selectedForSync: boolean) => void;
  playlist: StreamingPlaylistConfig;
}) {
  return (
    <label className="inline-flex shrink-0 items-center gap-2 text-[12px] font-semibold text-ctp-subtext0">
      <input
        aria-label={`Select ${playlist.title} for sync`}
        checked={playlist.selected_for_sync}
        className="h-4 w-4 rounded border-ctp-surface1 bg-ctp-surface0 text-ctp-mauve accent-ctp-mauve"
        disabled={isPending}
        onChange={(event) => onToggle(event.target.checked)}
        type="checkbox"
      />
      {isPending ? "Updating..." : playlist.selected_for_sync ? "Selected" : "Not selected"}
    </label>
  );
}

function PlaylistConfigRow({
  isTogglePending,
  onTogglePlaylist,
  playlist,
}: {
  isTogglePending: boolean;
  onTogglePlaylist: (playlist: StreamingPlaylistConfig, selectedForSync: boolean) => void;
  playlist: StreamingPlaylistConfig;
}) {
  return (
    <article className="rounded-[18px] border border-ctp-surface1/80 bg-ctp-mantle px-5 py-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="truncate text-[15px] font-semibold text-ctp-text">{playlist.title}</h3>
          <p className="mt-1 text-[12px] text-ctp-subtext0">
            Provider ID {playlist.provider_playlist_id} / Account {playlist.account_id}
          </p>
        </div>
        <PlaylistSyncToggle
          isPending={isTogglePending}
          onToggle={(selectedForSync) => onTogglePlaylist(playlist, selectedForSync)}
          playlist={playlist}
        />
      </div>

      <dl className="mt-4 grid gap-3 text-[12px] sm:grid-cols-3">
        <div>
          <dt className="font-medium text-ctp-subtext0">Tracks</dt>
          <dd className="mt-1 font-semibold tabular-nums text-ctp-text">{playlist.track_count}</dd>
        </div>
        <div>
          <dt className="font-medium text-ctp-subtext0">Last metadata sync</dt>
          <dd className="mt-1 font-semibold text-ctp-text">{formatPlaylistTimestamp(playlist.synced_at)}</dd>
        </div>
        <div>
          <dt className="font-medium text-ctp-subtext0">Last sync error</dt>
          <dd className={playlist.last_sync_error ? "mt-1 font-semibold text-ctp-red" : "mt-1 font-semibold text-ctp-green"}>
            {playlist.last_sync_error ?? "None"}
          </dd>
        </div>
      </dl>
    </article>
  );
}

function PlaylistSyncConfiguration() {
  const queryClient = useQueryClient();
  const configQuery = useStreamingPlaylistConfigQuery();
  const selectedSyncMutation = useMutation({
    mutationFn: syncStreamingAccount,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.list() }),
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.config() }),
      ]);
    },
  });
  const metadataRefreshMutation = useMutation({
    mutationFn: refreshStreamingAccountMetadata,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.list() }),
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.config() }),
      ]);
    },
  });
  const toggleMutation = useMutation({
    mutationFn: updateStreamingPlaylistConfig,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.list() }),
        queryClient.invalidateQueries({ queryKey: playlistQueryKeys.config() }),
      ]);
    },
  });
  const playlists = configQuery.data?.playlists ?? [];
  const selectedCount = getSelectedPlaylistCount(playlists);
  const accountId = playlists[0]?.account_id;

  if (configQuery.isPending) {
    return <PlaylistCollectionState status="loading" />;
  }

  if (configQuery.isError) {
    return <PlaylistCollectionState status="error" />;
  }

  if (playlists.length === 0) {
    return <PlaylistCollectionState status="empty" />;
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-[18px] font-semibold text-ctp-text">Playlist sync configuration</h2>
          <p className="mt-1 text-[13px] text-ctp-subtext0">
            {selectedCount} of {playlists.length} discovered playlists selected for sync.
          </p>
        </div>
        <div className="flex flex-col items-start gap-2 sm:items-end">
          <div className="flex flex-wrap justify-start gap-2 sm:justify-end">
            <button
              className="rounded-[10px] border border-ctp-surface1 bg-ctp-surface0 px-3 py-1.5 text-[12px] font-semibold text-ctp-text transition-colors hover:border-ctp-overlay0 hover:bg-ctp-surface1 disabled:cursor-not-allowed disabled:border-ctp-surface0 disabled:text-ctp-overlay1 disabled:hover:bg-ctp-surface0"
              disabled={accountId === undefined || selectedCount === 0 || selectedSyncMutation.isPending}
              onClick={() => {
                if (accountId !== undefined) {
                  selectedSyncMutation.mutate(accountId);
                }
              }}
              type="button"
            >
              {selectedSyncMutation.isPending ? "Syncing selected..." : "Sync selected"}
            </button>
            <button
              className="rounded-[10px] border border-ctp-surface1 bg-ctp-surface0 px-3 py-1.5 text-[12px] font-semibold text-ctp-text transition-colors hover:border-ctp-overlay0 hover:bg-ctp-surface1 disabled:cursor-not-allowed disabled:border-ctp-surface0 disabled:text-ctp-overlay1 disabled:hover:bg-ctp-surface0"
              disabled={accountId === undefined || metadataRefreshMutation.isPending}
              onClick={() => {
                if (accountId !== undefined) {
                  metadataRefreshMutation.mutate(accountId);
                }
              }}
              type="button"
            >
              {metadataRefreshMutation.isPending ? "Refreshing..." : "Refresh playlist metadata"}
            </button>
          </div>
          <PlaylistActionStatus
            errorText="Selected playlist sync failed."
            isError={selectedSyncMutation.isError}
            isPending={selectedSyncMutation.isPending}
            isSuccess={selectedSyncMutation.isSuccess}
            pendingText="Syncing selected playlists..."
            successText="Selected playlist sync queued."
          />
          <PlaylistActionStatus
            errorText="Metadata refresh failed."
            isError={metadataRefreshMutation.isError}
            isPending={metadataRefreshMutation.isPending}
            isSuccess={metadataRefreshMutation.isSuccess}
            pendingText="Refreshing playlist metadata..."
            successText="Metadata refresh queued."
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="space-y-3">
          {playlists.map((playlist) => (
            <PlaylistConfigRow
              isTogglePending={toggleMutation.isPending && toggleMutation.variables?.playlistId === playlist.id}
              key={playlist.id}
              onTogglePlaylist={(playlistToUpdate, selectedForSync) =>
                toggleMutation.mutate({
                  playlistId: playlistToUpdate.id,
                  selected_for_sync: selectedForSync,
                })
              }
              playlist={playlist}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

function ViewShell({
  activeViewId,
  playlistResourceId,
  viewId,
}: {
  activeViewId: string;
  playlistResourceId?: number;
  viewId: string;
}) {
  const isActive = activeViewId === viewId;

  return (
    <div
      aria-hidden={!isActive}
      className={isActive ? "flex flex-1 flex-col overflow-y-auto" : "hidden"}
      data-view-active={isActive ? "true" : "false"}
      id={viewId}
    >
      {isActive ? (
        <div className="flex min-h-0 flex-1 flex-col p-6">
          {playlistResourceId !== undefined ? (
            <PlaylistView isActive={isActive} playlistResourceId={playlistResourceId} />
          ) : viewId === playlistCollectionViewId ? (
            <PlaylistSyncConfiguration />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function App() {
  const [activeViewId, setActiveViewId] = useState(playlistCollectionViewId);
  const [hasUserSelectedView, setHasUserSelectedView] = useState(false);
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
      : "No synced playlists found.";

  useEffect(() => {
    if (playlistsQuery.isPending) {
      return;
    }

    if (!hasUserSelectedView || viewConfigById[activeViewId] === undefined) {
      setActiveViewId(defaultPlaylistViewId);
    }
  }, [activeViewId, defaultPlaylistViewId, hasUserSelectedView, playlistsQuery.isPending, viewConfigById]);

  function handleViewSelect(viewId: string) {
    setHasUserSelectedView(true);
    setActiveViewId(viewId);
  }

  return (
    <div className="flex flex-1 flex-row overflow-hidden bg-ctp-base text-ctp-text">
      <aside className="flex w-[220px] shrink-0 flex-col border-r border-ctp-surface0 bg-ctp-mantle">
          <div className="border-b border-ctp-surface0 px-5 py-5">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-[12px] bg-ctp-surface0 text-ctp-mauve">
                <svg
                  aria-hidden="true"
                  className="h-5 w-5"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <path
                    d="M5 16.5V7.5l7-4 7 4v9l-7 4-7-4Z"
                    stroke="currentColor"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="1.7"
                  />
                  <path
                    d="m9 10 3 1.75L15 10m-3 1.75V17"
                    stroke="currentColor"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="1.7"
                  />
                </svg>
              </div>
              <div>
                <p className="font-display text-[11px] font-bold uppercase tracking-[0.32em] text-ctp-mauve">
                  MUSEBRIDGE
                </p>
                <p className="mt-1 text-[12px] text-ctp-subtext0">Playlist linking control room</p>
              </div>
            </div>
          </div>

          <div className="border-b border-ctp-surface0 px-4 py-4">
            <SearchPanel />
          </div>

          <div className="flex-1 space-y-6 overflow-y-auto px-0 py-5">
            <SidebarSection
              activeItemId={activeViewId}
              items={maintenanceItems}
              onSelect={handleViewSelect}
              title="Maintenance"
            />
            <SidebarSection
              activeItemId={activeViewId}
              emptyMessage={playlistEmptyMessage}
              items={playlistItems}
              onSelect={handleViewSelect}
              title="YouTube Music"
            />
            <SidebarSection
              activeItemId={activeViewId}
              items={libraryItems}
              onSelect={handleViewSelect}
              title="Local Library"
            />
          </div>
        </aside>

        <main className="flex flex-1 flex-col bg-ctp-base">
          <Topbar onConfigureSync={() => handleViewSelect(playlistCollectionViewId)} view={activeView} />
          <div className="flex flex-1 flex-col">
            {viewShellIds.map((viewId) => (
              <ViewShell
                key={viewId}
                activeViewId={activeViewId}
                playlistResourceId={viewConfigById[viewId].playlistResourceId}
                viewId={viewId}
              />
            ))}
          </div>
        </main>
    </div>
  );
}

export default App;
