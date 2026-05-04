# crate-lynx — Epics

## Subdir layout

```
crate-lynx/
  app-ui/   React frontend served via Nginx (maps to app-ui container)
  app/      FastAPI server + RQ worker + Beets/FFmpeg/fpcalc/ytmusicapi (maps to app container)
  db/       Alembic migrations + schema (maps to db container)
  redis/    Redis config (maps to redis container)
  docker-compose.yml
  .env.example
```

---

## Epics

### E01 — Project scaffolding `done`
**Subdirs:** root, `app-ui/`, `app/`, `db/`, `redis/`
Docker Compose wiring all 4 services. Nginx config for the frontend. Supervisor or shell script inside `app` to start uvicorn + RQ worker together. Redis config. Env var template (`.env.example`). Health check endpoints on the API.

---

### E02 — Database schema & migrations `done`
**Subdir:** `db/`
Alembic setup. All 7 tables: `local_tracks`, `streaming_accounts`, `streaming_playlists`, `streaming_tracks`, `playlist_membership`, `suggested_links`, `final_links`. SQLAlchemy models shared with `app/`. Fernet encryption helpers for `auth_token_blob`.

---

### E03 — Local library ingestion pipeline `done`
**Subdir:** `app/`
Watchdog monitors `ingestion/` folder. Format check — MP3 passes through, lossless (FLAC/WAV/AIFF) transcoded via FFmpeg. Beets `import -q` for metadata enrichment and move to `/library/`. Chromaprint (`fpcalc`) fingerprint generation. File path stored relative to `LIBRARY_ROOT`. Enqueues matching pipeline job on completion.

---

### E04 — YouTube Music adapter `done`
**Subdir:** `app/`
`YouTubeMusicAdapter` module wrapping ytmusicapi. All ytmusicapi calls routed through this adapter — no direct library calls elsewhere in the codebase. Auth flow writing encrypted token to `streaming_accounts`. Playlist sync populating `streaming_playlists`, `streaming_tracks`, and `playlist_membership`. ISRC extraction from track metadata where available.

---

### E05 — Matching pipeline `done`
**Subdir:** `app/`
Sequential pipeline: ISRC match → fuzzy tag match (rapidfuzz) → acoustic fingerprint fallback (only when tag score is below threshold). Threshold bands: high (`isrc_match=true` or tag > 0.85), medium (0.5–0.85), low (< 0.5, triggers acoustic RQ job). Results written to `suggested_links`. Pipeline is re-runnable per track.

---

### E06 — Link proposal & approval API `done`
**Subdir:** `app/`
REST endpoints for the full approval lifecycle: list proposals (with confidence band filtering), approve (writes to `final_links`), reject (updates `suggested_links.status` + `rejected_at`), break link (removes from `final_links`, writes rejected suggestion), re-match (clears suggestion, re-enqueues pipeline). Rejected pairs must never resurface.

---

### E07 — M3U generation `done`
**Subdir:** `app/`
Generate one M3U per streaming playlist based on `playlist_membership` joined through `final_links` to `local_tracks`. Paths resolved relative to consuming tool (not container path). Auto-regenerated whenever a link is approved, rejected, or broken. Export endpoint for on-demand download.

---

### E08 — Metadata rescue `done`
**Subdir:** `app/`
Endpoint to overwrite a local MP3's ID3 tags with metadata from its linked streaming track (title, artist, album, year, high-res album art) using mutagen. Only available when a final link exists.

---

### E09 — Frontend scaffolding & layout `done`
**Subdir:** `app-ui/`
Vite + React + TypeScript. Tailwind CSS with official Catppuccin Mocha plugin. TanStack Query for server state. React Router for view routing. App shell: sidebar (Maintenance / YouTube Music / Local Library sections), topbar, main content area. Global search bar wired to API. Progress bubble component with lerp colour logic.

---

### E10 — Frontend: playlist views `done`
**Subdir:** `app-ui/`
Per-playlist view: playlist header with progress ring, track list with status dots (linked/pending/unlinked), duration, per-track action buttons (linked / review / match). Filter chips (All / Linked / Pending / Unlinked). Topbar sync and Export M3U buttons wired to API.

---

### E11 — YouTube Music sync reliability `done`
**Subdir:** `app/`
Make per-account playlist track sync resilient so one bad playlist cannot corrupt or abort the rest.

- **Fix the silent-wipe bug.** `list_playlist_tracks()` (`app/app/streaming/adapters/youtube_music.py:98`) currently returns `[]` when the upstream payload is malformed; combined with `replace_playlist_membership()` (`app/app/streaming/store.py:548-553`) deleting before insert, a malformed payload silently wipes the playlist. Distinguish "empty playlist" (legitimate, return `[]`) from "malformed/unparseable payload" (raise a typed error). Per-playlist callers must catch the error and skip `replace_playlist_membership` so prior memberships are preserved.
- **Per-playlist isolation.** Wrap each iteration of the playlist sync loop (around `youtube_music.py:271-277`) in try/except so one failure logs and skips that playlist; sync continues for the rest. Apply the same isolation to ISRC backfill (`_lookup_missing_isrcs` at `youtube_music.py:144`), which currently raises and aborts the loop.
- **No shape-based podcast detection.** Skipping "special playlist shapes" was proposed but there is no reliable adapter field; per-playlist error isolation is the robust fix.
- **Surface failures.** Record per-playlist last-error string + timestamp (on `streaming_playlists` or via job result) so the frontend can show them later (E14 owns the UI).

Out of scope: the discovery-call `get_library_playlists()` HTTP 400 (tracked separately). Track-list scrolling (no concrete repro; existing `min-h-0 flex-1 overflow-y-auto` at `App.tsx:608` appears correct).

---

### E12 — Backend: configurable per-playlist sync `done`
**Subdir:** `app/`
Add per-playlist sync selection and split discovery from track-sync.

- **Schema.** Add `streaming_playlists.selected_for_sync BOOLEAN NOT NULL DEFAULT false`. **Migration must backfill `true` for any playlist with at least one row in `playlist_membership`** so existing users do not lose their sidebar on upgrade. Newly discovered playlists default to `false`.
- **Reuse existing helper.** `sync_youtube_music_playlists()` at `store.py:577` is already metadata-only; wire it to the new refresh-metadata endpoint instead of inventing a parallel discovery path.
- **Endpoints:**
  - `POST /api/streaming/accounts/{id}/refresh-metadata` — discover playlists, no track sync. Wraps `sync_youtube_music_playlists`.
  - `POST /api/streaming/accounts/{id}/sync` — **semantic change**: now syncs tracks for `selected_for_sync = true` playlists only (previously synced all). This is a behavior break; update job, callers, and the hardcoded test fixtures at `app-ui/src/App.test.tsx:181,366`.
  - `POST /api/streaming/playlists/{id}/sync` — sync tracks for one playlist regardless of selected state (used by the per-playlist topbar action in E14).
  - `GET /api/streaming/playlists` — sidebar payload; filtered to `selected_for_sync = true`.
  - `GET /api/streaming/playlists/config` — config-UI payload; all discovered playlists with `selected_for_sync` and metadata.
  - `PATCH /api/streaming/playlists/{id}` — body `{ "selected_for_sync": bool }`.
- **Deselect semantics.** Setting `selected_for_sync = false` only hides the playlist from the sidebar payload. Memberships and the M3U file are preserved on disk; re-selection is instant and requires no re-sync.

---

### E13 — Frontend: playlist sync configuration UI `in progress`
**Subdir:** `app-ui/`
Build the YouTube Music config surface (no existing settings/config shell — start from zero).

- New "YouTube Music configuration" view (modal or routed page; pick in implementation), triggered from a tertiary action in the topbar or sidebar.
- Lists all playlists from `GET /api/streaming/playlists/config` with a toggle bound to `selected_for_sync`. Newly discovered playlists default to unselected.
- Toggle calls `PATCH /api/streaming/playlists/{id}` and invalidates both the sidebar and config TanStack queries on success.
- "Refresh playlist metadata" button → `POST .../refresh-metadata`; pending/success/error state visible.
- "Sync selected" button → `POST .../accounts/{id}/sync` (the now-repurposed endpoint); pending/success/error state visible.

---

### E14 — Frontend: sidebar, topbar, and per-playlist UX
**Subdir:** `app-ui/`
Wire the new endpoints into navigation and per-playlist views.

- **Sidebar.** Once E12's filter ships, `GET /api/streaming/playlists` returns selected only — no client-side filter needed (`App.tsx:694`).
- **Topbar sync (per-playlist).** When viewing a playlist, the topbar sync button calls `POST /api/streaming/playlists/{id}/sync` (replacing `syncStreamingAccount` at `App.tsx:226-236, 394-416`). When not in a playlist view, hide it or route to "sync selected".
- **Tests.** Update the hardcoded account-sync expectations at `App.test.tsx:181` and `:366` to match the per-playlist contract.
- **States.** Add empty/loading/error states for: no selected playlists ("Configure which YouTube Music playlists to sync"), metadata refresh in progress, selected sync in progress, per-playlist sync in progress, per-playlist sync failure (surface E11's per-playlist error string here). Reuse existing patterns: `PlaylistCollectionState` (`App.tsx:629-652`) and the status badges at `App.tsx:475-478`; extract `StatusMessage` / `EmptyStateCard` if reused 3+ times.

---

### E15 — Frontend: link proposals view
**Subdir:** `app-ui/`
Proposals list grouped by confidence band (High / Medium / Low). Per-card: confidence bar, local vs streaming track columns, match method badge (ISRC / Tag / Acoustic), score, Approve / Reject buttons. Filter chips by band. Approve/reject actions optimistically update UI via TanStack Query mutation.

---

### E16 — Frontend: library & maintenance views
**Subdir:** `app-ui/`
**Library:** stats cards (total / linked / pending / unlinked), faceted filter bar (link status / match method / file status), flat track list.
**Unidentified:** list of Beets-failed tracks with filename, fingerprint hash, Rescue button (triggers E08).
**Missing Locally:** list of streaming tracks with no local match.

---

### E17 — Acoustic fingerprint matching via yt-dlp
**Subdir:** `app/`
Implement the acoustic fallback stage that is currently a stub (`pipeline.py` enqueues acoustic jobs with empty fingerprints). For each low-confidence tag match, download the linked streaming track audio via yt-dlp to a temp file, run `fpcalc` (Chromaprint) on it, compare the resulting fingerprint against the local track's stored fingerprint, then delete the temp file. Promote or discard the suggestion based on the acoustic similarity score. Requires wiring fingerprint population into the streaming track model and updating the acoustic RQ job handler.
