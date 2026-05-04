import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ActionButton } from "../../components/ActionButton";
import { pillToneClasses } from "../../styles/toneClasses";
import { asRgb, getProgressColor } from "./progress";
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
    <section className="space-y-3">
      <h2 className="px-4 text-[11px] font-semibold uppercase tracking-[0.24em] text-ctp-subtext0">
        {title}
      </h2>
      <div className="space-y-1.5">
        {items.length === 0 && emptyMessage ? (
          <div className="space-y-2 px-4 py-2.5">
            <p className="text-[12px] leading-5 text-ctp-subtext0">{emptyMessage}</p>
            {emptyActionLabel && onEmptyAction ? (
              <ActionButton onClick={onEmptyAction}>
                {emptyActionLabel}
              </ActionButton>
            ) : null}
          </div>
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
    <aside className="flex min-h-0 w-[220px] shrink-0 flex-col border-r border-ctp-surface0 bg-ctp-mantle">
      <div className="border-b border-ctp-surface0 px-5 py-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-[12px] bg-ctp-surface0 text-ctp-mauve">
            <svg aria-hidden="true" className="h-5 w-5" fill="none" viewBox="0 0 24 24">
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
