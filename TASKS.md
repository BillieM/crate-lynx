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

Non-goals:

- No direct proposal endpoint reads from the Beets SQLite database.
- No runtime matcher dependency on `BEETS_LIBRARY`.
- No broad redesign of the local library or playlist UI outside the link proposal view.
- No Beets version upgrade as part of this work.

## T1. Add Beets mirror schema

- [ ] Files: Alembic migration under `db/versions/`, app schema/table definitions, migration tests.
- [ ] Add `beets_items`, keyed by `beets_id`, with typed columns matching fixed `beets.library.Item._fields` from `beets==2.2.0`.
- [ ] Add `beets_albums`, keyed by `beets_album_id`, with typed columns matching fixed `beets.library.Album._fields`.
- [ ] Add `beets_item_attributes` and `beets_album_attributes` for flexible/plugin attributes.
- [ ] Preserve the existing `local_tracks.beets_id` relationship and do not move app-owned state into the mirror tables.
- [ ] Use deterministic type mapping:
  - string/path fields -> text
  - id/integer/padded integer fields -> integer
  - booleans -> boolean
  - duration/float/gain fields -> float
  - Beets date/timestamp fields -> timezone-aware timestamp
- [ ] Add useful uniqueness/lookup constraints for Beets ids and attribute keys.

**Definition of done:**
- `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_migrations.py`

## T2. Add Beets metadata extraction and Postgres upsert service

- [ ] Files: new or existing ingestion/Beets metadata module plus focused tests.
- [ ] Read Beets SQLite `items`, `albums`, `item_attributes`, and `album_attributes`.
- [ ] Map Beets fixed item/album fields into the typed Postgres mirror columns.
- [ ] Map flexible/plugin attributes into key/value tables.
- [ ] Decode Beets path/blob values consistently with existing import code.
- [ ] Make upserts idempotent: repeated imports/backfills update existing mirror rows and replace stale attributes for that Beets item/album.
- [ ] Return/report counts for inserted, updated, skipped, missing, and stale rows.

**Definition of done:**
- `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_ingestion.py`

## T3. Mirror metadata during import

- [ ] Files: `app/app/ingestion/pipeline.py`, `app/app/local_tracks/store.py`, ingestion tests.
- [ ] Extend `BeetsImporter.import_file` to identify the imported item and capture enough metadata for the mirror upsert.
- [ ] Upsert the imported Beets item, its album, and flexible attributes into Postgres after successful Beets import.
- [ ] Persist `local_tracks` with the existing app fields and `beets_id`; do not duplicate the full Beets field set on `local_tracks`.
- [ ] Preserve existing staging cleanup, failure recording, and matching enqueue behavior.

**Definition of done:**
- `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_ingestion.py`

## T4. Backfill existing records from Beets

- [ ] Files: `app/app/ingestion/repair.py` or a dedicated repair subcommand, plus repair tests.
- [ ] Add a dry-run/apply backfill path that reads the current `BEETS_LIBRARY` SQLite database and mirrors all Beets item/album/attribute rows into Postgres.
- [ ] Use existing `local_tracks.beets_id` values to associate current app rows with mirrored Beets items.
- [ ] Insert missing `local_tracks` for Beets items that are present in the library but absent from the app DB.
- [ ] Report stale `local_tracks.beets_id` values that no longer exist in Beets; do not delete them automatically.
- [ ] Keep existing duplicate-track, stale-failure, zero-byte staging, and optional matching-enqueue repair behavior intact.

**Definition of done:**
- `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_ingestion.py app/tests/test_main.py`

## T5. Move matching off Beets SQLite

- [ ] Files: `app/app/matching/isrc.py`, `app/app/matching/tags.py`, `app/app/matching/pipeline.py`, `app/app/matching/jobs.py`, matching tests.
- [ ] Refactor ISRC matching to read `isrc` from `beets_items` through `local_tracks.beets_id`.
- [ ] Refactor tag matching to read title, artist, album, and duration from `beets_items`.
- [ ] Remove matcher-time `BEETS_LIBRARY` requirements and constructor arguments.
- [ ] Keep scoring, confidence bands, rejected-candidate exclusion, and candidate ordering unchanged.
- [ ] Update tests so they seed Postgres mirror rows instead of creating Beets SQLite fixtures.

**Definition of done:**
- `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_matching_isrc.py app/tests/test_matching_tags.py app/tests/test_matching_pipeline.py app/tests/test_worker.py`

## T6. Expand proposals API with local metadata

- [ ] Files: `app/app/links/router.py`, `app/app/links/models.py`, proposal tests.
- [ ] Join proposal records from `suggested_links` -> `local_tracks` -> `beets_items` and `streaming_tracks`.
- [ ] Return local filename/path plus nullable local title, artist, and album.
- [ ] Preserve existing pending-only filtering, confidence-band filtering, final-link exclusion, ordering, approve, and reject behavior.
- [ ] Use null-safe fallbacks for local tracks without mirrored Beets metadata.

**Definition of done:**
- `source .venv/bin/activate && ruff check . && ruff format --check . && pytest app/tests/test_links_models.py app/tests/test_links_router.py`

## T7. Compress link proposal UI

- [ ] Files: `app-ui/src/features/proposals/LinkProposalsView.tsx`, `app-ui/src/features/playlists/queries.ts`, proposal/query tests.
- [ ] Extend the frontend `LinkProposal` type and fixtures with local metadata fields from `/api/proposals`.
- [ ] Render proposal candidates as compact rows with score, match method, rank, and actions in a tighter layout.
- [ ] Show side-by-side local vs streaming comparison:
  - file name vs title
  - artist vs artist
  - album vs album
- [ ] Preserve approve/reject optimistic cache behavior and mutation error states.
- [ ] Keep text truncated within compact rows and preserve accessible button names.

**Definition of done:**
- `cd app-ui && npm run lint && npm test -- LinkProposalsView queries && npm run build`

## T8. Final validation

- [ ] Confirm `rg -n "sqlite3\\.connect" app/app` only finds import/backfill Beets synchronization code, not matchers or proposal/runtime query paths.
- [ ] Confirm matching jobs no longer require `BEETS_LIBRARY`.
- [ ] Run backend checks:
  - `source .venv/bin/activate && ruff check . && ruff format --check . && pytest`
- [ ] Run frontend checks:
  - `cd app-ui && npm run lint && npm test && npm run build`
- [ ] Manually review the proposal view with representative rows:
  - complete Beets metadata
  - missing local artist/album
  - multiple candidates for one local track
  - approve and reject pending states
