# E13 — Frontend: playlist sync configuration UI

- [x] Add a YouTube Music configuration view entry point from the existing topbar or sidebar
- [ ] Fetch all discovered playlists from `GET /api/streaming/playlists/config` with a dedicated TanStack Query
- [ ] Render the configuration list with playlist metadata and a `selected_for_sync` toggle for each playlist
- [ ] Wire playlist toggles to `PATCH /api/streaming/playlists/{id}` and invalidate both sidebar and config queries on success
- [ ] Add a "Refresh playlist metadata" action wired to `POST /api/streaming/accounts/{id}/refresh-metadata`
- [ ] Add pending, success, and error states for the metadata refresh action
- [ ] Add a "Sync selected" action wired to `POST /api/streaming/accounts/{id}/sync`
- [ ] Add pending, success, and error states for the selected-playlist sync action
- [ ] Cover newly discovered unselected playlists and toggle behavior in frontend tests
- [ ] Run relevant frontend validation: `npm run lint`, `npm test`, and `npm run build`
