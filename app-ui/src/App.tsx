/* eslint-disable react-refresh/only-export-components */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PlaylistHeader } from "./features/playlists/PlaylistHeader";
import { usePlaylistDetailQuery } from "./features/playlists/queries";

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

const maintenanceItems: NavItem[] = [
  { id: "proposals", label: "Link proposals", badge: 14, tone: "pending" },
  { id: "unidentified", label: "Unidentified", badge: 3, tone: "alert" },
  { id: "missing", label: "Missing locally", badge: 28, tone: "accent" },
];

const playlistItems: NavItem[] = [
  { id: "playlist", label: "Late Night Drive", progress: { complete: 58, total: 62 }, tone: "linked" },
  { id: "playlist2", label: "Static Bloom", progress: { complete: 24, total: 41 }, tone: "pending" },
  { id: "playlist3", label: "Afterglow", progress: { complete: 19, total: 36 }, tone: "pending" },
  { id: "playlist4", label: "Signal Loss", progress: { complete: 11, total: 29 }, tone: "unlinked" },
  { id: "playlist5", label: "Chrome Hearts", progress: { complete: 33, total: 54 }, tone: "linked" },
];

const libraryItems: NavItem[] = [
  { id: "library", label: "All tracks", badge: 312, tone: "accent" },
];

const viewConfigs = [
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
    id: "playlist",
    title: "Late Night Drive",
    pillLabel: "YouTube Music",
    pillTone: "pill-info",
    playlistResourceId: 12,
    actionLabels: ["Sync", "Export M3U"],
    icon: "playlist",
  },
  {
    id: "playlist2",
    title: "Static Bloom",
    pillLabel: "YouTube Music",
    pillTone: "pill-info",
    playlistResourceId: 9,
    actionLabels: ["Sync", "Export M3U"],
    icon: "playlist",
  },
  {
    id: "playlist3",
    title: "Afterglow",
    pillLabel: "YouTube Music",
    pillTone: "pill-info",
    playlistResourceId: 14,
    actionLabels: ["Sync", "Export M3U"],
    icon: "playlist",
  },
  {
    id: "playlist4",
    title: "Signal Loss",
    pillLabel: "YouTube Music",
    pillTone: "pill-info",
    playlistResourceId: 18,
    actionLabels: ["Sync", "Export M3U"],
    icon: "playlist",
  },
  {
    id: "playlist5",
    title: "Chrome Hearts",
    pillLabel: "YouTube Music",
    pillTone: "pill-info",
    playlistResourceId: 27,
    actionLabels: ["Sync", "Export M3U"],
    icon: "playlist",
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

const viewConfigById = Object.fromEntries(viewConfigs.map((view) => [view.id, view])) as Record<
  ViewConfig["id"],
  ViewConfig
>;

const viewShellIds = [
  "proposals",
  "unidentified",
  "missing",
  "playlist",
  "playlist2",
  "playlist3",
  "playlist4",
  "playlist5",
  "library",
] satisfies ViewConfig["id"][];

const searchKindLabels: Record<SearchResult["kind"], string> = {
  playlist: "Playlist",
  streaming_track: "Streaming",
  local_track: "Local",
};

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
  items,
  onSelect,
  title,
}: {
  activeItemId: string;
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

function Topbar({ view }: { view: ViewConfig }) {
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
        {view.actionLabels.map((actionLabel) => (
          <button
            key={actionLabel}
            className="rounded-[10px] border border-ctp-surface1 bg-ctp-surface0 px-3 py-1.5 text-[12px] font-semibold text-ctp-text transition-colors hover:border-ctp-overlay0 hover:bg-ctp-surface1"
            type="button"
          >
            {actionLabel}
          </button>
        ))}
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
        <div className="absolute inset-x-0 top-[calc(100%+0.5rem)] z-10 overflow-hidden rounded-[12px] border border-ctp-surface1 bg-ctp-mantle shadow-[0_20px_48px_rgba(17,17,27,0.38)]">
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

function ViewShell({
  activeViewId,
  playlistResourceId,
  viewId,
}: {
  activeViewId: ViewConfig["id"];
  playlistResourceId?: number;
  viewId: ViewConfig["id"];
}) {
  const isActive = activeViewId === viewId;
  const playlistDetailQuery = usePlaylistDetailQuery(isActive ? playlistResourceId : null);

  let content = null;

  if (playlistResourceId !== undefined) {
    if (playlistDetailQuery.isPending) {
      content = (
        <section className="rounded-[30px] border border-ctp-surface1/80 bg-ctp-mantle px-6 py-6 text-[13px] text-ctp-subtext0">
          Loading playlist overview…
        </section>
      );
    } else if (playlistDetailQuery.isError) {
      content = (
        <section className="rounded-[30px] border border-ctp-red/30 bg-ctp-surface0/60 px-6 py-6 text-[13px] text-ctp-red">
          Playlist overview is unavailable right now.
        </section>
      );
    } else if (playlistDetailQuery.data) {
      content = <PlaylistHeader playlist={playlistDetailQuery.data.playlist} />;
    }
  }

  return (
    <div
      aria-hidden={!isActive}
      className={isActive ? "flex flex-1 flex-col overflow-y-auto" : "hidden"}
      data-view-active={isActive ? "true" : "false"}
      id={viewId}
    >
      {isActive ? <div className="flex flex-1 flex-col p-6">{content}</div> : null}
    </div>
  );
}

function App() {
  const [activeViewId, setActiveViewId] = useState<ViewConfig["id"]>("proposals");
  const activeView = viewConfigById[activeViewId];

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
              onSelect={setActiveViewId}
              title="Maintenance"
            />
            <SidebarSection
              activeItemId={activeViewId}
              items={playlistItems}
              onSelect={setActiveViewId}
              title="YouTube Music"
            />
            <SidebarSection
              activeItemId={activeViewId}
              items={libraryItems}
              onSelect={setActiveViewId}
              title="Local Library"
            />
          </div>
        </aside>

        <main className="flex flex-1 flex-col bg-ctp-base">
          <Topbar view={activeView} />
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
