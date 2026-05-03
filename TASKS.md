# E10 — Frontend: playlist views integration fixes

- [x] Add or align backend endpoints for playlist detail and playlist tracks so the frontend can load real playlist metadata, linked/pending/unlinked counts, and track rows from deployed data
- [x] Standardize browser-facing API paths under `/api` for playlist detail, playlist tracks, M3U export, streaming sync, and per-track rematch so they work through the deployed Nginx proxy
- [x] Replace hard-coded playlist sidebar fixture names, counts, and IDs with real playlist data from the streaming playlists API
- [ ] Update the playlist view default/selection behavior so the app opens a real playlist when available and shows a clear empty state when no synced playlists exist
- [ ] Update frontend tests so mocked routes match the real backend API contract instead of testing nonexistent `/api/playlists` endpoints only in isolation
- [ ] Add backend route tests for the playlist detail, playlist tracks, and `/api`-prefixed action endpoints used by the deployed UI
- [ ] Run relevant validation: backend `ruff check .`, `ruff format --check .`, `pytest`; frontend `npm run lint`, `npm test`, `npm run build`
