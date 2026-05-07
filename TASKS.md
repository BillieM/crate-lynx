# Local Library And Table Filter Cleanup

Context:

- Replace the old tracker content with only this cleanup work.
- Do not edit or stage unrelated local changes, especially the existing settings/auth files currently dirty in the worktree.
- Table-backed filtering should be standardized through TanStack React Table row filtering in the shared `DataTable` wrapper.
- Existing domain filter controls can stay in their views, but they should drive table `columnFilters` instead of pre-filtering arrays before passing rows to `DataTable`.
- No backend schema, endpoint, or migration changes are expected.

Locked decisions:

- "No filter for column X" is signalled by **omitting** that column entry from `columnFilters` (push `[]` to clear). Do not register custom `filterFns` — TanStack's default equality covers `link_status` and `status`.
- DataTable owns selection-clearing on `columnFilters` change. Consumers stop clearing selection manually.
- Mixed bulk selections (T4): `Re-match` filters out linked rows in the chunk loop; `Unlink` filters out non-linked rows. Aggregate counts only what was actually attempted.

Non-goals (v1):

- No backend schema, endpoints, or migrations.
- No pagination, virtualization, column visibility menus, or column resizing.
- No removal of `filterPlaylistTracks` / `filterTracks.ts` (still unit-tested).
- No changes to `LocalTrackDetailDrawer` placeholder wiring.
- No URL persistence of `columnFilters`.
- No changes to `MissingLocallyView`, `UnidentifiedView`, `PlaylistSyncConfiguration` other than confirming their existing tests still pass.
- No edits to unrelated dirty files in the worktree (settings/auth).

## T1. DataTable filtering & row-click activation

- [x] Files: `app-ui/src/components/DataTable.tsx`, `app-ui/src/components/DataTable.test.tsx`.
- [x] Add `getFilteredRowModel()` to the `useReactTable` config.
- [x] Extend `DataTableProps<TRow>`:
  - `columnFilters?: ColumnFiltersState`
  - `onColumnFiltersChange?: OnChangeFn<ColumnFiltersState>`
  - `headerSlot?: (state: { filteredRowCount: number; totalRowCount: number }) => ReactNode`
- [x] Wire `state.columnFilters` and `onColumnFiltersChange` into `useReactTable` only when both are defined; keep filtering optional so existing consumers (`MissingLocallyView`, `UnidentifiedView`, `PlaylistSyncConfiguration`) keep working with no prop changes.
- [x] Render `headerSlot` between `BulkActionBar` and the `<table>` wrapper (around `DataTable.tsx:226–229`). Counts come from `table.getFilteredRowModel().rows.length` (filtered) and `table.getCoreRowModel().rows.length` (total).
- [x] Selection clearing on filter change: `useEffect` keyed on a stable serialization of `columnFilters` with a `useRef` first-commit guard, then `onRowSelectionChange({})`. No-op when `columnFilters` is undefined.
- [x] Row-click activation:
  - Add `onClick` to `<tr>`. If `event.target.closest('button, a, input, select, textarea, [role="button"], [role="link"], [role="checkbox"], [role="menuitem"], [role="option"]')` is non-null, bail out.
  - Otherwise call `onActivate?.(row.original)`.
  - Keep existing Enter-key activation (`DataTable.tsx:218`) and the bulk-select checkbox `event.stopPropagation()` (`DataTable.tsx:305`).
- [x] Keep existing sorting, row selection, select-all-visible, sticky header, responsive column metadata (`hideBelow`, `align`, `widthClass`), shift-click ranges, and ArrowUp/ArrowDown focus movement unchanged.
- [x] Update `DataTable.test.tsx`:
  - Replace the existing `FilterableDataTable` external-filter test with controlled `columnFilters` state. Assert filtering applies, `headerSlot` receives `{ filteredRowCount, totalRowCount }`, and selection clears after filter changes.
  - Add: row-click on a plain cell calls `onActivate`; row-click on the row checkbox does not; row-click on a `<button>` inside a row does not (add a button to the test column).
  - Assert `headerSlot` does not render when omitted (no empty wrapper).
  - Keep all existing sorting / selection / bulk-action / shift-click / keyboard tests intact.

**Definition of done:**
- `cd app-ui && npm run lint && npm test -- DataTable && npm run build`
- `MissingLocallyView`, `UnidentifiedView`, `PlaylistSyncConfiguration` test files pass without modification.

## T2. Migrate PlaylistView to DataTable filters

- [x] Files: `app-ui/src/features/playlists/PlaylistView.tsx`, `app-ui/src/features/playlists/FilterChips.test.tsx` (only if assertions change).
- [x] Drop `filteredTracks` / `filterPlaylistTracks` import and usage at `PlaylistView.tsx:14,98`. Pass full `tracks` array as `data` (`PlaylistView.tsx:324`).
- [x] Add `const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])`.
- [x] `handleFilterChange(nextFilter)` becomes:
  - if `nextFilter === "all"` → `setColumnFilters([])`
  - else → `setColumnFilters([{ id: "status", value: nextFilter }])`
  - drop the manual `setRowSelection({})` (DataTable handles it).
- [x] Extend the `useEffect` keyed on `playlistResourceId` (`PlaylistView.tsx:211`) to also clear `columnFilters`.
- [x] Pass `columnFilters` and `onColumnFiltersChange={setColumnFilters}` to `<DataTable>`.
- [x] Derive `FilterChips`'s `activeFilter` from `columnFilters` (`(columnFilters[0]?.value as PlaylistTrackFilter) ?? "all"`).
- [x] Replace the `Showing X of Y tracks` paragraph (`PlaylistView.tsx:305–307`) with a `headerSlot` render prop on `<DataTable>`. `getPlaylistTrackFilterCounts` continues to feed chip badges from the unfiltered `tracks`.
- [x] Keep `filterPlaylistTracks` in `filterTracks.ts`; `FilterChips.test.tsx:51–61` still exercises it as a unit.
- [x] Existing `PlaylistView.test.tsx` assertions (filter clicks, bulk unlink success / partial failure, account auth error, drawer-open on linked row) must continue to pass.

**Definition of done:**
- `cd app-ui && npm run lint && npm test -- playlists/PlaylistView playlists/FilterChips && npm run build`

## T3. Strip LocalLibrary stats, filters, columns, and row actions

- [x] Files: `app-ui/src/features/library/LocalLibraryView.tsx`, `app-ui/src/features/library/LocalLibraryView.test.tsx`, `app-ui/src/App.test.tsx` (lines ~566–576, ~596).
- [x] Remove from `LocalLibraryView.tsx`:
  - 4 stat cards block (`LocalLibraryView.tsx:640–644`).
  - `LibraryStat` type, `libraryStatConfigs`, `LibraryStatCard`, `libraryStats` derivation (lines 31–37, 84–113, 220–239, 423–426).
  - `LibraryMatchMethodFilter`, `LibraryFileStatusFilter` types (28–29).
  - `matchMethodFilter` / `fileStatusFilter` state and handlers (411–412, 553–563).
  - `LibrarySelectFilter` component and the two `LibraryFilterBar` widgets that use it (241–271, 319–332).
  - Constants: `matchMethodFilters`, `fileStatusFilters`, `matchMethodLabels`, `fileStatusLabels`, `fileStatusTones`, `formatMatchMethod` (115–151, 196–202).
  - `filterLibraryTracks` (204–218).
  - Columns: `match_method`, `file_status`, and the `display` Actions column (lines 495–534).
  - `LibraryTrackActions` component (358–399) and the now-unused `useMutation` / per-row `rematchLocalTrack` wiring it depended on.
  - Now-unused imports: `Pill`, `PillTone`, `Clock3`, `Link2`, `Music2`, `LibraryFileStatus`. Keep `Unlink`, `RotateCcw`, `RefreshCw` — still used by the bulk action bar.
- [x] Wire link-status to DataTable filtering:
  - Add `const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])`.
  - `handleLinkStatusFilterChange(value)`: `setColumnFilters(value === "all" ? [] : [{ id: "link_status", value }])`. Drop manual `setRowSelection({})`.
  - `resetFilters` clears `columnFilters` and `bulkStatus`. Selection clearing comes from DataTable.
  - Pass `data={tracks}`, `columnFilters`, `onColumnFiltersChange={setColumnFilters}` to `<DataTable>`.
- [x] Replace the inline "Showing X of Y rows" header (`LocalLibraryView.tsx:677–682`) with `headerSlot`. Keep the `<h2>Local library track list</h2>` heading inside the slot.
- [x] Empty-state copy (`LocalLibraryView.tsx:716–722`) body: **"No tracks match the selected link-status filter."**
- [x] Row activation already wired via `onActivate={openTrackDetail}` (`LocalLibraryView.tsx:711`) plus `?detail=` URL param in `openTrackDetail` (442–449); after T1 lands, click + Enter both open the drawer with no further changes.
- [x] Update `LocalLibraryView.test.tsx`:
  - Drop stat-card assertions. Keep link-status chip + count assertions.
  - Drop "updates and resets library filter selections" branches that touch match-method / file-status. Keep link-status reset behaviour.
  - Drop `Match method` / `File status` filter assertions and the column assertions for `ISRC`, `Available`, `Beets failed`.
  - Add: clicking a body row opens the `LocalTrackDetailDrawer` (mirrors PlaylistView's drawer-open test).
  - Confirm Details/per-row Re-match buttons are absent.
  - Keep the existing bulk re-match and bulk unlink tests (T4 will expand them).
- [x] Update `App.test.tsx`:
  - Lines 566–576: drop `Library stats`, `Total tracks`, `Linked tracks`, `Pending tracks`, `Unlinked tracks`, `Match method`, `File status` assertions.
  - Line 596: replace `getByLabelText("Library stats")` with an assertion on a surface that survives (e.g. `getByRole("region", { name: "Library filters" })`).

**Definition of done:**
- `cd app-ui && npm run lint && npm test && npm run build` (full suite — App.test is cross-cutting).
- Bulk re-match still works for unlinked rows (T4 expands eligibility next).

## T4. Expand LocalLibrary bulk re-match eligibility to pending + unlinked

- [ ] Files: `app-ui/src/features/library/LocalLibraryView.tsx`, `app-ui/src/features/library/LocalLibraryView.test.tsx`.
- [ ] Replace `selectedUnlinkedTracks` (`LocalLibraryView.tsx:432–435`) with `selectedRematchableTracks = selectedTracks.filter((t) => t.link_status !== "linked")` (covers `pending` and `unlinked`).
- [ ] Bulk `Re-match` disabled when `selectedRematchableTracks.length === 0 || isBulkBusy`.
- [ ] Bulk `Unlink` unchanged: still gated by `selectedLinkedTracks` (rows with `final_link_id !== null`).
- [ ] `handleBulkRematch` defensively re-filters linked rows out of the worker input, keeps `settleInChunks(..., 5, ...)`, and aggregates success/failure counts unchanged. Reuses `POST /api/local-tracks/{id}/rematch` (`LocalLibraryView.tsx:58–68`).
- [ ] Mixed selection of `{ linked, pending }` enables both buttons; `Re-match` POSTs only the pending id, `Unlink` DELETEs only the linked row's final-link.
- [ ] Status copy: existing `"queued for matching"` covers both pending and unlinked attempts — no string change unless review surfaces a clarity issue.
- [ ] Tests (`LocalLibraryView.test.tsx`):
  - Add: selecting a single `pending` row enables `Re-match`, disables `Unlink`; click queues `POST /api/local-tracks/{pendingId}/rematch`.
  - Update "enables bulk actions only for compatible selected local rows": pending row now enables `Re-match`.
  - Add: mixed `linked + pending` selection enables both buttons; `Re-match` only fires for the pending id, `Unlink` only fires for the linked row's `final_link_id`.

**Definition of done:**
- `cd app-ui && npm run lint && npm test -- library/LocalLibraryView && npm run build`
