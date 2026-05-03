# E12 — Backend: configurable per-playlist sync

- [x] Add `selected_for_sync BOOLEAN NOT NULL DEFAULT false` column to `streaming_playlists` via Alembic migration that backfills `true` for any playlist with at least one row in `playlist_membership`
- [x] Update the `StreamingPlaylist` SQLAlchemy model to include `selected_for_sync` and any related read/write helpers
- [x] Wire `sync_youtube_music_playlists()` (`store.py:577`) as the implementation backing the new metadata-only refresh endpoint instead of introducing a parallel discovery path
- [x] Implement `POST /api/streaming/accounts/{id}/refresh-metadata` — discovers playlists only, no track sync
- [x] Change `POST /api/streaming/accounts/{id}/sync` semantics to sync tracks only for playlists where `selected_for_sync = true`, updating the underlying job and any internal callers
- [x] Implement `POST /api/streaming/playlists/{id}/sync` — syncs tracks for a single playlist regardless of `selected_for_sync` state
- [x] Update `GET /api/streaming/playlists` to filter the sidebar payload to `selected_for_sync = true` playlists only
- [x] Implement `GET /api/streaming/playlists/config` — returns all discovered playlists with `selected_for_sync` and metadata for the config UI
- [x] Implement `PATCH /api/streaming/playlists/{id}` accepting body `{ "selected_for_sync": bool }`; ensure deselect preserves memberships and the M3U file on disk
- [x] Update the hardcoded account-sync test fixtures at `app-ui/src/App.test.tsx:181` and `:366` to match the new selected-only sync contract
- [x] Add backend tests covering: migration backfill behavior, refresh-metadata endpoint, account sync respecting `selected_for_sync`, single-playlist sync ignoring the flag, sidebar vs config filtering, PATCH toggling, deselect preserving memberships
- [x] Run validation: backend `ruff check .`, `ruff format --check .`, `pytest`; frontend test suite for the updated fixtures
