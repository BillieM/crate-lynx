# E13 — Frontend: playlist sync configuration UI

- [x] Add a YouTube Music configuration view entry point from the existing topbar or sidebar
- [x] Fetch all discovered playlists from `GET /api/streaming/playlists/config` with a dedicated TanStack Query
- [x] Render the configuration list with playlist metadata and a `selected_for_sync` toggle for each playlist
- [x] Wire playlist toggles to `PATCH /api/streaming/playlists/{id}` and invalidate both sidebar and config queries on success
- [x] Add a "Refresh playlist metadata" action wired to `POST /api/streaming/accounts/{id}/refresh-metadata`
- [x] Add pending, success, and error states for the metadata refresh action
- [x] Add a "Sync selected" action wired to `POST /api/streaming/accounts/{id}/sync`
- [x] Add pending, success, and error states for the selected-playlist sync action
- [x] Cover newly discovered unselected playlists and toggle behavior in frontend tests
- [x] Run relevant frontend validation: `npm run lint`, `npm test`, and `npm run build`
