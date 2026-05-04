# E18 — General settings and configurable ingest folders

## Summary

Add **Settings > General** as the default settings page, with a simple ingest folder manager. The backend should persist ingest folders in the database, expose settings APIs, and update the active filesystem watcher immediately when folders are added or removed.

Docker Compose should use explicit host mounts:

- Host `/srv/mergerfs/hdds/music-in` -> container `/ingestion`
- Host `/srv/mergerfs/hdds/soulseek/downloads` -> container `/soulseek`
- Host `/srv/mergerfs/hdds/media/music` -> container `/music`
- Host `/docker/appdata/cratelynx` -> container `/data`

Processed/imported music must be stored under `/music` in the container. `/music` is the library output path, not an ingest input, to avoid re-ingesting files that Beets has already imported.

Application-owned data, including the Beets SQLite database, must be stored under `/data` in the container. Docker Compose should back `/data` with `/docker/appdata/cratelynx` on the host.

## API, data, and runtime behavior

- New table: `ingest_folders`
  - `id int primary key`
  - `path string not null unique`
  - `created_at datetime not null`
  - `updated_at datetime not null`
- Seed default ingest folders when the table is empty:
  - `/ingestion`
  - `/soulseek`
- Normalize paths with `Path(path).expanduser().resolve(strict=False)`.
- Accept only non-empty absolute container paths.
- Reject duplicate normalized paths with `409`.
- Create missing watched directories on watcher start/add.
- Settings APIs:
  - `GET /api/settings/general` -> `{ "ingest_folders": [{ "id": 1, "path": "/ingestion" }] }`
  - `POST /api/settings/ingest-folders` with `{ "path": "/soulseek" }` -> `201` folder object
  - `DELETE /api/settings/ingest-folders/{folder_id}` -> `204`
- If `DATABASE_URL` is unavailable, settings APIs return `503`; ingestion startup can still fall back to env defaults to preserve lightweight local behavior.

## Tasks

- [x] Inspect current settings routing, ingestion startup, watcher lifecycle, Docker Compose mounts, Beets library path usage, and API/store patterns; record side effects around container paths, host mounts, and live watcher updates
- [x] Update Docker Compose app configuration so `/ingestion`, `/soulseek`, `/music`, and `/data` map to the requested host directories, `LIBRARY_ROOT` defaults to `/music`, and `BEETS_LIBRARY` defaults to `/data/beets/library.db`
- [ ] Add an `ingest_folders` database model and Alembic migration with unique normalized `path`, created/updated timestamps, and seed defaults for `/ingestion` and `/soulseek`
- [ ] Add a backend settings store that lists, creates, deletes, normalizes, deduplicates, and validates ingest folders using absolute container paths
- [ ] Add settings schemas and API routes for `GET /api/settings/general`, `POST /api/settings/ingest-folders`, and `DELETE /api/settings/ingest-folders/{folder_id}`
- [ ] Refactor `IngestionWatcher` to manage multiple watched roots, schedule/unschedule roots live, create missing directories on watch start/add, and keep existing event handling behavior
- [ ] Wire app startup so ingestion loads persisted folders, seeds defaults when needed, uses `/music` for Beets imports, and keeps the active watcher synchronized after settings API mutations
- [ ] Add backend tests for route mounting, default folder seeding, `/music` library configuration, path validation, duplicate rejection, delete behavior, multi-root watcher scheduling, live add/remove synchronization, and fallback behavior without `DATABASE_URL`
- [ ] Add frontend settings query/mutation helpers and stable query keys for general settings and ingest folder mutations
- [ ] Add a `GeneralSettingsView` with a folder list, icon-only remove buttons, an add-folder text field, loading/error/empty states, and mutation status feedback
- [ ] Update settings navigation so `/settings` and the topbar settings button land on General, while YouTube Music sync remains available at `/settings/sync/youtube-music`
- [ ] Update frontend tests for settings redirects, sidebar settings items, General page rendering, add-folder POST payloads, delete calls, query invalidation, and YouTube Music settings navigation
- [ ] Update README ingestion docs to explain configurable ingest folders, the default `/ingestion` and `/soulseek` inputs, `/music` as the processed library output, and Docker host mount requirements
- [ ] Run relevant validation: backend `ruff check .`, `ruff format --check .`, targeted `pytest`; frontend `npm run lint`, `npm test`, and `npm run build`

## Side effects to handle

- Removing an ingest folder stops watching for new files but does not cancel an import already in progress.
- Adding a path that is not host-mounted creates/watches a directory inside the container, which may not be useful; document this clearly.
- Multiple watched folders can process files through the same `IngestionProcessor`; existing unique staging filenames reduce basename collision risk.
- `/music` must not be seeded as an ingest folder, because Beets moves completed imports there.
- Existing references to `/library` should remain test-local unless they represent runtime defaults; production defaults should move to `/music`.

## Inspection notes

- Settings routing is currently frontend-only. `/settings` and `/settings/sync` redirect to `settings-sync-youtube-music`; the topbar settings button also opens the YouTube Music sync view, and the settings sidebar has a single `YouTube Music sync` item.
- There is no backend settings package or settings router yet. Existing backend route modules use `create_router(require_database_url=...)`, response schemas, store classes, and `503` guards from `app.main.require_database_url`.
- App startup creates one `IngestionProcessor` and one `IngestionWatcher` rooted at `INGESTION_ROOT` with default `/ingestion`. The watcher starts during FastAPI lifespan and stops on shutdown.
- `IngestionWatcher` supports only one root. `start()` creates that root with `mkdir(parents=True, exist_ok=True)`, schedules one Watchdog handler, and does not retain schedule handles for live unscheduling.
- The ingestion event handler processes closed files synchronously through the shared `IngestionProcessor`; removing a watched root later will only affect new events, not an in-flight processor call.
- Beets import defaults were `/library`: `LIBRARY_ROOT` defaulted to `/library`, `BEETS_LIBRARY` defaulted to `library_root / "library.db"`, and compose mapped named volume `library_data` to `/library`.
- Docker Compose previously mapped named volumes only: `library_data:/library` and `ingestion_data:/ingestion`. There was no `/soulseek`, `/music`, or `/data` mount.
- Runtime `/library` defaults also appear in M3U export, links, rescue, streaming, and ingestion code paths. Test fixtures also use `/library`; later tasks should change runtime defaults without rewriting unrelated test-local expectations.
- Local track persistence stores paths relative to `library_root`, so moving production `LIBRARY_ROOT` to `/music` should preserve relative database values if Beets paths stay under that root. The Beets database itself belongs under `/data`, not `/music`.
- Migration/model patterns are split between SQLAlchemy ORM models in `db/models.py` for Alembic and lightweight table definitions in app stores/models; `updated_at` commonly uses `server_default=func.now()` and ORM `onupdate=func.now()`.
- Frontend data access uses per-feature `queries.ts` files with `fetchJson`, exported query key factories, and TanStack Query hooks. Settings helpers should follow that pattern and invalidate both general settings and any affected ingest-folder keys after mutations.
- README still describes dropping files into `ingestion/` and asks for `LIBRARY_ROOT`; it needs explicit host mount guidance and clear wording that `/music` is output only.

## Assumptions

- Ingest folder changes apply live without backend restart.
- The API accepts only absolute container paths.
- Settings are persisted in the application database.
- Initial ingest folders are `/ingestion` and `/soulseek`; `/music` is output only.
