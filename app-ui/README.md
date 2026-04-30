# app-ui

React frontend served via Nginx for the music asset manager UI.

This directory now includes the container scaffold for the frontend:

- `Dockerfile` builds a Vite-style app when `package.json` exists
- `nginx.conf` serves the SPA, proxies `/api/` to the `app` service, and exposes `/healthz`

Until the React app is added, the build emits a small placeholder page so the container can still build and serve successfully.
