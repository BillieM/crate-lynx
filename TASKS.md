# Local Library And Table Filter Cleanup

Context:

- Replace the old tracker content with only this cleanup work.
- Do not edit or stage unrelated local changes, especially the existing settings/auth files currently dirty in the worktree.
- Table-backed filtering should be standardized through TanStack React Table row filtering in the shared `DataTable` wrapper.
- Existing domain filter controls can stay in their views, but they should drive table `columnFilters` instead of pre-filtering arrays before passing rows to `DataTable`.
- No backend schema, endpoint, or migration changes are expected.

## T1. Add shared DataTable filtering support

- [ ] Extend `app-ui/src/components/DataTable.tsx` to use TanStack `getFilteredRowModel`.
- [ ] Add controlled filter props to `DataTableProps`:
  - `columnFilters?: ColumnFiltersState`
  - `onColumnFiltersChange?: OnChangeFn<ColumnFiltersState>`
  - optional `filterFns` if needed for non-default filter semantics.
- [ ] Keep filtering optional so current table consumers can omit filter props without behavior changes.
- [ ] Add a render prop such as `headerSlot?: (state: { filteredRowCount: number; totalRowCount: number }) => ReactNode`.
- [ ] Render `headerSlot` above the table but below `BulkActionBar`, so callers can render "Showing X of Y" using the table filtered row model.
- [ ] Clear row selection when controlled `columnFilters` changes after initial mount.
- [ ] Keep existing sorting, row selection, select-all-visible, sticky header, responsive column metadata, and keyboard behavior unchanged.
- [ ] Update `app-ui/src/components/DataTable.test.tsx` to cover:
  - filtering through `columnFilters`,
  - `headerSlot` receiving filtered and total row counts,
  - selection clearing after filter changes,
  - unchanged sorting and selection behavior.

## T2. Add row-click activation to shared tables

- [ ] Make clicking a body row call `onActivate(row.original)` when `onActivate` is supplied.
- [ ] Preserve existing `Enter` row activation.
- [ ] Do not activate the row when the click starts from interactive controls:
  - row checkbox,
  - header checkbox,
  - buttons,
  - links,
  - inputs,
  - selects,
  - textareas,
  - elements with `role="button"` or another interactive role.
- [ ] Keep checkbox click behavior isolated from row activation.
- [ ] Add `DataTable.test.tsx` coverage for row-click activation and interactive-control isolation.

## T3. Migrate PlaylistView filters to DataTable filters

- [ ] Replace custom pre-filtering in `app-ui/src/features/playlists/PlaylistView.tsx`.
- [ ] Stop passing `filteredTracks` as `data`; pass the full playlist `tracks` array to `DataTable`.
- [ ] Store the active playlist status filter as TanStack `columnFilters`, targeting the `status` column.
- [ ] Keep existing `FilterChips` UI and counts, but make chips update the table filter state.
- [ ] Use the new `headerSlot` state for "Showing X of Y tracks".
- [ ] Remove or simplify `filterPlaylistTracks(...)` usage where it is no longer needed by the view.
- [ ] Keep selected linked-row bulk unlink behavior unchanged.
- [ ] Keep selection clearing on filter change through the shared `DataTable` behavior.
- [ ] Update playlist/filter tests to assert the same visible behavior through table-owned filtering.

## T4. Clean up LocalLibraryView filters and layout

- [ ] Remove the four top stat cards from `app-ui/src/features/library/LocalLibraryView.tsx`.
- [ ] Remove `Match method` and `File status` filters.
- [ ] Remove related filter state/types/options/helpers:
  - `LibraryMatchMethodFilter`,
  - `LibraryFileStatusFilter`,
  - `matchMethodFilters`,
  - `fileStatusFilters`,
  - `LibrarySelectFilter`,
  - match/file filter branches in reset/change handlers.
- [ ] Keep only the link-status chip filter with backend counts.
- [ ] Wire link-status chips to the DataTable `link_status` column filter.
- [ ] Remove custom `filterLibraryTracks(...)` pre-filtering and pass all local library rows to `DataTable`.
- [ ] Use `headerSlot` for "Showing X of Y rows".
- [ ] Keep reset behavior, but reset only the link-status filter, row selection, and bulk status.
- [ ] Update empty-state copy so it refers to the selected link-status filter, not generic "facets".

## T5. Simplify LocalLibraryView columns and row actions

- [ ] Remove Local Library table columns:
  - `Match method`,
  - `File status`,
  - `Actions`.
- [ ] Keep columns:
  - status dot,
  - title,
  - artist,
  - album,
  - duration,
  - file path.
- [ ] Remove per-row `Details` and per-row `Re-match` UI with the deleted Actions column.
- [ ] Preserve detail access through row click and `Enter`, opening the existing `LocalTrackDetailDrawer`.
- [ ] Keep row activation URL behavior through `?detail={localTrackId}`.
- [ ] Remove now-unused imports/helpers such as `Pill`, file-status tones, match-method formatting, and `LibraryTrackActions`.

## T6. Fix LocalLibrary bulk re-match eligibility

- [ ] Change bulk `Re-match` eligibility from selected `unlinked` rows only to selected non-linked rows:
  - eligible: `pending`, `unlinked`,
  - ineligible: `linked`.
- [ ] Keep bulk `Unlink` limited to selected linked rows with `final_link_id`.
- [ ] Reuse existing `POST /api/local-tracks/{id}/rematch`; do not add or change backend endpoints.
- [ ] Preserve existing concurrency behavior: process rematch requests in chunks of 5 and aggregate success/failure counts.
- [ ] Update button disabled logic so a mixed selection enables:
  - `Re-match` when at least one selected row is pending or unlinked,
  - `Unlink` when at least one selected row is linked.
- [ ] Update status copy only where needed to stay accurate for pending and unlinked rows.
- [ ] Add tests proving pending rows are valid rematch targets.

## T7. Audit other DataTable consumers

- [ ] Confirm `MissingLocallyView`, `UnidentifiedView`, and `PlaylistSyncConfiguration` still work with omitted filter props.
- [ ] Confirm their selection, bulk-action, row action, and sorting behavior still passes existing tests after `DataTable` changes.
- [ ] Confirm no stale filter UI, copy, helper functions, or tests remain from the removed Local Library match/file filters.
- [ ] Do not change non-table proposal filters in this pass.
- [ ] Do not add pagination, virtualization, column visibility menus, or column resizing.

## T8. Frontend tests and validation

- [ ] Update `app-ui/src/features/library/LocalLibraryView.test.tsx` for:
  - removed stats,
  - removed match method and file status filters,
  - removed match method, file status, and actions columns,
  - link-status table filtering,
  - row-click / Enter detail activation,
  - pending and unlinked bulk rematch,
  - linked-only bulk unlink.
- [ ] Update `app-ui/src/App.test.tsx` assertions that currently expect library stats or removed filters.
- [ ] Update `app-ui/src/components/DataTable.test.tsx` for shared filtering and row activation.
- [ ] Update playlist filter tests for table-owned filtering.
- [ ] Run frontend validation:
  - `cd app-ui`
  - `npm run lint`
  - `npm test`
  - `npm run build`
