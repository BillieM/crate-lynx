# E14 — Frontend: sidebar, topbar, and per-playlist UX

- [x] Ensure the sidebar relies on `GET /api/streaming/playlists` returning selected playlists only, with no extra client-side selected filter
- [x] Replace the playlist-view topbar sync action with `POST /api/streaming/playlists/{id}/sync`
- [x] Hide or reroute the topbar sync action when no playlist is selected
- [x] Add pending, success, and error states for per-playlist sync
- [x] Surface each playlist's last sync error string and timestamp in the playlist view when present
- [x] Add an empty state for no selected playlists that routes users to configure YouTube Music sync
- [x] Add loading and error states for metadata refresh and selected-playlist sync where they affect navigation or playlist views
- [ ] Extract shared `StatusMessage` or `EmptyStateCard` components if the new states reuse the same pattern three or more times
- [ ] Update frontend tests for the topbar sync button to expect the per-playlist sync endpoint
- [ ] Update frontend tests for no-selected-playlists and per-playlist sync failure states
- [ ] Run relevant frontend validation: `npm run lint`, `npm test`, and `npm run build`
