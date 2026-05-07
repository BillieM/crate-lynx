# Matching Flow Improvements

- [x] Improve tag candidate scoring with a token-aware ranker.
- [x] Reduce noisy candidate persistence.
- [x] Clear stale sibling suggestions when approving a proposal.
- [x] Group proposal candidates in the UI.
- [x] Clean up orphaned suggestions for already-approved tracks.

> The OnlyL/Gigi D'Agostino regression test from the original validation item is folded into T8 in the next section.

# Dense Track And Playlist Tables

**Non-goals (v1):** no destructive local-file deletion ("delete" means unlink final link or disable sync); no pagination; no row virtualization; no column resize / visibility menus; no conversion of the proposals view (stays card-based).

## T1. Shared dense-table foundation

- [x] Add `@tanstack/react-table` (no other table package is currently installed).
- [x] Build `<DataTable<TRow>>` in `app-ui/src/components/` using a semantic `<table>` with sticky header, compact density, accessible checkbox selection, and horizontal overflow on small screens. Reuse Catppuccin tokens (`textClasses.title`, `surfaceClasses.panelRadius`, etc.) so the table reads as part of the existing system.
- [x] Component API:
  - Props: `data`, `columns`, `rowId`, `sorting`, `onSortingChange`, `rowSelection`, `onRowSelectionChange`, `onActivate(row)`, `density="compact"`, `stickyHeader`, `bulkActionSlot`.
  - Column meta: `{ hideBelow?: "sm" | "md" | "lg", align?: "start" | "end", widthClass?: string }` so views can opt columns out at narrow widths instead of relying on truncation alone.
  - Selection state lifted to the caller so views can wire bulk toolbars and reset on filter change.
- [x] Behaviour decisions (locked for v1):
  - **Clear selection on filter change.** Persisting invisible selection is a bulk-action footgun.
  - **No virtualization.** Isolate row rendering so `@tanstack/react-virtual` can drop in later if profiling demands it.
  - Keyboard: `↑/↓` move focus, `Space` toggle select, `Enter` activate (drawer), `Shift+Click` range select.
  - Bulk toolbar slot: generic `<BulkActionBar>` rendered above the table, hidden when zero rows selected, exposing selected count + `Clear selection` + caller-supplied actions.
- [x] Tests (Vitest + Testing Library):
  - select / deselect a row, select-all visible, clear selection, sorting toggle, bulk-action enable/disable rules, selection clears when the caller changes filter input.
- [x] **Definition of done:** `npm run lint && npm test && npm run build` pass; new component has tests above.

## T2. Backend fields needed by bulk table actions (done)

- `LibraryTrackRecord` already SELECTs `final_links_table.c.id.label("final_link_id")` (`app/app/library/store.py:85`) and discards it; propagate it through the dataclass and `LibraryTrackResponse` as `final_link_id: int | None`.
- `MissingLocallyTrackRecord` already keys playlist titles by playlist id (`app/app/maintenance/store.py:121-123`); expose those keys as `playlist_ids: list[int]` on the record and `MissingLocallyResponse`.
- Update frontend types in `app-ui/src/features/library/queries.ts:16-27` and `app-ui/src/features/maintenance/queries.ts:5-14`.
- Backend tests: extend `app/tests/test_main.py` library + maintenance assertions to cover the new fields.
- **Definition of done:** `ruff check . && ruff format --check . && pytest app/tests/test_main.py -k "library or maintenance"` pass; new fields visible in serialized responses.

## T3. Track-detail drawer shell + supporting endpoint

- [x] Carved out so it isn't reinvented by T4 and T5.
- [x] New endpoint: `GET /api/local-tracks/{id}` returning a combined detail payload — file path, `library_root_rel_path`, link status, final-link record (if any), pending suggestions, recent failed ingestion attempts. Backed by a new `LocalTrackStore.get_detail` reading from `local_tracks_table`, `final_links_table`, `suggested_links_table`, `failed_ingestion_attempts_table`.
- [x] Drawer primitive (hand-rolled — only `react-router-dom`, `@tanstack/react-query`, and `lucide-react` are available, no headless lib in deps):
  - Props: `open`, `onClose`, `title`, `children`.
  - Focus trap, ESC closes, body scroll lock, `role="dialog"` + `aria-labelledby`, returns focus to invoker on close.
  - Optional URL sync via `?detail={localTrackId}` so refresh / browser back works.
- [x] The drawer body in this task is a placeholder (title + raw detail JSON or a minimal summary). Per-view drawer content lands with the consuming task.
- [x] Tests: drawer open/close, ESC, focus return; backend endpoint shape + 404 path.
- [x] **Definition of done:** `ruff check . && ruff format --check . && pytest` pass for the new endpoint; `npm run lint && npm test` pass for the drawer.

## T4. Convert PlaylistView to dense table + replace overview card with a toolbar (done)

- Same file (`app-ui/src/features/playlists/PlaylistView.tsx` + `PlaylistHeader.tsx`); must ship together to avoid merge conflict between the two pieces.
- Replace `PlaylistHeader`'s large overview card with a single compact toolbar: playlist name, linked / pending / unlinked count pills, sync timestamp, sync-error chip rendered only when present. Drop cover art and the coverage meter in this pass.
- Keep `StatusMessage` for sync in-progress / error above the table.
- Replace `PlaylistTrackRow` card rendering with the shared table.
- Columns: select, position, status dot, title, artist, album, duration, provider track id, actions. Use `hideBelow` meta so album/provider id collapse on small screens.
- Preserve existing filters and the per-row actions: pending rows still review proposals (inline action button or drawer launcher); linked rows still expose final/local link details.
- Bulk action: `Unlink` selected linked rows. Fan out `DELETE /api/final-links/{final_link_id}` with a concurrency cap (`Promise.allSettled` over chunks of 5). Aggregate success / failure counts and surface via `StatusMessage`.
- Wire row activation (`onActivate`) to the T3 drawer for linked rows.
- Tests: column rendering at desktop + sm widths, bulk Unlink path (mocked fetch), pending-row review action still reachable, toolbar count pills.
- **Definition of done:** `npm run lint && npm test && npm run build` pass; manual smoke in dev server confirms no text overlap at 360 px and 1440 px.

## T5. Convert LocalLibraryView to dense table (done)

- Largest file (`app-ui/src/features/library/LocalLibraryView.tsx`, ~507 LOC); keep alone.
- Preserve the four stat cards and the existing filter bar (link status / match method / file status / reset).
- Columns: select, link-status dot, title, artist, album, duration, match method, file status, file path, actions. Apply `hideBelow` meta to album / file path / match method so the row stays legible on narrow viewports.
- Bulk actions:
  - `Re-match` for selected `unlinked` rows: fan out `POST /api/local-tracks/{id}/rematch`, concurrency cap 5, aggregate status.
  - `Unlink` for selected `linked` rows: fan out `DELETE /api/final-links/{final_link_id}` (requires T2's `final_link_id`), same concurrency pattern.
- Wire row activation to the T3 drawer.
- Tests: bulk Re-match enabled only when selection contains unlinked rows; bulk Unlink enabled only when selection contains linked rows; aggregated success/error message renders; selection clears when filters change (covered indirectly via T1, plus a smoke test here).
- **Definition of done:** lint / test / build pass; manual smoke covers 1k+ row counts (no current virtualization, so confirm scroll perf is acceptable; if not, log the finding for a follow-up).

## T6. Convert MissingLocallyView and UnidentifiedView to dense table (done)

- Both views are small (170 / 190 LOC) with one bulk action each — combining them keeps the context window busy and the UX consistent.
- **MissingLocallyView:**
  - Columns: select, status dot, title, artist, album, duration, affected playlists (rendered as count + tooltip / popover with titles), provider track id.
  - Bulk action: `Sync affected playlists` — collect `playlist_ids` across selected rows, dedupe, fan out `POST /api/streaming/playlists/{playlist_id}/sync` with concurrency 5.
  - Decide per-view: keep both summary cards, or absorb counts into the table header. Recommendation — keep them; counts add context the table doesn't.
- **UnidentifiedView:**
  - Columns: select, filename, source path, failed timestamp, reason, local track id, actions.
  - Per-row Rescue stays. Disable selection checkbox for rows where `local_track_id === null`.
  - Bulk action: `Rescue` — skip rows without `local_track_id`, fan out `POST /api/local-tracks/{id}/rescue`, aggregate counts.
  - Keep pending / error / success accessible status feedback (`aria-live="polite"`).
- Tests for each view: bulk action button enable/disable, dedupe of `playlist_ids`, skip-rule for null-`local_track_id` rescue, aggregated status surface.
- **Definition of done:** lint / test / build pass; manual smoke at narrow + wide widths.

## T7. Convert PlaylistSyncConfiguration to dense table

- [x] Replace `PlaylistConfigRow` cards in `app-ui/src/features/playlists/PlaylistSyncConfiguration.tsx`.
- [x] Columns: select, playlist title, sync enabled (toggle / status), track count, last metadata sync, last sync error, provider playlist id, account id, row actions.
- [x] Rename: the existing toolbar button `Sync selected` → `Sync enabled` (PlaylistSyncConfiguration.tsx:218). It still calls account-wide `syncStreamingAccount` — only the label and status copy at lines 232–238 change.
- [x] Bulk actions on selected rows:
  - `Enable sync` / `Disable sync` — PATCH `/api/streaming/playlists/{playlist_id}` with `selected_for_sync`, fan out concurrency 5.
  - `Sync rows` — fan out `POST /api/streaming/playlists/{playlist_id}/sync` per selected row (distinct from the account-wide `Sync enabled` button on the toolbar).
- [x] Tests: rename surfaces in DOM; bulk enable / disable / sync wire the right endpoints; selection-aware bulk button states.
- [x] **Definition of done:** lint / test / build pass.

## T8. Cross-cutting close-out

- a11y / keyboard sweep across the four converted views: confirm no text overlap at 360 px and 1440 px, checkbox labels read correctly, drawer close control reachable, status dots / chips have accessible names.
- Confirm bulk-action error states (one row fails of N) surface a clear aggregated message rather than silently dropping.
- Add the carried-over **OnlyL / Gigi D'Agostino regression test** to `app/tests/test_matching*` so the true candidate ranks above the false positive. (This belongs to the matching pipeline rather than the table work, but is the last orphan from the previous epic.)
- Full validation pass:
  - Backend: `source .venv/bin/activate && ruff check . && ruff format --check . && pytest`
  - Frontend: `cd app-ui && npm run lint && npm test && npm run build`
- **Definition of done:** all commands pass on a clean working tree.

# Authentication And Sync Failure Visibility

Context from investigation:

- Current sync buttons do queue jobs: `/api/streaming/playlists/{playlist_id}/sync` returns `202` and the `streaming` RQ worker executes `app.streaming.jobs.run_youtube_music_playlist_sync_job`.
- The observed failures are not a broken POST handler. The stored YouTube Music session can fetch some selected playlists, but authenticated library/private playlist access is unreliable: `get_library_playlists(limit=5)` returned zero items, `get_account_info()` returned a signed-out-style account menu, and failing playlist responses included `logged_in: 0`.
- Browser-header auth remains the v1 auth mechanism. Stored browser headers must never be rendered back to the UI.
- `auth_error` is recorded on the **account** (`store.py:727` short-circuits in `_run_youtube_music_sync` before per-playlist failure marking). A failure caused by expired headers populates `account.auth_error` and leaves `playlist.last_sync_error` empty — the UI must surface both.
- `POST /api/streaming/accounts` and `GET /api/streaming/accounts` already exist (`router.py:143`, `router.py:248`); only frontend wrappers are missing.

**Non-goals (v1):** multiple YouTube Music accounts (single-account assumption stays — `PlaylistSyncConfiguration.tsx:148`); automatic / OAuth token refresh; backend job-status endpoint or SSE; pre-flight auth probe on submit; sidebar auth-error indicator dot; renaming `display_name` via the PATCH endpoint.

## A1. Backend `PATCH /api/streaming/accounts/{account_id}/auth` + store method

- [x] Add `StreamingAccountStore.update_youtube_music_account_auth(*, account_id: int, browser_headers: dict[str, Any]) -> StreamingAccountRecord | None` in `app/app/streaming/store.py`.
  - Reuse `encrypt_token` from `app/app/streaming/crypto.py` (matching `create_youtube_music_account`, `store.py:81`).
  - In a single `engine.begin()` transaction: update `auth_token_blob`, set `auth_state="connected"`, clear `auth_error`, clear `auth_error_at`, stamp `updated_at = datetime.now(UTC)`.
  - Return the refreshed `StreamingAccountRecord` (use `list_accounts` style read), or `None` when no row matched.
- [x] Add `UpdateStreamingAccountAuthRequest(BaseModel)` in `app/app/streaming/schemas.py` with `browser_headers: dict[str, object]` (mirror `CreateStreamingAccountRequest`, `schemas.py:73`).
- [x] Export the new schema from `app/app/streaming/__init__.py`.
- [x] Add the route in `app/app/streaming/router.py` after `POST /streaming/accounts` (line 248), reusing `serialize_streaming_account` (`router.py:43`):
  ```
  @router.patch("/streaming/accounts/{account_id}/auth")
  def update_streaming_account_auth(
      account_id: int,
      payload: UpdateStreamingAccountAuthRequest,
      engine: Engine = Depends(require_database_engine),
  ) -> StreamingAccountResponse
  ```
- [x] Missing account → `HTTPException(404, "Streaming account not found")` matching `router.py:273` copy. Never return browser headers.
- [x] Backend tests:
  - In `app/tests/test_streaming_accounts.py` (mirror the fixture style at line 33): existing account auth updates → decrypted blob equals new headers; `auth_state="connected"`; `auth_error` and `auth_error_at` cleared; `updated_at` advances; stored blob differs from the previous blob (replaces the broken "old headers no longer decrypt" assertion from the prior draft).
  - Pre-existing `auth_error` is cleared after a successful refresh.
  - Missing account returns `None` from the store method.
  - In `app/tests/test_main.py` (mirror the route-mount assertions at line 523): `/api/streaming/accounts/{account_id}/auth` is mounted under `/api`; PATCH against missing id returns 404; PATCH against an existing account returns the public response shape with no headers leaked.
- **Definition of done:** `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_streaming_accounts.py app/tests/test_main.py` pass.

## A2. Frontend streaming-accounts queries module

- [x] New file `app-ui/src/features/streamingAccounts/queries.ts` exporting:
  - `StreamingAccount` type: `{ id; provider; display_name; auth_state; auth_error: string | null; auth_error_at: string | null; created_at; updated_at; }`.
  - `StreamingAccountsResponse = { accounts: StreamingAccount[] }`.
  - `streamingAccountQueryKeys = { all: ["streaming-accounts"] as const, list: () => ["streaming-accounts", "list"] as const }`.
  - `fetchStreamingAccounts()` → `GET /api/streaming/accounts` via `fetchJson`.
  - `createStreamingAccount({ display_name, browser_headers })` → `POST /api/streaming/accounts` with JSON body.
  - `refreshStreamingAccountAuth({ accountId, browser_headers })` → `PATCH /api/streaming/accounts/{accountId}/auth`.
  - `useStreamingAccountsQuery()`.
  - `useCreateStreamingAccountMutation()` and `useRefreshStreamingAccountAuthMutation()` — both throw on non-2xx responses; both invalidate `streamingAccountQueryKeys.list()` AND `playlistQueryKeys.list()` AND `playlistQueryKeys.config()` on success.
- [x] Keep account query keys disjoint from `playlistQueryKeys` (`app-ui/src/features/playlists/queries.ts:128`).
- [x] Tests in `app-ui/src/features/streamingAccounts/queries.test.tsx` (follow `app-ui/src/features/playlists/queries.test.tsx` patterns):
  - list endpoint URL is `/api/streaming/accounts`.
  - create mutation posts `{ display_name, browser_headers }`.
  - refresh mutation patches `/api/streaming/accounts/{accountId}/auth` with `{ browser_headers }`.
  - failed responses throw.
- [x] **Definition of done:** `cd app-ui && npm run lint && npm test && npm run build` pass.

## A3. Settings → Authentication page

- [x] In `app-ui/src/features/shell/viewRegistry.tsx`:
  - Add `settingsAuthenticationViewId = "settings-authentication"`.
  - Add a static view entry with `path: "/settings/authentication"` rendering `<AuthenticationSettingsView />`.
  - Add a nav item in `buildSettingsNavItems` (line 153) labelled `Authentication`, between General and YouTube Music sync.
- [x] In `app-ui/src/App.tsx:122`: include `settingsAuthenticationViewId` in the `isSettingsView` check.
- [x] New component `app-ui/src/features/settings/AuthenticationSettingsView.tsx` mirroring `GeneralSettingsView.tsx` layout (header + form + `StatusMessage`):
  - Props: none. Reads via `useStreamingAccountsQuery()`; first YouTube Music account is the active account.
  - **No-account state:** "Not connected" status, `Display name` input defaulting to `YouTube Music`, `Browser headers` `<textarea>`, submit `Connect` → `useCreateStreamingAccountMutation`.
  - **Existing-account state:** "Connected" when `auth_state === "connected"`; "Authentication needs attention" when `auth_state === "error"` or `auth_error` is present; render `auth_error` + `auth_error_at`; `Browser headers` textarea; submit `Refresh authentication` → `useRefreshStreamingAccountAuthMutation`.
  - On success: clear textarea, render success `StatusMessage`, expose CTA "Configure playlists" → `navigate("/settings/sync/youtube-music")`.
  - Decision (locked): PATCH never updates `display_name` — only the create form sets it.
  - Never render `auth_token_blob` or any stored header value.
- [x] In `app-ui/src/features/playlists/PlaylistSyncConfiguration.tsx` `PlaylistCollectionState` (line 60–84): when `status="empty"`, append a CTA link/button → `/settings/authentication` so a fresh install has a path forward.
- [x] Tests in `app-ui/src/features/settings/AuthenticationSettingsView.test.tsx`:
  - settings nav and route registry include `Authentication`.
  - no-account state submit calls POST with the expected body.
  - existing-account state submit calls PATCH with the expected body.
  - `auth_state="error"` renders error text and timestamp.
  - textarea clears after a successful mutation.
  - stored headers are not rendered (assert no element contains a sentinel header value after fetching the accounts response).
- [x] **Definition of done:** `cd app-ui && npm run lint && npm test && npm run build` pass.

## A4a. Delayed-refetch helper + wire 4 sync mutation sites

- [x] New helper `app-ui/src/lib/useDelayedInvalidate.ts`:
  ```
  export function useDelayedInvalidate(): (
    queryKeys: readonly QueryKey[],
    delaysMs?: readonly number[],
  ) => void;
  ```
  Default delays `[3000, 10000]`. Returns a stable callback. Cleans up pending timeouts on unmount.
- [x] Wire it into the four mutation sites (preserve existing immediate "queued" status messages — schedule, don't replace):
  1. `app-ui/src/features/playlists/PlaylistView.tsx` topbar Sync trigger — schedule delayed invalidation of `playlistQueryKeys.detail(id)`, `playlistQueryKeys.tracks(id)`, `playlistQueryKeys.list()`, `streamingAccountQueryKeys.list()`.
  2. `PlaylistSyncConfiguration.tsx:118` `selectedSyncMutation` (`Sync enabled`) — schedule `playlistQueryKeys.list()`, `playlistQueryKeys.config()`, `streamingAccountQueryKeys.list()`.
  3. `PlaylistSyncConfiguration.tsx:327 handleBulkRowSync` (`Sync rows`) — schedule the same three keys after the chunked settle resolves.
  4. `PlaylistSyncConfiguration.tsx:127 metadataRefreshMutation` — schedule the same three keys.
- [x] Tests (extend `PlaylistView.test.tsx`, `PlaylistSyncConfiguration.test.tsx`, mock timers via `vi.useFakeTimers()`):
  - immediate queued status still renders on POST success.
  - each mutation schedules invalidation at both delay ticks.
  - advancing timers triggers a refetch of the expected keys.
- **Definition of done:** `cd app-ui && npm run lint && npm test && npm run build` pass.

## A4b. Surface `auth_error` and `last_sync_error` near sync controls

- [x] In `app-ui/src/features/playlists/PlaylistSyncConfiguration.tsx` toolbar (around line 374): if `useStreamingAccountsQuery()` returns an account with `auth_state === "error"` or non-null `auth_error`, render a prominent `<StatusMessage status="error">` above the table with the error text + timestamp and disable `Sync enabled`, `Sync rows`, and `Refresh playlist metadata` while in error state. Include a CTA → `/settings/authentication`.
- [x] In `app-ui/src/features/playlists/PlaylistView.tsx` (around line 263 where `last_sync_error` is already shown): also render the active account's `auth_error` from `useStreamingAccountsQuery()` so a header-level auth failure is visible during a single-playlist view.
- [ ] Tests:
  - `PlaylistSyncConfiguration.test.tsx`: mock accounts with `auth_state="error"` → assert error message, timestamp, CTA visible; assert sync buttons disabled.
  - `PlaylistView.test.tsx`: mock accounts with non-null `auth_error` → assert it renders alongside `last_sync_error`.
  - Refetched `auth_error` (after A4a's delayed invalidation) becomes visible without manual reload.
- **Definition of done:** `cd app-ui && npm run lint && npm test && npm run build` pass.

## A5. Validation

- [ ] Backend:
  - `source .venv/bin/activate`
  - `ruff check .`
  - `ruff format --check .`
  - `pytest`
- [ ] Frontend:
  - `cd app-ui`
  - `npm run lint`
  - `npm test`
  - `npm run build`
