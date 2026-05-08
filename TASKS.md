# Beets Metadata Mirror And Link Proposal Comparison

Context:

- Replace the old tracker content with only this Beets metadata mirror work.
- Do not edit or stage unrelated local changes, especially the existing `app-ui/src/features/library/` files currently dirty in the worktree.
- Beets SQLite should be treated as an import/backfill source only. Runtime app flows, routers, and matchers should read from the main Postgres database.
- The mirror targets the pinned Beets dependency in `app/requirements.txt`: `beets==2.2.0`.
- Existing `local_tracks` remain app-owned identity/state rows and continue to link to Beets data through `beets_id`.

Locked decisions:

- Use a full typed Postgres mirror for fixed Beets 2.2.0 item and album fields.
- Store Beets flexible/plugin attributes in separate key/value tables.
- Keep Beets SQLite reads isolated to import and repair/backfill tooling.
- Use the mirrored Beets metadata for matching, proposal API responses, and local-vs-streaming comparison UI.
- Recommended landing order: T1 → T2 → T4 → T3 → T5a → T5b → T6 → T7. Backfilling first means matchers and proposals always see populated mirror rows for older imports.

Non-goals:

- No direct proposal endpoint reads from the Beets SQLite database.
- No runtime matcher dependency on `BEETS_LIBRARY`.
- No broad redesign of the local library or playlist UI outside the link proposal view.
- No Beets version upgrade as part of this work.
- No automatic deletion of stale `beets_items` mirror rows or stale `local_tracks` rows in v1. Surface them; do not act.
- No mobile-specific column hiding beyond the existing `md:` breakpoint.
- No proposal-row bulk approve/reject UI.
- No moving `BeetsImporter`'s sqlite reads (`app/app/ingestion/pipeline.py:133, 143`) off SQLite — they're how the importer learns the new beets_id.
- No re-run of matching against backfilled rows (existing `--enqueue-matching` flag stays as-is).

## T1. Add Beets mirror schema

- [x] New module `app/app/ingestion/beets_mirror.py` exporting a `metadata: MetaData` and four tables: `beets_items_table`, `beets_albums_table`, `beets_item_attributes_table`, `beets_album_attributes_table`.
- [x] Wire the new metadata into `app/app/schema.py:34` `_app_tables()`.
- [x] New Alembic revision under `db/versions/` (e.g. `b9c2f4a8e7d1_add_beets_mirror_tables.py`) with `down_revision = "9b7e3c2d1a4f"`.
- [x] `beets_items_table`: keyed by `beets_id` (PK, integer), with typed columns enumerated literally from `beets.library.Item._fields` in the pinned `beets==2.2.0`.
- [x] `beets_albums_table`: keyed by `beets_album_id` (PK, integer), with typed columns enumerated literally from `beets.library.Album._fields`.
- [x] `beets_item_attributes_table` and `beets_album_attributes_table`: `(id PK, entity_id INT NOT NULL, key TEXT NOT NULL, value TEXT, created_at, updated_at)` with `UNIQUE(entity_id, key)` and FK `entity_id → beets_items.beets_id` / `beets_albums.beets_album_id`.
- [x] Type mapping helper that maps `beets.dbcore.types.*` → SQLAlchemy column type via one switch:
  - string/path fields -> text
  - id/integer/padded integer fields -> integer
  - booleans -> boolean
  - duration/float/gain (`NULL_FLOAT`) fields -> float
  - Beets `DateType` fields -> timezone-aware timestamp
- [x] Preserve the existing `local_tracks.beets_id` column unchanged. Do not move app-owned state into the mirror tables.
- [x] Add a `test_beets_mirror_migration_matches_beets_field_set` test in `app/tests/test_migrations.py` that imports `beets.library.Item._fields` / `Album._fields` and asserts each fixed field name has a column in the migrated DB.

**Definition of done:**
- `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_migrations.py`

## T2. Add Beets metadata extraction and Postgres upsert service

- [x] New module `app/app/ingestion/beets_mirror_sync.py`. Locked API:
  - `@dataclass(frozen=True) class BeetsMirrorRow: beets_id: int; album_id: int | None; fixed_fields: dict[str, Any]; flex_attributes: dict[str, str]` (only `Item._fields` keys allowed in `fixed_fields`).
  - `@dataclass(frozen=True) class BeetsMirrorAlbumRow: beets_album_id: int; fixed_fields: dict[str, Any]; flex_attributes: dict[str, str]`.
  - `@dataclass(frozen=True) class BeetsMirrorCounts: items_inserted: int; items_updated: int; items_skipped: int; albums_inserted: int; albums_updated: int; albums_skipped: int; missing_in_beets: int; stale_items: int`.
  - `def read_item(sqlite_conn, beets_id: int) -> BeetsMirrorRow | None`.
  - `def read_album(sqlite_conn, beets_album_id: int) -> BeetsMirrorAlbumRow | None`.
  - `def iter_all_items(sqlite_conn) -> Iterator[BeetsMirrorRow]`.
  - `def iter_all_albums(sqlite_conn) -> Iterator[BeetsMirrorAlbumRow]`.
  - `def upsert_item(pg_conn, row: BeetsMirrorRow) -> Literal["inserted", "updated"]`.
  - `def upsert_album(pg_conn, row: BeetsMirrorAlbumRow) -> Literal["inserted", "updated"]`.
- [x] Move `_decode_beets_path` from `app/app/ingestion/repair.py:235` and `app/app/ingestion/pipeline.py:157` into this new module. Export as `decode_beets_path(raw_path: bytes | str) -> str` (drop the leading underscore — it's shared now).
- [x] Update both call sites in `repair.py` and `pipeline.py` to import from `app.ingestion.beets_mirror_sync` (one-line change each).
- [x] Read Beets SQLite `items`, `albums`, `item_attributes`, and `album_attributes` tables.
- [x] Map Beets fixed item/album fields into the typed Postgres mirror columns using the same type switch as T1.
- [x] Map flexible/plugin attributes into the key/value tables.
- [x] Idempotent upserts: `ON CONFLICT (beets_id) DO UPDATE` for items, `ON CONFLICT (beets_album_id) DO UPDATE` for albums; attributes replaced wholesale per entity (`DELETE WHERE entity_id = :id` then `INSERT`).
- [x] New tests file `app/tests/test_beets_mirror_sync.py`. Cover: round-trip read+write, attribute replacement on re-upsert, missing-row handling, type coercion for `DateType` / `PathType` / boolean / `PaddedInt`, bytes-with-surrogateescape and str path round-trips.

**Definition of done:**
- `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_beets_mirror_sync.py app/tests/test_ingestion.py`

## T4. Backfill existing records from Beets

- [x] Files: `app/app/ingestion/repair.py` (lines 30–62 wiring; existing `_iter_current_beets_items` at line 210 stays untouched). Add a new repair step `_repair_beets_mirror`.
- [x] Use `decode_beets_path` from `app.ingestion.beets_mirror_sync` (already moved there in T2) — do not re-add a local copy.
- [x] Add a dry-run / `--apply` backfill path that reads the current `BEETS_LIBRARY` SQLite database and mirrors all Beets item/album/attribute rows into Postgres via `beets_mirror_sync.upsert_item` / `upsert_album`.
- [x] All upserts run inside one `engine.begin()` block. Steps in order:
  1. Iterate all Beets items via `iter_all_items` chunked at 500; call `upsert_item` per chunk.
  2. Iterate all Beets albums via `iter_all_albums` chunked at 500; call `upsert_album`.
  3. Compute mirror-vs-source diff: `beets_items.beets_id NOT IN (current sqlite ids)` → report as `stale_mirror_items` (do not delete in v1).
  4. Compute `local_tracks.beets_id NOT IN (current sqlite ids)` → report as `stale_local_track_beets_ids` (do not delete in v1).
  5. Existing missing-`local_tracks` insertion (lines 166–207) stays unchanged.
- [x] Concurrency cap: chunk size 500 for attribute writes; single connection (repair runs single-threaded today — do not introduce parallelism).
- [x] Report stale `local_tracks.beets_id` values that no longer exist in Beets; do not delete them automatically.
- [x] Keep existing duplicate-track, stale-failure, zero-byte staging, and optional `--enqueue-matching` repair behavior intact.
- [x] New tests in `app/tests/test_ingestion.py` covering: dry-run vs apply, partial mirror (some items already in Postgres), stale-mirror detection, stale-local-track detection.

**Definition of done:**
- `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_ingestion.py app/tests/test_main.py`

## T3. Mirror metadata during import

- [x] Files: `app/app/ingestion/pipeline.py` (`IngestionProcessor.process` at lines 201–242), `app/tests/test_ingestion.py`.
- [x] After `BeetsImporter.import_file` returns at `pipeline.py:208`, open a sqlite read on `self.beets_importer.library_database` and call `beets_mirror_sync.read_item` / `read_album` then `upsert_item` / `upsert_album` against the Postgres engine.
- [x] Order: mirror upsert **before** `track_store.persist`, so the FK chain `local_tracks.beets_id → beets_items.beets_id` is always satisfied.
- [x] Wrap the new step in the same try/except as the existing import path, so failure paths still record `failed_ingestion_attempts`.
- [x] `BeetsImporter._fetch_imported_track` continues to read sqlite locally — only the post-import mirror upsert uses the new module.
- [x] Keep `local_tracks` schema unchanged. Do not duplicate the full Beets field set on `local_tracks`.
- [x] Preserve existing staging cleanup, failure recording, and matching enqueue behavior.
- [x] Extend existing successful-import tests in `test_ingestion.py` to assert one `beets_items` row + N `beets_item_attributes` exist and the album row exists.
- [x] Add a regression test: re-importing the same path updates the existing mirror row instead of creating a duplicate.

**Definition of done:**
- `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_ingestion.py`

## T5a. Move ISRC matching off Beets SQLite

- [x] Extend `app/tests/factories.py:24` `TestDataFactory` with shared helpers consumed by T5a, T5b, and T6:
  ```python
  def beets_item(
      self,
      *,
      beets_id: int,
      album_id: int | None = None,
      title: str | None = None,
      artist: str | None = None,
      album: str | None = None,
      isrc: str | None = None,
      length: float | None = None,
      **fixed_fields: Any,
  ) -> int: ...
  def beets_item_attribute(
      self, *, beets_id: int, key: str, value: str
  ) -> int: ...
  ```
  Insert into `beets_items_table` / `beets_item_attributes_table` via the existing `_insert` helper.
- [x] Files: `app/app/matching/isrc.py` (whole file, 93 LOC), `app/app/matching/pipeline.py:191–200` (drop `beets_library` arg from `IsrcMatcher` construction; **leave `TagMatcher` arg in place** — it's removed in T5b), `app/tests/test_matching_isrc.py` (335 LOC of fixture migration).
- [x] New `IsrcMatcher.__init__` signature: `__init__(self, *, database_url: str)` — drops `beets_library`.
- [x] Single Postgres query joining `local_tracks ⋈ beets_items` on `beets_id`, where `local_tracks.id = :id`, returning `beets_items.isrc`. If row missing or isrc null → return `None`.
- [x] Keep ISRC normalization (`_normalize_isrc`), confidence band, score (1.0), and streaming-track lookup unchanged.
- [x] Migrate `test_matching_isrc.py` to seed Postgres mirror rows via `factories.beets_item(...)` instead of `sqlite3.connect`. Remove the `import sqlite3` line at file top once all uses are gone.

**Definition of done:**
- `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_matching_isrc.py app/tests/test_matching_pipeline.py`

## T5b. Move tag matching off Beets SQLite and remove `BEETS_LIBRARY` from runtime

- [x] Reuses `factories.beets_item(...)` from T5a — no new test plumbing required.
- [x] Files: `app/app/matching/tags.py` (whole file, 233 LOC), `app/app/matching/pipeline.py:181–200` (drop `beets_library` from the `MatchingPipeline` dataclass + `__post_init__`), `app/app/matching/jobs.py:35–43` (remove env check + arg passthrough), `app/tests/test_matching_tags.py`, `app/tests/test_matching_pipeline.py`, `app/tests/test_worker.py`, `app/tests/test_main.py:175` (delete the now-redundant `delenv` if matching path no longer reads it).
- [x] New `TagMatcher.__init__` signature: `__init__(self, *, database_url: str)`.
- [x] Single Postgres query joining `local_tracks ⋈ beets_items` to fetch `title, artist, album, length` for the local track. Convert `length` (Beets seconds float) to ms via the existing `_normalize_duration_ms` logic.
- [x] Scoring functions (`_score_tags`, `_title_similarity`, `_token_similarity`, `_album_similarity`, weights, duration tolerance) remain identical.
- [x] Keep scoring, confidence bands, rejected-candidate exclusion, and candidate ordering unchanged.
- [x] All pipeline tests: replace `beets_library=tmp_path / "library.db"` calls with no-arg construction; seed `beets_items` rows via `factories.beets_item(...)` for any test that requires tag lookup data.
- [x] `BeetsImporter` retains its `BEETS_LIBRARY` env (`app/app/main.py:49`); only the matching pipeline / jobs path drops it.
- [x] After this task, `rg -n "BEETS_LIBRARY" app/app` should only match `main.py:49` (BeetsImporter wiring) and `ingestion/repair.py:22` (repair sync source).

**Definition of done:**
- `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_matching_tags.py app/tests/test_matching_pipeline.py app/tests/test_worker.py app/tests/test_main.py`

## T6. Expand proposals API with local metadata

- [x] Reuses `factories.beets_item(...)` from T5a in `test_links_router.py` for the existing list-proposals tests at lines 35 and 139.
- [x] Files: `app/app/links/router.py:55–126`, `app/app/links/models.py:6–18`, `app/tests/test_links_router.py`.
- [x] Extend `ProposalResponse` with `local_title: str | None`, `local_artist: str | None`, `local_album: str | None`. Keep `local_file_path: str` (always present, unchanged).
- [x] Add `LEFT OUTER JOIN beets_items ON beets_items.beets_id = local_tracks.beets_id` to the existing query at `router.py:77–92` and select `beets_items.title`, `beets_items.artist`, `beets_items.album` aliased as `local_title` / `local_artist` / `local_album`.
- [x] Pydantic `str | None` handles null safely — no SQL coalesce needed.
- [x] Preserve existing pending-only filtering, confidence-band filtering, final-link exclusion, ordering, approve, and reject behavior.

**Definition of done:**
- `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_links_models.py app/tests/test_links_router.py`

## T7. Compress link proposal UI with side-by-side comparison

- [x] Files: `app-ui/src/features/proposals/LinkProposalsView.tsx` (especially `ProposalGroupCard` at lines 259–316 and `ProposalCandidateRow` at lines 318–379), `app-ui/src/features/playlists/queries.ts:78–91` (extend `LinkProposal` type), `app-ui/src/features/proposals/LinkProposalsView.test.tsx` (extend fixture at lines 8–53; add comparison-rendering tests).
- [x] Extend the frontend `LinkProposal` type with `local_title: string | null`, `local_artist: string | null`, `local_album: string | null` to match `/api/proposals`. Update test fixtures.
- [x] Locked layout in `ProposalGroupCard`:
  - Replace the single "Local track" header (`LinkProposalsView.tsx:283–288`) with a 2-column grid: left = local fields (filename, title, artist, album), right = streaming fields (title, artist, album).
  - Use `grid-cols-1 md:grid-cols-2`. Each row uses `<dt>` label + `<dd>` value. Center divider on `md:`.
  - When local title / artist / album is null, render `—` in `text-ctp-overlay1` italic. Always render filename (always present).
- [x] In `ProposalCandidateRow`: drop the local restatement — only show streaming side, score, method, rank, actions. Local context lives in the group header.
- [x] Truncate with `truncate` on each `<dd>`. Preserve existing `aria-hidden` on the score meter.
- [x] Approve/reject mutation logic, optimistic cache, and error banners untouched (`LinkProposalsView.tsx:159–185`).
- [x] Test additions: render with all-three-local-fields-present (verify side-by-side), render with all-null-locals (verify dashes), render with one missing field, preserve approve+reject pending-state assertions.
- [ ] Manual review (replaces dropped T8): open `/proposals` in dev and verify rows with full Beets metadata, rows with only filename, and rows with multiple candidates render correctly; verify approve+reject pending states animate correctly.

**Definition of done:**
- `cd app-ui && npm run lint && npm test -- LinkProposalsView queries && npm run build`
