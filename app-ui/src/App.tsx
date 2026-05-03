/* eslint-disable react-refresh/only-export-components */

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

const maintenanceItems: NavItem[] = [
  { id: "proposals", label: "Link proposals", badge: 14, tone: "pending" },
  { id: "unidentified", label: "Unidentified", badge: 3, tone: "alert" },
  { id: "missing", label: "Missing locally", badge: 28, tone: "accent" },
];

const playlistItems: NavItem[] = [
  { id: "playlist1", label: "Late Night Drive", progress: { complete: 58, total: 62 }, tone: "linked" },
  { id: "playlist2", label: "Static Bloom", progress: { complete: 24, total: 41 }, tone: "pending" },
  { id: "playlist3", label: "Afterglow", progress: { complete: 19, total: 36 }, tone: "pending" },
  { id: "playlist4", label: "Signal Loss", progress: { complete: 11, total: 29 }, tone: "unlinked" },
  { id: "playlist5", label: "Chrome Hearts", progress: { complete: 33, total: 54 }, tone: "linked" },
];

const libraryItems: NavItem[] = [
  { id: "library", label: "All tracks", badge: 312, tone: "accent" },
];

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

function SidebarSection({
  items,
  title,
}: {
  items: NavItem[];
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
            className="flex w-full items-center gap-3 rounded-[10px] px-4 py-2.5 text-left transition-colors hover:bg-ctp-surface0/80"
            type="button"
          >
            <span className="min-w-0 flex-1 truncate text-[14px] font-medium text-ctp-text">
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

function App() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-transparent px-6 py-10 text-ctp-text">
      <div
        className="flex h-[640px] w-full max-w-[1280px] flex-row overflow-hidden rounded-[12px] border border-ctp-surface0 bg-ctp-base shadow-[0_32px_120px_rgba(17,17,27,0.45)]"
      >
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
            <label className="sr-only" htmlFor="sidebar-search">
              Search library
            </label>
            <div className="flex items-center gap-2 rounded-[10px] bg-ctp-surface0 px-3 py-2.5 text-ctp-subtext0">
              <svg aria-hidden="true" className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24">
                <path
                  d="m21 21-4.35-4.35m1.85-5.15a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeWidth="1.8"
                />
              </svg>
              <input
                className="w-full border-0 bg-transparent p-0 text-[13px] text-ctp-text outline-none placeholder:text-ctp-subtext0"
                id="sidebar-search"
                placeholder="Search tracks, artists, playlists"
                type="search"
              />
            </div>
          </div>

          <div className="flex-1 space-y-6 overflow-y-auto px-0 py-5">
            <SidebarSection items={maintenanceItems} title="Maintenance" />
            <SidebarSection items={playlistItems} title="YouTube Music" />
            <SidebarSection items={libraryItems} title="Local Library" />
          </div>
        </aside>

        <main className="flex-1 bg-ctp-base" />
      </div>
    </div>
  );
}

export default App;
