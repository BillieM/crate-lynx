import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";

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

type AppRoute = {
  description: string;
  heading: string;
  kicker: string;
  path: string;
  progressExamples: Array<{
    label: string;
    matchPercentage: number;
    status: ProgressStatus;
  }>;
  section: string;
  stats: Array<{
    label: string;
    value: string;
  }>;
};

type ProgressStatus = "unlinked" | "pending" | "linked";

type RgbColor = {
  blue: number;
  green: number;
  red: number;
};

const progressPalette = {
  linked: { red: 166, green: 227, blue: 161 },
  pending: { red: 249, green: 226, blue: 175 },
  unlinked: { red: 108, green: 112, blue: 134 },
} satisfies Record<ProgressStatus, RgbColor>;

const appRoutes: AppRoute[] = [
  {
    path: "/maintenance",
    section: "Maintenance",
    kicker: "Operations",
    heading: "Keep ingestion and recovery moving.",
    description:
      "Track importer health, re-run background jobs, and clear operational issues before they turn into stale playlists.",
    progressExamples: [
      { label: "Rescue queue", matchPercentage: 18, status: "unlinked" },
      { label: "Import recovery", matchPercentage: 54, status: "pending" },
      { label: "Retry sweep", matchPercentage: 92, status: "linked" },
    ],
    stats: [
      { label: "Queue health", value: "Stable" },
      { label: "Failed imports", value: "03" },
      { label: "Rescue jobs", value: "11 pending" },
    ],
  },
  {
    path: "/youtube-music",
    section: "YouTube Music",
    kicker: "Streaming",
    heading: "Review sync status and playlist linkage.",
    description:
      "Follow playlist coverage, inspect match confidence, and keep the catalog aligned with the upstream YouTube Music library.",
    progressExamples: [
      { label: "Roadtrip mix", matchPercentage: 24, status: "unlinked" },
      { label: "Deep cuts sync", matchPercentage: 63, status: "pending" },
      { label: "Daily rotation", matchPercentage: 88, status: "linked" },
    ],
    stats: [
      { label: "Playlists synced", value: "18" },
      { label: "Pending links", value: "42" },
      { label: "Coverage", value: "81%" },
    ],
  },
  {
    path: "/local-library",
    section: "Local Library",
    kicker: "Collection",
    heading: "Manage your source-of-truth music archive.",
    description:
      "Inspect the local catalog, surface unmatched tracks, and prep metadata rescue work before generating exports.",
    progressExamples: [
      { label: "New arrivals", matchPercentage: 12, status: "unlinked" },
      { label: "Metadata rescue", matchPercentage: 57, status: "pending" },
      { label: "Archive export", matchPercentage: 95, status: "linked" },
    ],
    stats: [
      { label: "Tracks indexed", value: "6,482" },
      { label: "Linked cleanly", value: "5,973" },
      { label: "Needs review", value: "509" },
    ],
  },
];

function ShellNavLink({ path, section }: Pick<AppRoute, "path" | "section">) {
  return (
    <NavLink
      to={path}
      className={({ isActive }) =>
        [
          "group relative flex items-center justify-between overflow-hidden rounded-2xl border px-4 py-3 transition",
          isActive
            ? "border-ctp-sky/70 bg-ctp-sky/12 text-ctp-text shadow-lg shadow-ctp-crust/20"
            : "border-ctp-surface0/80 bg-ctp-base/40 text-ctp-subtext0 hover:border-ctp-surface1 hover:bg-ctp-surface0/35 hover:text-ctp-text",
        ].join(" ")
      }
    >
      {({ isActive }) => (
        <>
          <span className="text-sm font-semibold tracking-[0.18em] uppercase">
            {section}
          </span>
          <span
            aria-hidden="true"
            className={[
              "text-lg transition",
              isActive
                ? "translate-x-0 text-ctp-sky"
                : "-translate-x-1 text-ctp-overlay0 group-hover:translate-x-0 group-hover:text-ctp-text",
            ].join(" ")}
          >
            /
          </span>
        </>
      )}
    </NavLink>
  );
}

function clampPercentage(matchPercentage: number) {
  return Math.max(0, Math.min(100, matchPercentage));
}

function lerp(start: number, end: number, amount: number) {
  return Math.round(start + (end - start) * amount);
}

function mixColors(start: RgbColor, end: RgbColor, amount: number): RgbColor {
  return {
    red: lerp(start.red, end.red, amount),
    green: lerp(start.green, end.green, amount),
    blue: lerp(start.blue, end.blue, amount),
  };
}

function getProgressColor(matchPercentage: number): RgbColor {
  const normalized = clampPercentage(matchPercentage) / 100;

  if (normalized <= 0.5) {
    return mixColors(progressPalette.unlinked, progressPalette.pending, normalized / 0.5);
  }

  return mixColors(progressPalette.pending, progressPalette.linked, (normalized - 0.5) / 0.5);
}

function asRgb(color: RgbColor, alpha = 1) {
  return `rgba(${color.red}, ${color.green}, ${color.blue}, ${alpha})`;
}

function ProgressBubble({
  label,
  matchPercentage,
  status,
}: {
  label: string;
  matchPercentage: number;
  status: ProgressStatus;
}) {
  const percentage = clampPercentage(matchPercentage);
  const color = getProgressColor(percentage);

  return (
    <article
      aria-label={`${label}: ${status} at ${percentage}% match`}
      className="rounded-[1.5rem] border border-ctp-surface0/80 bg-ctp-mantle/70 p-5"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold tracking-[0.24em] uppercase text-ctp-subtext0">
            {label}
          </p>
          <p className="mt-3 text-sm leading-7 text-ctp-subtext1">
            Match confidence is currently {status}, with colour blended directly
            from the percentage score.
          </p>
        </div>

        <div
          aria-hidden="true"
          className="flex h-17 w-17 shrink-0 items-center justify-center rounded-full border text-center shadow-lg"
          style={{
            background: `radial-gradient(circle at 30% 30%, ${asRgb(color, 0.38)}, ${asRgb(color, 0.12)} 62%, rgba(24, 24, 37, 0.92) 100%)`,
            borderColor: asRgb(color, 0.55),
            boxShadow: `0 18px 40px ${asRgb(color, 0.2)}`,
          }}
        >
          <div>
            <p className="font-display text-xl font-semibold text-ctp-text">{percentage}%</p>
            <p
              className="text-[0.6rem] font-semibold tracking-[0.22em] uppercase"
              style={{ color: asRgb(color, 0.92) }}
            >
              {status}
            </p>
          </div>
        </div>
      </div>
    </article>
  );
}

function SectionView({
  description,
  heading,
  kicker,
  progressExamples,
  stats,
  section,
}: AppRoute) {
  return (
    <section className="space-y-8">
      <div className="relative overflow-hidden rounded-[2rem] border border-ctp-surface0/80 bg-[linear-gradient(135deg,rgba(137,180,250,0.14),rgba(30,30,46,0.9)_40%,rgba(17,17,27,0.96))] p-8 shadow-2xl shadow-ctp-crust/35 sm:p-10">
        <div className="absolute -right-12 top-0 h-40 w-40 rounded-full bg-ctp-sky/15 blur-3xl" />
        <div className="absolute bottom-[-4rem] left-[-2rem] h-44 w-44 rounded-full bg-ctp-teal/15 blur-3xl" />

        <div className="relative space-y-5">
          <p className="text-sm font-semibold tracking-[0.4em] uppercase text-ctp-sky">
            {kicker}
          </p>
          <div className="space-y-4">
            <h1 className="max-w-3xl font-display text-4xl font-bold tracking-tight text-ctp-rosewater sm:text-5xl">
              {heading}
            </h1>
            <p className="max-w-2xl text-lg leading-8 text-ctp-subtext1">
              {description}
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(18rem,0.85fr)]">
        <div className="rounded-[1.75rem] border border-ctp-surface0/80 bg-ctp-base/75 p-6 shadow-xl shadow-ctp-crust/20 backdrop-blur">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-2">
              <p className="text-sm font-semibold tracking-[0.32em] uppercase text-ctp-lavender">
                {section} workspace
              </p>
              <h2 className="font-display text-2xl font-semibold text-ctp-text">
                Main content area
              </h2>
            </div>
            <span className="rounded-full border border-ctp-surface1 bg-ctp-mantle/80 px-3 py-1 text-xs font-semibold tracking-[0.28em] uppercase text-ctp-subtext0">
              Shell scaffold
            </span>
          </div>

          <div className="mt-8 grid gap-4 md:grid-cols-2">
            <article className="rounded-[1.5rem] border border-ctp-surface0/80 bg-ctp-mantle/70 p-5">
              <h3 className="text-sm font-semibold tracking-[0.28em] uppercase text-ctp-green">
                Ready for data wiring
              </h3>
              <p className="mt-3 text-sm leading-7 text-ctp-subtext1">
                This shared shell now keeps navigation and topbar state stable
                while route-specific panels swap into place underneath.
              </p>
            </article>
            <div className="rounded-[1.5rem] border border-ctp-surface0/80 bg-ctp-mantle/70 p-5">
              <h3 className="text-sm font-semibold tracking-[0.28em] uppercase text-ctp-yellow">
                Link confidence
              </h3>
              <p className="mt-3 text-sm leading-7 text-ctp-subtext1">
                Bubble colour now lerps from unlinked to pending to linked as
                each match score improves.
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            {progressExamples.map((example) => (
              <ProgressBubble
                key={example.label}
                label={example.label}
                matchPercentage={example.matchPercentage}
                status={example.status}
              />
            ))}
          </div>
        </div>

        <aside className="rounded-[1.75rem] border border-ctp-surface0/80 bg-ctp-base/75 p-6 shadow-xl shadow-ctp-crust/20 backdrop-blur">
          <p className="text-sm font-semibold tracking-[0.32em] uppercase text-ctp-peach">
            Section snapshot
          </p>
          <div className="mt-6 space-y-4">
            {stats.map((stat) => (
              <div
                key={stat.label}
                className="rounded-[1.35rem] border border-ctp-surface0/80 bg-ctp-mantle/75 px-4 py-4"
              >
                <p className="text-xs font-semibold tracking-[0.24em] uppercase text-ctp-subtext0">
                  {stat.label}
                </p>
                <p className="mt-2 font-display text-2xl font-semibold text-ctp-text">
                  {stat.value}
                </p>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </section>
  );
}

async function fetchSearchResults(query: string): Promise<SearchResponse> {
  const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
  if (!response.ok) {
    throw new Error(`Search request failed with status ${response.status}`);
  }

  return (await response.json()) as SearchResponse;
}

function SearchPanel() {
  const location = useLocation();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
    }, 180);

    return () => window.clearTimeout(timeoutId);
  }, [query]);

  useEffect(() => {
    setQuery("");
    setDebouncedQuery("");
  }, [location.pathname]);

  const searchQuery = useQuery({
    queryKey: ["global-search", debouncedQuery],
    queryFn: () => fetchSearchResults(debouncedQuery),
    enabled: debouncedQuery.length > 1,
  });

  const isOpen = query.trim().length > 1;
  const results = searchQuery.data?.results ?? [];

  return (
    <div className="relative min-w-[18rem] flex-1 sm:min-w-[24rem]">
      <label className="block">
        <span className="sr-only">Global search</span>
        <input
          aria-autocomplete="list"
          aria-controls="global-search-results"
          aria-expanded={isOpen}
          aria-label="Global search"
          className="w-full rounded-full border border-ctp-surface1 bg-ctp-mantle/85 px-5 py-3 text-sm text-ctp-text outline-none transition placeholder:text-ctp-overlay0 focus:border-ctp-sky focus:ring-2 focus:ring-ctp-sky/35"
          name="global-search"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search playlists, tracks, and matches"
          type="search"
          value={query}
        />
      </label>

      {isOpen ? (
        <div
          className="absolute left-0 right-0 top-[calc(100%+0.75rem)] z-20 overflow-hidden rounded-[1.5rem] border border-ctp-surface1 bg-ctp-base/95 shadow-2xl shadow-ctp-crust/35 backdrop-blur"
          id="global-search-results"
        >
          {searchQuery.isPending ? (
            <p className="px-5 py-4 text-sm text-ctp-subtext1">Searching…</p>
          ) : null}
          {searchQuery.isError ? (
            <p className="px-5 py-4 text-sm text-ctp-maroon">
              Search is temporarily unavailable.
            </p>
          ) : null}
          {!searchQuery.isPending && !searchQuery.isError && results.length === 0 ? (
            <p className="px-5 py-4 text-sm text-ctp-subtext1">
              No matches for “{query.trim()}”.
            </p>
          ) : null}
          {results.length > 0 ? (
            <ul className="py-2">
              {results.map((result) => (
                <li key={`${result.kind}-${result.id}`}>
                  <Link
                    className="flex items-start justify-between gap-4 px-5 py-3 transition hover:bg-ctp-surface0/60"
                    to={result.route_path}
                  >
                    <div>
                      <p className="text-sm font-semibold text-ctp-text">
                        {result.title}
                      </p>
                      <p className="mt-1 text-sm text-ctp-subtext1">
                        {result.subtitle}
                      </p>
                    </div>
                    <span className="rounded-full border border-ctp-surface1 bg-ctp-mantle/80 px-2 py-1 text-[0.65rem] font-semibold tracking-[0.2em] uppercase text-ctp-lavender">
                      {result.kind.replace("_", " ")}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function AppShell() {
  return (
    <div className="min-h-screen bg-transparent px-4 py-4 text-ctp-text sm:px-6 lg:px-8">
      <div className="mx-auto grid min-h-[calc(100vh-2rem)] max-w-[110rem] gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <aside className="rounded-[2rem] border border-ctp-surface0/80 bg-ctp-crust/70 p-5 shadow-2xl shadow-ctp-crust/40 backdrop-blur">
          <div className="flex h-full flex-col">
            <div className="rounded-[1.75rem] border border-ctp-surface0/80 bg-[linear-gradient(160deg,rgba(137,180,250,0.18),rgba(30,30,46,0.9)_45%,rgba(17,17,27,0.95))] p-5">
              <p className="text-sm font-semibold tracking-[0.42em] uppercase text-ctp-sky">
                crate-lynx
              </p>
              <h1 className="mt-4 font-display text-3xl font-bold tracking-tight text-ctp-rosewater">
                Link your library without losing control.
              </h1>
              <p className="mt-4 text-sm leading-7 text-ctp-subtext1">
                Persistent navigation for operations, streaming sync, and local
                archive workflows.
              </p>
            </div>

            <nav aria-label="Sidebar" className="mt-6 space-y-3">
              {appRoutes.map(({ path, section }) => (
                <ShellNavLink key={path} path={path} section={section} />
              ))}
            </nav>

            <div className="mt-6 rounded-[1.5rem] border border-ctp-surface0/80 bg-ctp-base/55 p-4">
              <p className="text-xs font-semibold tracking-[0.28em] uppercase text-ctp-subtext0">
                Queue pulse
              </p>
              <p className="mt-3 font-display text-3xl font-semibold text-ctp-text">
                87%
              </p>
              <p className="mt-2 text-sm leading-6 text-ctp-subtext1">
                Match throughput is holding steady while new UI pieces come
                online.
              </p>
            </div>
          </div>
        </aside>

        <div className="rounded-[2rem] border border-ctp-surface0/80 bg-ctp-mantle/55 p-4 shadow-2xl shadow-ctp-crust/30 backdrop-blur sm:p-5">
          <header className="rounded-[1.75rem] border border-ctp-surface0/80 bg-ctp-base/80 px-5 py-4 shadow-lg shadow-ctp-crust/15">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div>
                <p className="text-sm font-semibold tracking-[0.3em] uppercase text-ctp-subtext0">
                  App shell
                </p>
                <h2 className="mt-2 font-display text-2xl font-semibold text-ctp-text">
                  Unified review workspace
                </h2>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <SearchPanel />
                <button
                  className="rounded-full border border-ctp-surface1 bg-ctp-base px-4 py-3 text-sm font-semibold text-ctp-subtext0 transition hover:border-ctp-sky hover:text-ctp-text"
                  type="button"
                >
                  Recent activity
                </button>
              </div>
            </div>
          </header>

          <main className="mt-4">
            <Routes>
              <Route
                path="/"
                element={<Navigate to={appRoutes[0].path} replace />}
              />
              {appRoutes.map((route) => (
                <Route
                  key={route.path}
                  path={route.path}
                  element={<SectionView {...route} />}
                />
              ))}
            </Routes>
          </main>
        </div>
      </div>
    </div>
  );
}

function App() {
  return <AppShell />;
}

export default App;
