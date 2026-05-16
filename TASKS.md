# tasks.md

## Task Breakdown

- [x] Auto-queue playlist metadata refresh after a new YouTube Music account is connected
  - Scope this to first-time YouTube Music account creation from `AuthenticationSettingsView`; do not auto-refresh metadata after existing-account auth refresh.
  - Keep the behavior frontend-owned: after successful `Connect`, call the existing `refreshStreamingAccountMetadata(createdAccount.id)` helper and existing `/api/streaming/accounts/{account_id}/refresh-metadata` endpoint.
  - Do not change backend routes, schemas, OpenAPI types, generated frontend types, or the metadata-refresh response shape.
  - Keep account creation successful even if metadata refresh queueing fails.
  - Clear the cURL textarea after account creation succeeds, regardless of metadata refresh queueing outcome.
  - Show success copy when authentication is saved and metadata refresh is queued.
  - Show partial-failure copy when authentication is saved but metadata refresh cannot be queued.
  - Keep the `Configure playlists` CTA visible for both full success and partial metadata-refresh failure.
  - Schedule delayed invalidation after refresh queueing succeeds so discovered playlists appear after the background job completes.
  - Include the same delayed job surfaces used by manual playlist metadata refresh: streaming accounts, playlist config, full playlist list, and Missing Locally.
  - Preserve the existing account mutation invalidation for the saved account itself.
  - Relevant current files:
    - `app-ui/src/features/settings/AuthenticationSettingsView.tsx`
    - `app-ui/src/features/streamingAccounts/queries.ts`
    - `app-ui/src/features/playlists/queries.ts`
    - `app-ui/src/lib/useDelayedInvalidate.ts`
  - Add frontend tests for:
    - first-time Connect sends the existing account POST and then sends the metadata refresh POST for the returned account id
    - metadata refresh queue success shows saved-auth + metadata-queued copy and the `Configure playlists` CTA
    - metadata refresh queue failure shows partial-failure copy while preserving saved-auth success and the `Configure playlists` CTA
    - existing-account `Refresh authentication` does not auto-queue metadata refresh

- [x] Remove row-selection checkboxes from the playlist sync configuration view
  - Add a `DataTable` option for non-selectable rendering, for example `enableRowSelection?: boolean`, defaulting to the current selectable behavior.
  - In non-selectable mode, hide:
    - the select-all checkbox header cell
    - per-row selection checkbox cells
    - `BulkActionBar`
    - all row-selection bulk action slots
  - In non-selectable mode, disable keyboard spacebar row-selection behavior while preserving row focus, arrow-key movement, sorting, column filtering, sticky headers, and optional row activation behavior.
  - Keep existing selectable table behavior unchanged for:
    - local library
    - playlist detail
    - Missing Locally
    - Unidentified maintenance
  - Use non-selectable mode in `PlaylistSyncConfiguration`.
  - Remove playlist-sync selected-row bulk actions that only appear after selecting rows:
    - `Set Off`
    - `Set Match only`
    - `Set Full sync`
    - `Sync active rows`
  - Remove playlist-sync-only row selection state and selected-row derivations if they are no longer used.
  - Keep these playlist sync controls:
    - top-level `Sync Full + Match`
    - top-level `Refresh playlist metadata`
    - per-row `Off / Match only / Full sync` segmented controls
  - Relevant current files:
    - `app-ui/src/components/DataTable.tsx`
    - `app-ui/src/components/DataTable.test.tsx`
    - `app-ui/src/features/playlists/PlaylistSyncConfiguration.tsx`
    - `app-ui/src/features/playlists/PlaylistSyncConfiguration.test.tsx`
  - Add frontend tests for:
    - `DataTable` non-selectable mode renders no select-all checkbox, row checkboxes, selected-row count, or clear-selection button
    - `DataTable` default behavior remains selectable
    - playlist sync configuration renders no row checkboxes or selected-row action bar
    - top-level sync/metadata buttons and per-row mode controls still render

- [ ] Make playlist sync mode changes update without visibly refreshing the full settings view
  - Replace the playlist mode mutation's immediate full query invalidation with direct React Query cache updates.
  - On mode click, optimistically update the changed row's `sync_mode` in `playlistQueryKeys.config()`.
  - On mode click, also update `playlistQueryKeys.list()` so full-playlist surfaces stay consistent:
    - changing a playlist to `full` adds or replaces it in the full-playlist cache
    - changing a playlist away from `full` removes it from the full-playlist cache
  - On PATCH success, replace the optimistic config/list cache data with the PATCH response.
  - On PATCH failure, restore cache snapshots and show one compact table-level error message above the playlist sync table.
  - Use table-level failure UX, not row-inline failure UX.
  - Avoid refetching `/api/streaming/playlists/config` immediately after each mode click.
  - Keep the table rendered during mode changes; the selected button state should update in place.
  - Clear the table-level mode-update error on the next mode update attempt.
  - Keep `missing-locally` consistent after successful mode changes by invalidating that query, since full-mode membership affects that surface.
  - Do not use delayed invalidation for this synchronous PATCH; delayed invalidation is only for queued background jobs.
  - Relevant current files:
    - `app-ui/src/features/playlists/PlaylistSyncConfiguration.tsx`
    - `app-ui/src/features/playlists/queries.ts`
    - `app-ui/src/lib/optimisticMutation.ts`
    - `app-ui/src/features/maintenance/queries.ts`
  - Current behavior to replace:
    - `toggleMutation` currently calls `invalidatePlaylistConfigurationMutationQueries(queryClient)` on success.
    - Existing test coverage currently expects `/api/streaming/playlists/config` to refetch after mode PATCH; update that expectation.
  - Add frontend tests for:
    - mode change PATCH updates the pressed mode button without refetching the whole config list
    - `/api/streaming/playlists/config` fetch count does not increase immediately after a mode PATCH
    - table remains rendered while the mode mutation is pending/successful
    - failed PATCH rolls back the cached row and shows the compact table-level error
    - changing `off` or `match_only` to `full` adds/replaces the playlist in `playlistQueryKeys.list()`
    - changing `full` to `off` or `match_only` removes the playlist from `playlistQueryKeys.list()`
    - successful mode change invalidates Missing Locally without invalidating/refetching playlist config immediately

## Implementation Context

- This follow-up is frontend-only unless a later task explicitly changes backend behavior.
- Existing backend metadata refresh endpoint:
  - `POST /api/streaming/accounts/{account_id}/refresh-metadata`
  - implemented by `refresh_streaming_account_metadata` in `app/app/streaming/router.py`
  - response shape is `StreamingSyncResponse` with `account_id` and `job_id`
- Existing frontend metadata refresh helper:
  - `refreshStreamingAccountMetadata(accountId)` in `app-ui/src/features/playlists/queries.ts`
- Existing delayed invalidation helper:
  - `useDelayedInvalidate()` in `app-ui/src/lib/useDelayedInvalidate.ts`
  - current default delays are `3000` and `10000` ms
  - use it only after a mutation queues backend work whose visible results land after the request returns
- Existing playlist job invalidation helpers:
  - `streamingAccountCollectionJobInvalidationKeys()`
  - `streamingAccountPlaylistSyncJobInvalidationKeys(playlistIds)`
  - `playlistCollectionJobInvalidationKeys()`
  - `playlistSyncJobInvalidationKeys(playlistIds)`
- Existing playlist mode PATCH helper:
  - `updateStreamingPlaylistConfig({ playlistId, sync_mode })`
  - calls `PATCH /api/streaming/playlists/{playlist_id}` with `{ sync_mode }`
  - returns one `StreamingPlaylistConfig`
- Existing full-playlist list cache:
  - `playlistQueryKeys.list()`
  - backed by `/api/streaming/playlists`
  - contains only `full` playlists
- Existing full config cache:
  - `playlistQueryKeys.config()`
  - backed by `/api/streaming/playlists/config`
  - contains all discovered playlists
- Existing Missing Locally cache:
  - `maintenanceQueryKeys.missingLocally()`
  - should update after full playlist membership changes
- Existing optimistic helper:
  - `createOptimisticMutation` exists in `app-ui/src/lib/optimisticMutation.ts`
  - it currently snapshots and restores one query-key family; the playlist mode implementation may either extend this helper carefully or use local mutation callbacks directly for both config and list caches.
- Current `DataTable` requires controlled `rowSelection` and always renders selection controls.
- Current `PlaylistSyncConfiguration` has row-selection state, selected row derivations, bulk mode updates, and selected-row sync behavior that should be removed by the non-selectable table task.

## Product Decisions

- Auto metadata refresh applies to first-time account connection only, not authentication refresh.
- Auto metadata refresh stays frontend-owned and chains from the Authentication settings UI.
- Account creation is the primary success. Metadata refresh queueing is secondary and must not turn a saved account into a failed Connect.
- Partial Connect success should keep `Configure playlists` visible.
- Playlist sync mode PATCH failures should use a compact table-level error, not a row-inline error.
- Removing checkboxes from playlist sync configuration also removes all playlist-sync selected-row bulk actions.
- Top-level `Sync Full + Match` remains the way to sync active playlists in bulk.
- Per-row mode controls remain the way to change individual playlist modes.
- Backend direct playlist sync permissiveness remains unchanged.
- Existing backend metadata-refresh endpoint and response shape remain unchanged.

## Validation

- Only frontend validation is expected for these tasks unless implementation unexpectedly touches backend files.
- Run from `app-ui/`:
  - `npm run lint`
  - `npm test`
  - `npm run build`
- Do not run frontend formatters that rewrite files unless a later implementation task explicitly chooses that.
- If backend files are changed unexpectedly, also follow the repository backend validation instructions:
  - `source .venv/bin/activate`
  - `ruff check .`
  - `ruff format --check .`
  - `pytest`

## Repository Notes

- `TASKS.md` is currently the only modified tracked file in this planning pass.
- There is no `EPICS.md` in this checkout.
- `.codex/commands/next-task.md` still expects `EPICS.md`; do not rely on that command flow unless `EPICS.md` is restored or the command is updated.
