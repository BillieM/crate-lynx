# E09 — Frontend scaffolding & layout

- [x] Scaffold a new Vite + React + TypeScript project in `app-ui/`
- [x] Install and configure Tailwind CSS with the official Catppuccin Mocha plugin
- [ ] Install TanStack Query and set up a `QueryClient` provider at the app root
- [ ] Install React Router and define top-level routes (Maintenance, YouTube Music, Local Library)
- [ ] Build the app shell: persistent sidebar with the three navigation sections, topbar, and main content area
- [ ] Wire the global search bar in the topbar to the appropriate API search endpoint
- [ ] Implement the progress bubble component with lerp colour logic (unlinked → pending → linked colour gradient based on match percentage)
- [ ] Configure Nginx in `app-ui/` to serve the built assets and proxy `/api` requests to the `app` container
- [ ] Confirm the `app-ui` Docker container builds and serves the shell correctly end-to-end
