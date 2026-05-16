# tasks.md

## Task Breakdown

- [x] Add playlist sync-mode migration and backend model support
  - Add `sync_mode`, `provider_track_count`, `metadata_synced_at`, and `tracks_synced_at` fields on `streaming_playlists`.
  - Make `sync_mode` the only writable playlist mode source, constrained to `off`, `match_only`, or `full`.
  - Remove `selected_for_sync` and replace ambiguous `synced_at` storage with explicit metadata and track-import timestamps.
  - Backfill `sync_mode = "full"` where `selected_for_sync` is true, otherwise `off`.
  - Backfill `metadata_synced_at = synced_at`.
  - Backfill `tracks_synced_at = synced_at` only for playlists with existing memberships.
  - Add migration/model tests for the new fields and backfill behavior.

- [x] Update playlist metadata refresh to store provider counts and metadata timestamps
  - Keep metadata refresh limited to discovering/upserting playlist rows, provider counts, and `metadata_synced_at`.
  - Store provider counts from YouTube Music metadata without importing playlist tracks.
  - Preserve existing playlist `sync_mode` values during metadata refresh.
  - Extend `YouTubeMusicPlaylist` to normalize provider counts from ytmusicapi library playlist `count`, with defensive fallback to `trackCount`.
  - Tolerate missing, blank, or non-numeric provider counts.
  - Test provider count normalization and metadata refresh persistence.

- [x] Update active playlist track import behavior for off, match-only, and full modes
  - Import tracks for active modes only: `full` and `match_only`.
  - Skip `off` playlists during account sync.
  - Fetch all tracks for active playlist imports with `get_playlist(..., limit=None)`.
  - Update successful track import to set `tracks_synced_at`.
  - Keep direct playlist sync endpoint behavior permissive unless a later task explicitly changes API enforcement.
  - Test account sync mode filtering, full-track fetches, and successful `tracks_synced_at` updates.

- [x] Replace backend API fields and PATCH contract with explicit sync mode fields
  - Expose playlist response fields as `sync_mode`, `provider_track_count`, `imported_track_count`, `metadata_synced_at`, `tracks_synced_at`, `last_sync_error`, and `last_sync_error_at`.
  - Remove `selected_for_sync`, `track_count`, and `synced_at` from backend API schemas and query schemas.
  - Compute `imported_track_count` from `playlist_membership` joins on read instead of storing it.
  - Change playlist config PATCH behavior to accept `{ sync_mode }`.
  - Add router/API tests for the new response shape and PATCH behavior.

- [ ] Scope ISRC and tag matching to active playlist modes
  - Scope ISRC matcher candidates to streaming tracks that belong to at least one active playlist (`full` or `match_only`).
  - Scope tag matcher candidates to streaming tracks that belong to at least one active playlist (`full` or `match_only`).
  - Ensure off-only streaming tracks are ignored by matchers.
  - Ensure tracks remain matchable when they belong to at least one `full` or `match_only` playlist.
  - Add matcher tests for off-only, match-only, full, and mixed-membership cases.

- [ ] Restrict wanted-playlist, reporting, and M3U backend surfaces to full playlists
  - Filter sidebar playlists, playlist navigation, playlist detail access, Missing Locally, and wanted-music reporting to `full` playlists only.
  - Restrict M3U export and regeneration writes to `full` playlists only.
  - Preserve existing stale M3U files when a playlist leaves `full`; prevent future non-full writes instead of deleting old files.
  - Add backend tests for reporting, playlist navigation/detail, Missing Locally, stale M3U preservation, and future M3U writes.

- [ ] Regenerate OpenAPI/frontend types and update playlist settings UI
  - Regenerate OpenAPI/frontend types and keep codegen consistency checks passing.
  - Remove frontend usage of `selected_for_sync`, `track_count`, and `synced_at`.
  - Replace checkbox selection with mode controls for `Off`, `Match only`, and `Full sync`.
  - Show split columns for YouTube count, imported tracks, metadata refreshed, track synced, and last sync error.
  - Add header summary counts for discovered playlists, full-sync playlists, and match-only playlists.
  - Add bulk actions that set selected rows to Off, Match only, or Full sync.
  - Rename account sync copy to reflect active modes, e.g. `Sync Full + Match`.
  - Ensure settings-table row sync queues only active rows, with off rows excluded or disabled.
  - Add frontend tests for rendering, split columns, bulk mode changes, row sync behavior, sync action copy, and generated API type consistency.

- [ ] Add final regression coverage and remove stale selected/synced references
  - Search backend, frontend, generated types, tests, and docs for stale `selected_for_sync`, `track_count`, and `synced_at` usage.
  - Confirm old `selected_for_sync` and `synced_at` fields are removed from schemas/types.
  - Fill any remaining test gaps from the full feature detail before marking the epic complete.
  - Run the relevant backend and frontend validation commands for the final changed surface area.

## Full Feature Detail

### Playlist Sync Modes And Metadata Counts

#### Summary

- Replace playlist sync selection with explicit `off`, `match_only`, and `full` modes.
- Keep playlist metadata refresh lightweight: discover playlist rows and provider track counts only.
- Import tracks for active modes only: `full` and `match_only`.
- Fetch all tracks for active playlist imports.
- Only `full` playlists are visible/actionable as wanted playlists in navigation, Missing Locally, playlist pages, and M3U export/regeneration.
- Match-only playlists provide candidate data for matching without appearing as wanted playlists.

#### Key Changes

- Add DB fields on `streaming_playlists`:
  - `sync_mode`
  - `provider_track_count`
  - `metadata_synced_at`
  - `tracks_synced_at`
- Make `sync_mode` the only writable playlist mode source, constrained to `off`, `match_only`, or `full`.
- Remove `selected_for_sync` instead of keeping it as a derived or mirrored compatibility field.
- Replace ambiguous `synced_at` with explicit metadata and track-import timestamps.
- Backfill `sync_mode = "full"` where `selected_for_sync` is true, otherwise `off`.
- Backfill `metadata_synced_at = synced_at`.
- Backfill `tracks_synced_at = synced_at` only for playlists with existing memberships.
- Store only provider counts; compute imported counts from `playlist_membership` joins on read.
- Extend `YouTubeMusicPlaylist` to normalize provider counts from ytmusicapi library playlist `count`, with defensive fallback to `trackCount`.
- Tolerate missing, blank, or non-numeric provider counts.
- Update active playlist track import to call `get_playlist(..., limit=None)` so `full` and `match_only` syncs import all tracks.
- Keep metadata refresh limited to upserting playlist rows, provider counts, and `metadata_synced_at`.
- Update account sync to import tracks only for `full` and `match_only`; skip `off`.
- Update successful track import to set `tracks_synced_at`.
- Scope ISRC and tag matchers to streaming tracks that belong to at least one active playlist (`full` or `match_only`).
- Filter sidebar playlists, playlist navigation, playlist detail access, Missing Locally, M3U export, and M3U regeneration to `full` playlists only.
- Do not delete existing stale M3U files when a playlist leaves `full`; just prevent future non-full writes.

Reference: https://ytmusicapi.readthedocs.io/en/1.10.3/reference/api/ytmusicapi.mixins.html

#### API And UI

- Playlist response fields should use explicit names:
  - `sync_mode`
  - `provider_track_count`
  - `imported_track_count`
  - `metadata_synced_at`
  - `tracks_synced_at`
  - `last_sync_error`
  - `last_sync_error_at`
- Remove `selected_for_sync`, `track_count`, and `synced_at` from API schemas, generated frontend types, query schemas, and UI usage.
- Change playlist config PATCH to send `{ sync_mode }`.
- Replace checkbox selection with mode controls:
  - `Off`
  - `Match only`
  - `Full sync`
- Show separate columns for:
  - YouTube count (`provider_track_count`)
  - Imported tracks (`imported_track_count`)
  - Metadata refreshed (`metadata_synced_at`)
  - Track synced (`tracks_synced_at`)
  - Last sync error
- Add header summary counts for discovered playlists, full-sync playlists, and match-only playlists.
- Bulk actions set selected rows to Off, Match only, or Full sync.
- Rename account sync copy to reflect active modes, e.g. `Sync Full + Match`.
- Settings-table row sync should queue only active rows; off rows should not be included in row-sync bulk actions.
- Do not add a new backend rejection for direct sync requests against off playlists unless a later task explicitly wants stricter API enforcement.
- Regenerate OpenAPI/frontend types and keep codegen consistency checks passing.

#### Tests

- Backend:
  - Migration backfills `sync_mode`, `provider_track_count`, `metadata_synced_at`, and `tracks_synced_at`.
  - Old `selected_for_sync` and `synced_at` fields are removed from schemas/types.
  - Provider count persistence during metadata refresh.
  - Mode preservation during metadata refresh.
  - Account sync imports only `full` and `match_only`.
  - Active playlist imports request all tracks.
  - `tracks_synced_at` updates only after track import success.
  - Imported counts are computed from membership joins, not stored.
  - Reporting, playlist navigation/detail, Missing Locally, and M3U surfaces exclude `match_only` and `off`.
  - Existing stale M3U files are preserved when mode changes away from `full`.
  - Future M3U export/regeneration writes only `full` playlists.
- Adapter:
  - Provider count normalization for `count`, fallback `trackCount`, int, numeric string, missing, blank, and invalid values.
- Matching:
  - ISRC matcher ignores off-only streaming tracks.
  - Tag matcher ignores off-only streaming tracks.
  - Tracks remain matchable when they belong to at least one `full` or `match_only` playlist.
- Router/API:
  - New response fields.
  - `{ sync_mode }` PATCH behavior.
  - Direct playlist sync endpoint behavior remains permissive unless otherwise changed later.
- Frontend:
  - Mode control rendering.
  - Split provider/imported count columns.
  - Split metadata/track timestamp columns.
  - Bulk mode changes.
  - Row sync excludes or disables off rows.
  - Sync action copy reflects active modes.
  - Generated API types remain in sync with the backend schema.

#### Validation

- Backend:
  - `ruff check .`
  - `ruff format --check .`
  - `pytest`
- Frontend:
  - `npm run lint`
  - `npm test`
  - `npm run build`

#### Assumptions

- `full` means visible and actionable as a wanted playlist: sidebar, playlist pages, Missing Locally, and M3U.
- `match_only` means imported candidate data only: eligible for matching, hidden from playlist navigation and wanted-music reports.
- `off` means not imported by account sync and not eligible as the only source of matching candidates.
- Provider track count is advisory metadata from YouTube Music.
- Imported track count is computed from current local playlist membership rows.
- Existing stale M3U files are ignored rather than cleaned up.
