import { useEffect, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { Package, Search } from "lucide-react";
import { ActionButton } from "../../components/ActionButton";
import { controlClasses, shellClasses, surfaceClasses, textClasses } from "../../styles/componentClasses";
import { pillToneClasses } from "../../styles/toneClasses";
import { getProgressColor } from "./progress";
import type { NavItem, SearchResponse, SearchResult } from "./types";

async function fetchSearchResults(query: string) {
  const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);

  if (!response.ok) {
    throw new Error(`Search request failed with status ${response.status}`);
  }

  return (await response.json()) as SearchResponse;
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

function getBadgeClasses(tone: NavItem["tone"]) {
  switch (tone) {
    case "pending":
      return pillToneClasses.pending;
    case "alert":
      return pillToneClasses.danger;
    case "accent":
      return pillToneClasses.accent;
    case "linked":
      return pillToneClasses.success;
    case "unlinked":
      return pillToneClasses.neutral;
  }
}

function ProgressFraction({ complete, total }: { complete: number; total: number }) {
  const color = getProgressColor((complete / total) * 100);
  const progressColorStyle: CSSProperties & Record<"--progress-color", string> = {
    "--progress-color": color,
  };

  return (
    <span className="ml-auto flex shrink-0 items-baseline text-[11px] font-semibold tabular-nums">
      <span className="min-w-[2ch] text-right text-[var(--progress-color)]" style={progressColorStyle}>
        {complete}
      </span>
      <span className="px-0.5 text-ctp-overlay1">/</span>
      <span className="min-w-[2ch] text-left text-ctp-subtext0">{total}</span>
    </span>
  );
}

function SidebarSection({
  activeItemId,
  emptyActionLabel,
  emptyMessage,
  items,
  onEmptyAction,
  onSelect,
  title,
}: {
  activeItemId: string;
  emptyActionLabel?: string;
  emptyMessage?: string;
  items: NavItem[];
  onEmptyAction?: () => void;
  onSelect: (itemId: string) => void;
  title: string;
}) {
  return (
    <section className={shellClasses.navSection}>
      <h2 className={`${shellClasses.navSectionTitle} ${textClasses.eyebrow} text-ctp-subtext0`}>
        {title}
      </h2>
      <div className={shellClasses.navStack}>
        {items.length === 0 && emptyMessage ? (
          <div className="space-y-2 px-3.5 py-2">
            <p className={textClasses.bodyMutedRelaxed}>{emptyMessage}</p>
            {emptyActionLabel && onEmptyAction ? (
              <ActionButton className={controlClasses.actionButtonCompact} onClick={onEmptyAction}>
                {emptyActionLabel}
              </ActionButton>
            ) : null}
          </div>
        ) : null}
        {items.map((item) => (
          <button
            key={item.id}
            className={`${shellClasses.navItem} ${
              item.id === activeItemId ? "bg-ctp-surface0 text-ctp-text" : "text-ctp-subtext1"
            }`}
            onClick={() => onSelect(item.id)}
            type="button"
          >
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
              {item.label}
            </span>
            {item.progress ? (
              <ProgressFraction complete={item.progress.complete} total={item.progress.total} />
            ) : null}
            {item.badge ? (
              <span className={`tabular-nums ${controlClasses.pill} ${shellClasses.navBadge} ${getBadgeClasses(item.tone)}`}>
                {item.badge}
              </span>
            ) : null}
          </button>
        ))}
      </div>
    </section>
  );
}

const searchKindLabels: Record<SearchResult["kind"], string> = {
  playlist: "Playlist",
  streaming_track: "Streaming",
  local_track: "Local",
};

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
      <div className={`flex items-center gap-2 text-ctp-subtext0 ${shellClasses.searchField} ${controlClasses.searchFrame}`}>
        <Search aria-hidden="true" className="h-4 w-4 shrink-0" strokeWidth={1.8} />
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
        <div className={`absolute inset-x-0 top-[calc(100%+0.5rem)] z-10 overflow-hidden ${surfaceClasses.popover}`}>
          {isFetching ? (
            <p className="px-3 py-3 text-[12px] text-ctp-subtext0">Searching library...</p>
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

export function Sidebar({
  activeItemId,
  libraryItems,
  maintenanceItems,
  onConfigureSync,
  onSelect,
  playlistEmptyActionLabel,
  playlistEmptyMessage,
  playlistItems,
}: {
  activeItemId: string;
  libraryItems: NavItem[];
  maintenanceItems: NavItem[];
  onConfigureSync: () => void;
  onSelect: (itemId: string) => void;
  playlistEmptyActionLabel?: string;
  playlistEmptyMessage: string;
  playlistItems: NavItem[];
}) {
  return (
    <aside className={shellClasses.sidebar}>
      <div className={shellClasses.sidebarHeader}>
        <div className="flex items-center gap-2.5">
          <div className={shellClasses.sidebarLogo}>
            <Package aria-hidden="true" className="h-4 w-4" strokeWidth={1.7} />
          </div>
          <div>
            <p className="font-display text-[10px] font-bold uppercase tracking-[0.26em] text-ctp-mauve">
              MUSEBRIDGE
            </p>
            <p className="mt-0.5 text-[11px] text-ctp-subtext0">Playlist linking control room</p>
          </div>
        </div>
      </div>

      <div className={shellClasses.sidebarSearch}>
        <SearchPanel />
      </div>

      <div className={shellClasses.sidebarBody}>
        <SidebarSection activeItemId={activeItemId} items={maintenanceItems} onSelect={onSelect} title="Maintenance" />
        <SidebarSection
          activeItemId={activeItemId}
          emptyActionLabel={playlistEmptyActionLabel}
          emptyMessage={playlistEmptyMessage}
          items={playlistItems}
          onEmptyAction={onConfigureSync}
          onSelect={onSelect}
          title="YouTube Music"
        />
        <SidebarSection activeItemId={activeItemId} items={libraryItems} onSelect={onSelect} title="Local Library" />
      </div>
    </aside>
  );
}
