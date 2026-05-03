function App() {
  return (
    <main className="min-h-screen px-6 py-10 text-ctp-text sm:px-10">
      <section className="mx-auto flex min-h-[calc(100vh-5rem)] w-full max-w-5xl items-center">
        <div className="relative w-full overflow-hidden rounded-[2rem] border border-ctp-surface1/70 bg-ctp-base/85 p-8 shadow-2xl shadow-ctp-crust/50 backdrop-blur sm:p-12">
          <div className="absolute inset-x-0 top-0 h-px bg-linear-to-r from-transparent via-ctp-sky/80 to-transparent" />
          <div className="absolute -right-20 top-[-3.5rem] h-44 w-44 rounded-full bg-ctp-blue/15 blur-3xl" />
          <div className="absolute bottom-[-4rem] left-[-2rem] h-40 w-40 rounded-full bg-ctp-mauve/15 blur-3xl" />

          <div className="relative space-y-6">
            <p className="font-display text-sm font-semibold uppercase tracking-[0.4em] text-ctp-sapphire">
              crate-lynx
            </p>
            <div className="space-y-4">
              <h1 className="max-w-3xl font-display text-4xl font-bold tracking-tight text-ctp-rosewater sm:text-5xl">
                Frontend scaffold ready for the playlist UI.
              </h1>
              <p className="max-w-2xl text-lg leading-8 text-ctp-subtext1">
                Tailwind CSS is now wired into the Vite app with the official
                Catppuccin Mocha theme, so the shell, routing, and data-loading
                work can build on the real design tokens instead of placeholder
                styles.
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <article className="rounded-2xl border border-ctp-surface1 bg-ctp-mantle/80 p-5">
                <p className="text-sm font-medium text-ctp-green">
                  Tailwind v4
                </p>
                <p className="mt-2 text-sm leading-6 text-ctp-subtext1">
                  Utility classes are compiled through the Vite plugin rather
                  than a hand-rolled stylesheet.
                </p>
              </article>
              <article className="rounded-2xl border border-ctp-surface1 bg-ctp-mantle/80 p-5">
                <p className="text-sm font-medium text-ctp-pink">
                  Catppuccin Mocha
                </p>
                <p className="mt-2 text-sm leading-6 text-ctp-subtext1">
                  The palette is available directly through `ctp` colour tokens.
                </p>
              </article>
              <article className="rounded-2xl border border-ctp-surface1 bg-ctp-mantle/80 p-5">
                <p className="text-sm font-medium text-ctp-yellow">
                  Ready for E09
                </p>
                <p className="mt-2 text-sm leading-6 text-ctp-subtext1">
                  The next tasks can focus on layout, routing, and server state.
                </p>
              </article>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

export default App;
