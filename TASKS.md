# tasks.md

Audit-driven cleanup backlog. Originating audit files (`claudeaudit.md`, `codexaudit.md`)
have been retired; their findings live here, verified against the codebase.

Tasks are roughly ordered by impact — correctness/data integrity first, polish last.
Each task is sized to fit comfortably in one Codex 5.5-xhigh context window.

---

## Locked decisions (apply across tasks)

- **Streaming track uniqueness key** (T2): `provider_track_id` only. The `streaming_tracks` table has no `account_id` column — the original audit's `(account_id, provider_track_id)` hint was wrong.
- **Ingestion idempotence direction** (T3): direction 1 — make persistence idempotent on `beets_id`. Simpler than quarantining sources; `beets_id` uniqueness is reliable per beets's own model.
- **Async-route conversion** (T8): convert `async def` → `def` rather than `run_in_threadpool`. No async I/O happens in those routes today.
- **Library pagination** (T6): cursor-based, sorted by `local_tracks.id ASC`. Default 100, max 500. No filtering or sorting in v1.
- **Cache invalidation rule** (T12): `delayedInvalidate` only after mutations that trigger backend jobs whose effect lands asynchronously (e.g., RQ-backed sync endpoints). Otherwise immediate.
- **Duplicate streaming title in proposal rows**: kept as intentional UX. Header summarizes the row; comparison field shows the local-vs-streaming pairing. Tests assert it (`LinkProposalsView.test.tsx:162, :213`, `App.test.tsx:654`). Not a task.

---

## Verification notes (corrections to the original audits)

- `create_engine()` is in **17 files / 20 calls**, not 37 (audit overcount). Concern still stands.
- `LIBRARY_ROOT` setenv duplicates exist in **2 files** (`test_links_router.py`, `test_main.py`), not 3. `test_beets_mirror_backfill.py` doesn't use it.
- View duplications confirmed: `final_links_view` × 3, `suggested_links_view` × 2, `beets_items_view` × 2 (verified — see T17).
- Zero `Index()` declarations across `app/app/` or `db/versions/` (verified — T2).
- The "TanStack Table column defs recreated each render" finding was wrong: `LocalLibraryView.tsx:216-289` and `PlaylistView.tsx:133-151` already wrap in `useMemo`.
- The "`PlaylistTrackActions.tsx` is dead code" finding was wrong: imported at `PlaylistView.tsx:16`, rendered at `:194`.
- The `repair.py` `print()` complaint was wrong: it already uses `logging`. Only `beets_mirror_backfill.py` needs the fix (T15).
- The `optimisticMutation` factory finding originally listed 3 sites; only 2 are real (`LinkProposalsView.tsx` approve + reject). `PlaylistView.tsx` and `LocalLibraryView.tsx` use `Promise.allSettled` + post-hoc invalidation, not optimistic-cache (T11).

---

## - [x] T1. Tighten crypto, validate at startup, narrow ingestion exceptions

**Why**: Three related error-handling weaknesses:
- `app/app/streaming/crypto.py` raises only on first `encrypt_token`/`decrypt_token` call. The app boots fine without `TOKEN_ENCRYPTION_KEY` and fails later on user auth — confusing failure mode, easy to miss in deploy validation.
- Fernet key initialization is duplicated between `encrypt_token` and `decrypt_token` (`crypto.py:8-31`).
- `app/app/ingestion/pipeline.py:235-247` and `app/app/ingestion/repair.py:260` catch `Exception` broadly and either re-raise without context or return `None`, losing diagnostic information.

**Files**: `app/app/streaming/crypto.py` (31 LOC, full rewrite); `app/app/main.py` (lifespan, `:29-79`); `app/app/ingestion/pipeline.py:235-247`; `app/app/ingestion/repair.py:260`.

**Approach**:
- `crypto.py`: extract `_get_fernet() -> Fernet` helper; both `encrypt_token` and `decrypt_token` call it. Raise a new `TokenEncryptionKeyError(RuntimeError)` instead of generic `RuntimeError` so callers can match cleanly. Export `validate_token_encryption_key()` that runs `_get_fernet()` once and discards.
- `main.py` lifespan: call `crypto.validate_token_encryption_key()` at startup. Skip the check if `TOKEN_ENCRYPTION_KEY` is unset *and* `DATABASE_URL` is unset (current behavior — accounts table won't be touched).
- `pipeline.py`: narrow `except Exception` to expected types (`subprocess.CalledProcessError`, `ValueError`, `FileNotFoundError`, beets-specific exceptions). `logger.exception(...)` before re-raise.
- `repair.py:260`: same narrowing treatment.

**Definition of done**: New `test_main.py` tests cover missing-key and malformed-key boot failure (both raise `TokenEncryptionKeyError`). Logs include traceback context for each handled failure. No behavioral change for happy paths. `cd app && ruff check . && ruff format --check . && pytest tests/test_crypto.py tests/test_ingestion.py tests/test_main.py`.

---

## - [x] T2. Schema integrity: indexes + unique constraints + migration

**Why**: Two correctness/perf gaps share one migration:
- Concurrent sync jobs can create duplicate rows. `streaming_playlists.provider_playlist_id` and `streaming_tracks.provider_track_id` are bare columns; the store does select-then-insert at `app/app/streaming/store.py:262` and `:573`.
- Zero `Index()` declarations exist across `app/app/` or `db/versions/`. Postgres does not auto-index FKs. Joins through `final_links`, `suggested_links`, `playlist_membership`, `streaming_playlists.account_id` are sequential scans today — fine on dev, cliff at 100k+ rows.

**Files**: `app/app/streaming/models.py:43-67`; `app/app/streaming/store.py:250-360, 564-615`; `app/app/local_tracks/store.py`; `app/app/links/store.py`; `app/app/matching/pipeline.py`; single new Alembic migration in `db/versions/`.

**Approach** — unique constraints (locked):
- `streaming_playlists` → `UniqueConstraint("account_id", "provider_playlist_id")`.
- `streaming_tracks` → `UniqueConstraint("provider_track_id")` (no `account_id` column on this table).
- Replace select-then-insert in `streaming/store.py` with `sqlalchemy.dialects.postgresql.insert(...).on_conflict_do_update(...)`. Postgres-specific.

**Approach** — indexes (fixed inventory):
- `local_tracks(fingerprint)` — ingestion repair lookups.
- `local_tracks(beets_id)` — joined to mirror.
- `streaming_tracks(isrc)` — ISRC matching.
- `playlist_membership(playlist_id)`, `(streaming_track_id)`.
- `final_links(streaming_track_id)` (already unique on `local_track_id`).
- `suggested_links(local_track_id, status)`, `(streaming_track_id)`.
- Add `Index(...)` next to each `Table(...)` declaration; one migration runs `op.create_index(...)` for everything. No `CONCURRENTLY` in dev — flag in the migration's docstring that prod operators should run `--sql` and switch to `CREATE INDEX CONCURRENTLY` if rolling against a populated DB.

**Definition of done**: Migration applies cleanly. Concurrent upsert test (two threads upserting same provider IDs) produces a single row. `cd app && ruff check . && pytest tests/test_streaming_accounts.py tests/test_migrations.py`. Manually run `EXPLAIN` on `/library/tracks` and `/playlists/{id}/tracks` against a seeded dev DB; paste output into the PR description.

---

## - [x] T3. Make ingestion idempotent

**Why**: In `app/app/ingestion/pipeline.py:212-233`, beets import happens before mirror, persist, enqueue, and source cleanup. A crash between import (`:212`) and source cleanup (`:233`) leaves the source file in place — the watcher re-ingests on next pass and can produce duplicate `local_tracks`.

**Files**: `app/app/ingestion/pipeline.py:205-247`; `app/app/local_tracks/store.py` (persist method); new Alembic migration in `db/versions/`.

**Approach** (locked direction 1):
- Add `UniqueConstraint("beets_id")` on `local_tracks` (one local track ↔ one beets row).
- In `LocalTrackStore.persist`, use `INSERT ... ON CONFLICT (beets_id) DO UPDATE SET fingerprint=EXCLUDED.fingerprint, ... RETURNING id`.
- Source cleanup at `pipeline.py:233` becomes safe to retry.

**Definition of done**: New `test_ingestion.py` test simulates a mid-pipeline crash followed by retry on the same source path; asserts a single `local_tracks` row. Existing ingestion tests pass. `cd app && pytest tests/test_ingestion.py tests/test_migrations.py`.

---

## - [x] T4. Fix tag-matching N+1

**Why**: `app/app/matching/tags.py:69-117` loads every streaming track into Python and scores in-memory — `O(local × streaming)`. Fine on dev fixtures; cliff at scale.

**Files**: `app/app/matching/tags.py`; new migration to enable `pg_trgm` extension.

**Approach**: `CREATE EXTENSION IF NOT EXISTS pg_trgm` in a new migration. Use trigram similarity (`title % :query`) to prefilter candidates SQL-side, returning ~50-100 candidates per local track. Score the small candidate set in Python as today. Alternative if pg_trgm setup is painful: precompute normalized `title_norm`/`artist_norm` columns and filter SQL-side.

**Definition of done**: Benchmark on 5k local × 50k streaming shows order-of-magnitude reduction in match time. Quality of matches unchanged on existing fixtures. `cd app && pytest tests/test_matching_tags.py tests/test_migrations.py`.

---

## - [x] T5. Fix playlist-tracks triple-scan

**Why**: `/playlists/{id}/tracks` at `app/app/streaming/router.py:210` calls `get_playlist_detail()` (which iterates `list_playlist_tracks()` to compute counts), then `:216` calls `list_playlist_tracks()` again. Frontend separately requests detail. Three scans per request on large playlists.

**Files**: `app/app/streaming/router.py:203-218`; `app/app/streaming/store.py:384-407`.

**Approach**: Replace the `get_playlist_detail()` existence check at `router.py:210` with a cheap `select(streaming_playlists_table.c.id).where(...).scalar_one_or_none()`. Don't change `get_playlist_detail`'s signature — it's still used by `:197`. If counts surface elsewhere, use SQL aggregation (`COUNT(*)`) instead of materializing the track list.

**Definition of done**: Endpoint issues at most one `playlist_membership` scan per request; response shape unchanged. `cd app && pytest tests/test_main.py -k playlist_tracks`.

---

## - [ ] T6. Paginate library listing

**Why**: `app/app/library/store.py:51-137` runs an unbounded 7-table outer join with no `LIMIT`/`OFFSET`. Fine today, dies at large libraries.

**Files**: `app/app/library/store.py`; `app/app/library/router.py`; `app-ui/src/features/library/LocalLibraryView.tsx`.

**Approach** (locked):
- Cursor-based pagination, sorted by `local_tracks.id ASC`. Default limit 100; max 500.
- Split `LibraryStore.list_tracks()` into `list_tracks_page(cursor, limit) -> LibraryTracksPage` + `compute_stats() -> LibraryStatsRecord`. Stats summary stays unpaginated (returns full counts).
- Router accepts `?cursor=&limit=`.
- Frontend uses TanStack Query `useInfiniteQuery`.

**Non-goals**: no filtering, no sorting beyond `id`. Those are future tasks.

**Definition of done**: Library page loads paginated. Tests cover empty, single-page, multi-page, end-of-list. `cd app && pytest tests/test_main.py -k library`. `cd app-ui && npm run lint && npm test && npm run build`.

---

## - [ ] T7. Set TanStack Query defaults

**Why**: `app-ui/src/main.tsx:8` instantiates `new QueryClient()` with no `defaultOptions`. Default `staleTime` is `0` so every component remount refetches — unnecessary network chatter.

**Files**: `app-ui/src/main.tsx` only.

**Approach** (locked): `new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, gcTime: 5 * 60_000 } } })`. Queries that need fresher data (job-status polling) keep their per-query overrides — audit them.

**Definition of done**: Devtools show fewer network requests on tab/page navigation; no stale-data UX regressions. `cd app-ui && npm test`.

---

## - [ ] T8. Centralize SQLAlchemy engine, inject via Depends, drop blocking async

**Why**: Three coupled problems on the same files:
- 17 `create_engine()` call sites. Each Store class instantiates its own engine in `__init__`, so connection-pool isolation is per-store — multiplies pool exhaustion risk under load.
- `require_database_engine` + lazy `create_engine` block is copy-pasted across 3 routers (`matching/router.py:22-46`, `links/router.py`, `rescue/router.py`).
- `app/app/library/router.py:17`, `maintenance/router.py:18`, `settings/router.py:30` are `async def` but call sync SQLAlchemy code that blocks the event loop.

**Files**: new `app/app/core/db.py`; `app/app/main.py:29-79`; every `*/store.py` (`local_tracks`, `streaming`, `links`, `library`, `maintenance`, `matching`, `rescue/metadata`, `settings`, `ingestion/failures`, `ingestion/beets_mirror_backfill`, `m3u/generator`); `app/app/{matching,links,rescue,library,maintenance,settings}/router.py`; `app/tests/conftest.py` fixture wiring.

**Approach**:
- `core/db.py` exposes module-level `get_engine() -> Engine` that pulls from `app.state` (set during lifespan startup).
- All 6 routers move to `engine: Engine = Depends(get_engine)`.
- `library/maintenance/settings` routes drop `async def` → `def` (FastAPI runs sync routes in a threadpool).
- Every Store's `__init__` accepts `engine: Engine`; remove `create_engine` calls inside.
- Retire the duplicated `require_database_engine` blocks in `matching/links/rescue` routers.
- Update `conftest.py:31` to pass the migrated engine into Store fixtures.

**Definition of done**: `grep -rn "create_engine" app/app/` returns 1 (only `core/db.py`). Event loop no longer blocks during library/maintenance/settings calls. Existing tests pass after fixture wiring update. `cd app && ruff check . && pytest`.

---

## - [ ] T9. End-to-end type safety: response_model → OpenAPI → openapi-typescript → fetchJson + zod

**Why**: Four tightly coupled gaps that all touch the same boundary code — doing them separately means re-touching the same 2 feature files three times:
- `app/app/streaming/router.py` returns raw `dict[str, object]`; `app/app/links/router.py` already uses typed Pydantic responses. Inconsistent.
- Frontend types are hand-maintained (`app-ui/src/features/streamingAccounts/queries.ts`, etc.). Backend Pydantic models are the source of truth — manual sync drifts silently.
- `app-ui/src/lib/api.ts:5-13` blindly casts JSON to `T` with no validation.
- `fetchJson()` only wraps GET. Mutations across `app-ui/src/features/playlists/queries.ts:172-225` and `streamingAccounts/queries.ts:46-82` reimplement headers, JSON serialization, and `response.ok` checks inline.
- `serialize_playlist_track()` at `app/app/streaming/router.py:129-142` has one caller — folds in cleanly here.

**Files**:
- Backend: `app/app/streaming/router.py:44-218`; audit `app/app/system/router.py`; new `app/app/openapi_export.py` CLI module.
- Build: new `scripts/generate-types.sh`; `app-ui/package.json` codegen script.
- Frontend: generated `app-ui/src/lib/api-types.ts` (committed); `app-ui/src/lib/api.ts`; migrate `app-ui/src/features/streamingAccounts/queries.ts` and `app-ui/src/features/playlists/queries.ts`.

**Approach**:
- Backend: add `response_model=...` to every streaming route. Replace dict construction with Pydantic instances. Inline the one-call `serialize_playlist_track`.
- Codegen: small CLI in `app/app/openapi_export.py` (`from app.main import app; print(app.openapi())`). Build script writes `openapi.json`, then `npx openapi-typescript openapi.json -o app-ui/src/lib/api-types.ts`. Single `npm run codegen` script. CI lint runs codegen then `git diff --exit-code app-ui/src/lib/api-types.ts` to fail on staleness.
- Frontend `api.ts`: add `postJson<T>`, `patchJson<T>`, `deleteJson<T>` (or `request<T>(method, url, body)` + thin wrappers). Each accepts an optional zod schema and parses on the way out; default no-op if no schema passed.
- Migrate `streamingAccounts/queries.ts` + `playlists/queries.ts` to use the new helpers + generated types + zod.

**Non-goals** (v1 scope): do NOT migrate `library`, `maintenance`, `proposals`, `localTracks`, `settings` features in this task — they keep hand-written types. Each becomes its own future cleanup task.

**Definition of done**: `grep -n "dict\[str, " app/app/streaming/router.py` returns 0. All streaming routes have `response_model`. `streamingAccounts/queries.ts` and `playlists/queries.ts` import from `lib/api-types.ts`. No raw `fetch()` calls remain in those two files. CI fails when types are stale. Bogus payloads surface as parse errors instead of late `undefined` crashes. `cd app && pytest && cd ../app-ui && npm run lint && npm test && npm run build`.

---

## - [ ] T10. Codify connection-context rule

**Why**: `.connect()` vs `.begin()` are used interchangeably across stores (e.g., `app/app/matching/pipeline.py`). No documented rule.

**Files**: docstring in `app/app/core/db.py` (depends on T8) or `CLAUDE.md`; spot-fix obvious misuses found during the audit pass.

**Approach**: Document the rule — `.begin()` for any code path that mutates, `.connect()` for read-only queries. Add a banner to `core/db.py`. Audit `app/app/` for misuses; fix any clearly wrong.

**Definition of done**: Rule documented in `core/db.py` or CLAUDE.md. Review pass over `app/app/` confirms compliance. `cd app && pytest`.

---

## - [ ] T11. Extract shared frontend helpers to lib/

**Why**: Three duplicated patterns across feature files:
- `settleInChunks` is identical in 5 files: `features/playlists/PlaylistView.tsx:63`, `features/playlists/PlaylistSyncConfiguration.tsx:48`, `features/library/LocalLibraryView.tsx:58`, `features/maintenance/UnidentifiedView.tsx:33`, `features/maintenance/MissingLocallyView.tsx:55`.
- Formatters `formatPlaylistTimestamp`, `getLocalTrackLabel`, `getMatchMethodLabel`, `formatDuration` are scattered across `features/proposals/LinkProposalsView.tsx:154-197`, `features/playlists/PlaylistSyncConfiguration.tsx:28-34`, etc.
- `onMutate` / `onError` / `onSettled` cache-restore pattern repeats at `LinkProposalsView.tsx:202-221` (approve + reject — 2 mutations, same shape).

**Files**:
- New: `app-ui/src/lib/settleInChunks.ts`, `app-ui/src/lib/formatters.ts`, `app-ui/src/lib/optimisticMutation.ts`.
- Consumers: 5 files for settleInChunks, scattered consumers for formatters, `LinkProposalsView.tsx` for the optimistic factory.

**Approach**:
- `settleInChunks`: move once, replace 5 imports. No behavioral change; all 5 sites already use chunks of 5 with `Promise.allSettled`. Keep that as the bulk-action concurrency cap.
- Formatters: pull each function into `lib/formatters.ts`; consolidate variants where equivalent; document any genuine differences in inline comments.
- `createOptimisticMutation()` factory: accepts `mutationFn`, `queryKey`, `optimisticUpdate`, `revertOnError`; returns a `useMutation` config. Migrate the 2 mutations in `LinkProposalsView.tsx`. `PlaylistView.tsx` and `LocalLibraryView.tsx` use `Promise.allSettled` + post-hoc invalidation, NOT optimistic-cache — out of scope here.

**Definition of done**: `grep -rln "settleInChunks" app-ui/src/` shows the helper file plus 5 consumers. Each formatter has one canonical implementation. Optimistic boilerplate removed at `LinkProposalsView.tsx:202-221`. `cd app-ui && npm run lint && npm test && npm run build`.

---

## - [ ] T12. Standardize cache invalidation

**Why**: Some sites use feature-level helpers (`invalidateStreamingAccountMutationQueries`); others inline 2-3 `queryClient.invalidateQueries()` calls. `Topbar.tsx:120-125` uses `delayedInvalidate` while `PlaylistSyncConfiguration.tsx:136-151` does not despite a similar workflow.

**Files**: `app-ui/src/features/shell/Topbar.tsx`; `app-ui/src/features/playlists/PlaylistSyncConfiguration.tsx:136-160`; audit other features.

**Approach** (locked rule): `delayedInvalidate` is required after a mutation that triggers a backend job whose effect lands asynchronously (RQ-backed sync endpoints). Otherwise immediate `invalidateQueries`. Pull each feature's invalidation list into `<feature>/queries.ts` (where the keys live). Document the rule as a comment above `useDelayedInvalidate`. Audit all `invalidateQueries` call sites against the rule.

**Definition of done**: Each feature uses a single invalidation pattern; rule for delayed vs immediate documented. Manual smoke: trigger a streaming-sync, confirm playlist detail re-renders after the worker completes. `cd app-ui && npm test && npm run build`.

---

## - [ ] T13. A11y on PlaylistTrackActions popover

**Why**: Popover at `app-ui/src/features/playlists/PlaylistTrackActions.tsx:42-50` lacks ESC dismiss, `aria-modal`, and focus trap.

**Files**: `app-ui/src/features/playlists/PlaylistTrackActions.tsx`.

**Approach**: Use the existing dialog/popover primitive (check `app-ui/src/components/` first) or add ESC handler + focus-trap + `aria-modal="true"` directly.

**Definition of done**: Keyboard dismiss works; screen reader announces modal correctly. Existing tests pass. `cd app-ui && npm test`.

---

## - [ ] T14. Test infra overhaul: testcontainers + conftest cleanup + m3u coverage

**Why**: Three test-infra issues converge on `conftest.py`:
- `app/tests/conftest.py:25` uses SQLite. Schema features (CHECK constraints, partial unique indexes, FK ON DELETE) silently differ from prod — T2 (uniqueness) and T3 (idempotence) cannot be tested under SQLite.
- `monkeypatch.setenv("LIBRARY_ROOT", ...)` repeats across `test_links_router.py` (3 sites) and `test_main.py` (2 sites).
- `test_m3u_generator.py` only has 2 tests; missing coverage for empty playlists, all-unlinked playlists, and approval-triggered regeneration.

**Files**: `app/tests/conftest.py`; `app/tests/test_links_router.py`; `app/tests/test_main.py`; `app/tests/test_m3u_generator.py`; `requirements-dev.txt`.

**Approach**:
- Add `testcontainers-python` to dev deps. Provide a session-scoped Postgres container fixture; existing per-test fixture creates a fresh schema inside it. Keep SQLite as a fallback for ultra-fast unit tests if migration tests are too slow.
- Module-level `library_root` fixture in `conftest.py`; remove the 5 duplicates.
- Add `test_m3u_generator.py` cases for empty playlists, all-unlinked playlists, approval-triggered regeneration.

**Sequencing note**: Land before T2/T3 if possible so those tasks can include real Postgres tests at landing time. If sequenced after, T2/T3 should explicitly note "Postgres-specific tests deferred until T14 lands."

**Definition of done**: `grep -rn 'setenv("LIBRARY_ROOT"' app/tests/` shows only the conftest entry. Migration and schema tests run against Postgres. Coverage report shows added m3u paths exercised. `cd app && pytest`. CI time acceptable.

---

## - [ ] T15. Logging standardization

**Why**: Two adjacent gaps:
- `app/app/matching/jobs.py:run_matching_pipeline` doesn't include `job_id` or `local_track_id` in log records, so worker output can't be correlated with an enqueue.
- `app/app/ingestion/beets_mirror_backfill.py:51-56` uses `print()` while the rest of the backend uses `logging`. Operator output is inconsistent and not capturable.

**Files**: `app/app/matching/jobs.py`; `app/app/matching/pipeline.py`; `app/app/ingestion/beets_mirror_backfill.py`.

**Approach**:
- `LoggerAdapter` (or `structlog.bind`) at job entry with `job_id` + `local_track_id`; pass through to downstream calls in `matching/pipeline.py`.
- `beets_mirror_backfill.py`: module-level logger; configure CLI entry to set `INFO` level on stdout. Replace `print()` with `logger.info(...)`.

**Definition of done**: Worker logs show both IDs on every line emitted by a job. `grep -n "print(" app/app/ingestion/beets_mirror_backfill.py` returns 0. Tools emit standard log lines; behavior unchanged for users running them. `cd app && pytest tests/test_beets_mirror_backfill.py tests/test_worker.py`.

---

## - [ ] T16. Deployment & ops polish

**Why**: Four small deployment-time gaps:
- Hardcoded `/tmp/crate-lynx-*` staging dirs in `app/app/main.py:34-35` and `app/app/m3u/generator.py`.
- `DEFAULT_INGEST_FOLDER_PATHS = ("/ingestion", "/soulseek")` in `app/app/settings/models.py` must stay in sync with `docker-compose.yml:53-58` mounts by hand. Drift = silent breakage.
- `docker-compose.yml:57-60` hardcodes `/srv/mergerfs/...` host paths — non-portable.
- Only Postgres has a compose healthcheck; the API doesn't.

**Files**: `app/app/main.py`; `app/app/m3u/generator.py`; `app/app/settings/models.py`; `docker-compose.yml`; `.env.example` (new or extended).

**Approach**:
- Read staging dir from env (`CRATE_LYNX_STAGING_DIR`); default to `/tmp/...`.
- Add banner comments in `settings/models.py` and `docker-compose.yml` cross-referencing each other (lower-effort than env-driven defaults).
- Use `${VAR:-default}` syntax in compose with documented `.env.example` for host paths.
- Add `/healthz` endpoint to `main.py` returning `{"ok": true}` plus a DB ping; add `healthcheck:` to the api compose service.

**Definition of done**: `docker-compose ps` shows `(healthy)` for the api service. Staging dir override works. Fresh clone with documented `.env` builds and runs. Deployment to gluesoup-1 unchanged. `cd app && pytest`.

---

## - [ ] T17. Backend code-quality cleanup: f-strings, view consolidation, migration safety

**Why**: Three small backend hygiene items:
- `app/app/ingestion/beets_mirror_sync.py:144, 154` interpolates `table_name` into SQL via f-string. Not a vulnerability (callers are internal, args are string literals) but ugly.
- `final_links_view` is defined in 3 places (`local_tracks/store.py:41`, `streaming/store.py:50`, `matching/pipeline.py:54`); `suggested_links_view` in 2 (`local_tracks/store.py:48`, `streaming/store.py:56`); `beets_items_view` in 2 (`matching/tags.py:29`, `matching/isrc.py:9`). These are SQLAlchemy `table()` literals (not Postgres views) — name the new module accordingly.
- `db/versions/f8a3d2c1b0e4_remove_non_audio_failed_ingestion_attempts.py:32-33` has empty `pass` downgrade after destructive delete; `9b7e3c2d1a4f_remove_streaming_fingerprints_and_acoustic_suggestions.py:20-31` cannot restore original `match_method` values. Rolling back loses data silently.

**Files**: `app/app/ingestion/beets_mirror_sync.py`; new `app/app/core/tables.py` (name reflects SQLAlchemy literals, not DB views); 5 consumer files; the 2 cited migrations.

**Approach**:
- f-strings: split into two functions (`_fetch_one_item`, `_fetch_one_album`) instead of parameterized table name. Or use module-level constants if one-function reads cleaner.
- Move all duplicated `table()` literals into `app/app/core/tables.py`. Stores import from there.
- Migration downgrades: replace empty `pass` with `raise NotImplementedError("downgrade is destructive; restore from backup")` for both cited migrations. Best-effort reverse migration is not worth the complexity here.

**Definition of done**: `grep -rn "= table(" app/app/` returns only definitions in `core/tables.py`. No string-formatted table names in SQL. Each migration's downgrade either works or fails loudly. `cd app && pytest`.

---

## - [ ] T18. Replace `as number | string` casts in frontend

**Why**: `app-ui/src/features/library/LocalLibraryView.tsx:46-56` and `features/playlists/queries.ts:160-161` use repeated unsafe casts that hide bugs if upstream guards break.

**Files**: `app-ui/src/features/library/LocalLibraryView.tsx:46-56`; `app-ui/src/features/playlists/queries.ts:160-161`.

**Approach**: Replace casts with proper type guards (`typeof x === "number"` etc.). If T9 has reached these features, drop the casts entirely in favor of generated types. Otherwise ship runtime guards now.

**Definition of done**: No `as number | string` casts remain in those files. `cd app-ui && npm run lint && npm test && npm run build`.
