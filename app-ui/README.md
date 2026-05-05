# app-ui

React frontend for the crate-lynx music asset manager UI.

## Stack

- Vite + React + TypeScript
- Tailwind CSS with Catppuccin Mocha tokens
- TanStack Query for server state
- React Router for client-side routing
- Vitest + Testing Library for component and query tests

## Development

Install dependencies from this directory:

```bash
npm install
```

Run the Vite dev server:

```bash
npm run dev
```

The Docker image builds the production bundle and serves it with Nginx. `nginx.conf` serves the SPA, proxies `/api/` to the backend `app` service, and exposes `/healthz`.

## Validation

Run the frontend checks from this directory:

```bash
npm run lint
npm test
npm run build
```
