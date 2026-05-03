# E10 — Frontend: playlist views

- [x] Define TanStack Query hooks for playlist detail endpoint: fetch playlist metadata (name, cover art, track count, linked/pending/unlinked counts) and track list
- [x] Build `PlaylistHeader` component: cover art thumbnail, playlist name, progress ring (linked/total), linked/pending/unlinked counts
- [x] Build `TrackStatusDot` component: coloured dot mapped to linked (green), pending (yellow), unlinked (red/subtext) status
- [x] Build `PlaylistTrackRow` component: status dot, track title, artist, album, duration, and per-track action button slot
- [x] Implement per-track action buttons: "Linked" (opens final link info), "Review" (navigates to proposals filtered to this track), "Match" (triggers re-match API call)
- [x] Build `FilterChips` component: All / Linked / Pending / Unlinked chips — filters the track list client-side
- [x] Assemble `PlaylistView` layout: `PlaylistHeader` + `FilterChips` + scrollable `PlaylistTrackRow` list, all within the existing stub shell div
- [x] Wire the Sync button in the topbar action slot: call the YTM sync API endpoint for the active playlist, show loading state
- [x] Wire the Export M3U button in the topbar action slot: hit the M3U export endpoint and trigger a file download
- [ ] Replace the five `playlist2`–`playlist5` stub shells with the same `PlaylistView` component, driven by different playlist IDs from sidebar nav state
- [ ] Apply Catppuccin Mocha tokens throughout — no grays, no default Tailwind colours
