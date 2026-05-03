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

### E06 — Link proposal & approval API `in progress`
**Subdir:** `app/`
REST endpoints for the full approval lifecycle: list proposals (with confidence band filtering), approve (writes to `final_links`), reject (updates `suggested_links.status` + `rejected_at`), break link (removes from `final_links`, writes rejected suggestion), re-match (clears suggestion, re-enqueues pipeline). Rejected pairs must never resurface.

---

### E07 — M3U generation
**Subdir:** `app/`
Generate one M3U per streaming playlist based on `playlist_membership` joined through `final_links` to `local_tracks`. Paths resolved relative to consuming tool (not container path). Auto-regenerated whenever a link is approved, rejected, or broken. Export endpoint for on-demand download.

---

### E08 — Metadata rescue
**Subdir:** `app/`
Endpoint to overwrite a local MP3's ID3 tags with metadata from its linked streaming track (title, artist, album, year, high-res album art) using mutagen. Only available when a final link exists.

---

### E09 — Frontend scaffolding & layout
**Subdir:** `app-ui/`
Vite + React + TypeScript. Tailwind CSS with official Catppuccin Mocha plugin. TanStack Query for server state. React Router for view routing. App shell: sidebar (Maintenance / YouTube Music / Local Library sections), topbar, main content area. Global search bar wired to API. Progress bubble component with lerp colour logic.

---

### E10 — Frontend: playlist views
**Subdir:** `app-ui/`
Per-playlist view: playlist header with progress ring, track list with status dots (linked/pending/unlinked), duration, per-track action buttons (linked / review / match). Filter chips (All / Linked / Pending / Unlinked). Topbar sync and Export M3U buttons wired to API.

---

### E11 — Frontend: link proposals view
**Subdir:** `app-ui/`
Proposals list grouped by confidence band (High / Medium / Low). Per-card: confidence bar, local vs streaming track columns, match method badge (ISRC / Tag / Acoustic), score, Approve / Reject buttons. Filter chips by band. Approve/reject actions optimistically update UI via TanStack Query mutation.

---

### E12 — Frontend: library & maintenance views
**Subdir:** `app-ui/`
**Library:** stats cards (total / linked / pending / unlinked), faceted filter bar (link status / match method / file status), flat track list.
**Unidentified:** list of Beets-failed tracks with filename, fingerprint hash, Rescue button (triggers E08).
**Missing Locally:** list of streaming tracks with no local match.
