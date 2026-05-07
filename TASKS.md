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

## T5. Convert LocalLibraryView to dense table

- Largest file (`app-ui/src/features/library/LocalLibraryView.tsx`, ~507 LOC); keep alone.
- Preserve the four stat cards and the existing filter bar (link status / match method / file status / reset).
- Columns: select, link-status dot, title, artist, album, duration, match method, file status, file path, actions. Apply `hideBelow` meta to album / file path / match method so the row stays legible on narrow viewports.
- Bulk actions:
  - `Re-match` for selected `unlinked` rows: fan out `POST /api/local-tracks/{id}/rematch`, concurrency cap 5, aggregate status.
  - `Unlink` for selected `linked` rows: fan out `DELETE /api/final-links/{final_link_id}` (requires T2's `final_link_id`), same concurrency pattern.
- Wire row activation to the T3 drawer.
- Tests: bulk Re-match enabled only when selection contains unlinked rows; bulk Unlink enabled only when selection contains linked rows; aggregated success/error message renders; selection clears when filters change (covered indirectly via T1, plus a smoke test here).
- **Definition of done:** lint / test / build pass; manual smoke covers 1k+ row counts (no current virtualization, so confirm scroll perf is acceptable; if not, log the finding for a follow-up).

## T6. Convert MissingLocallyView and UnidentifiedView to dense table

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

- Replace `PlaylistConfigRow` cards in `app-ui/src/features/playlists/PlaylistSyncConfiguration.tsx`.
- Columns: select, playlist title, sync enabled (toggle / status), track count, last metadata sync, last sync error, provider playlist id, account id, row actions.
- Rename: the existing toolbar button `Sync selected` → `Sync enabled` (PlaylistSyncConfiguration.tsx:218). It still calls account-wide `syncStreamingAccount` — only the label and status copy at lines 232–238 change.
- Bulk actions on selected rows:
  - `Enable sync` / `Disable sync` — PATCH `/api/streaming/playlists/{playlist_id}` with `selected_for_sync`, fan out concurrency 5.
  - `Sync rows` — fan out `POST /api/streaming/playlists/{playlist_id}/sync` per selected row (distinct from the account-wide `Sync enabled` button on the toolbar).
- Tests: rename surfaces in DOM; bulk enable / disable / sync wire the right endpoints; selection-aware bulk button states.
- **Definition of done:** lint / test / build pass.

## T8. Cross-cutting close-out

- a11y / keyboard sweep across the four converted views: confirm no text overlap at 360 px and 1440 px, checkbox labels read correctly, drawer close control reachable, status dots / chips have accessible names.
- Confirm bulk-action error states (one row fails of N) surface a clear aggregated message rather than silently dropping.
- Add the carried-over **OnlyL / Gigi D'Agostino regression test** to `app/tests/test_matching*` so the true candidate ranks above the false positive. (This belongs to the matching pipeline rather than the table work, but is the last orphan from the previous epic.)
- Full validation pass:
  - Backend: `source .venv/bin/activate && ruff check . && ruff format --check . && pytest`
  - Frontend: `cd app-ui && npm run lint && npm test && npm run build`
- **Definition of done:** all commands pass on a clean working tree.
