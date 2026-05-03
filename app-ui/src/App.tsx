import { NavLink, Navigate, Route, Routes } from "react-router-dom";

type AppRoute = {
  description: string;
  heading: string;
  path: string;
  tabLabel: string;
};

const appRoutes: AppRoute[] = [
  {
    path: "/maintenance",
    tabLabel: "Maintenance",
    heading: "Maintenance",
    description:
      "System jobs, ingestion health, and cleanup tools will land here.",
  },
  {
    path: "/youtube-music",
    tabLabel: "YouTube Music",
    heading: "YouTube Music",
    description:
      "Playlist sync status and link review flows will anchor this section.",
  },
  {
    path: "/local-library",
    tabLabel: "Local Library",
    heading: "Local Library",
    description:
      "Library stats, track inventory, and metadata rescue tools belong here.",
  },
];

function RouteCard({ description, heading }: Omit<AppRoute, "path" | "tabLabel">) {
  return (
    <section className="mx-auto flex min-h-[calc(100vh-5rem)] w-full max-w-5xl items-center">
      <div className="relative w-full overflow-hidden rounded-[2rem] border border-ctp-surface1/70 bg-ctp-base/85 p-8 shadow-2xl shadow-ctp-crust/50 backdrop-blur sm:p-12">
        <div className="absolute inset-x-0 top-0 h-px bg-linear-to-r from-transparent via-ctp-sky/80 to-transparent" />
        <div className="absolute -right-20 top-[-3.5rem] h-44 w-44 rounded-full bg-ctp-blue/15 blur-3xl" />
        <div className="absolute bottom-[-4rem] left-[-2rem] h-40 w-40 rounded-full bg-ctp-mauve/15 blur-3xl" />

        <div className="relative space-y-8">
          <div className="space-y-4">
            <p className="font-display text-sm font-semibold uppercase tracking-[0.4em] text-ctp-sapphire">
              crate-lynx
            </p>
            <h1 className="max-w-3xl font-display text-4xl font-bold tracking-tight text-ctp-rosewater sm:text-5xl">
              {heading}
            </h1>
            <p className="max-w-2xl text-lg leading-8 text-ctp-subtext1">
              {description}
            </p>
          </div>

          <nav
            aria-label="Top-level sections"
            className="flex flex-wrap gap-3"
          >
            {appRoutes.map((route) => (
              <NavLink
                key={route.path}
                to={route.path}
                className={({ isActive }) =>
                  `rounded-full border px-4 py-2 text-sm font-medium transition ${
                    isActive
                      ? "border-ctp-blue bg-ctp-blue/15 text-ctp-blue"
                      : "border-ctp-surface1 bg-ctp-mantle/80 text-ctp-subtext0 hover:border-ctp-sapphire hover:text-ctp-text"
                  }`
                }
              >
                {route.tabLabel}
              </NavLink>
            ))}
          </nav>
        </div>
      </div>
    </section>
  );
}

function App() {
  return (
    <main className="min-h-screen px-6 py-10 text-ctp-text sm:px-10">
      <Routes>
        <Route
          path="/"
          element={<Navigate to={appRoutes[0].path} replace />}
        />
        {appRoutes.map(({ description, heading, path }) => (
          <Route
            key={path}
            path={path}
            element={<RouteCard description={description} heading={heading} />}
          />
        ))}
      </Routes>
    </main>
  );
}

export default App;
