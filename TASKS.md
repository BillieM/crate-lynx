# E16 — Backend-backed library & maintenance views

- [x] Add backend library read models and `GET /api/library/tracks`
  - Follow the existing FastAPI patterns used by `app/app/streaming/router.py`, `app/app/streaming/store.py`, and `app/app/streaming/schemas.py`.
  - Return one row per `local_tracks` record with `id`, `title`/display filename, `artist`, `album`, `duration_ms`, `file_path`, and `library_root_rel_path` fields where available from existing data.
  - Derive `link_status` from existing link tables: `linked` when a `final_links` row exists, `pending` when a pending `suggested_links` row exists, and `unlinked` otherwise.
  - Return `match_method` from the relevant pending or approved suggestion when available; otherwise return `null`.
  - Keep `file_status` conservative: use `available` for persisted local tracks unless this task explicitly adds a reliable filesystem existence check.
  - Add focused backend tests for linked, pending, unlinked, and no-match rows.
  - Run the relevant backend validation for the changed backend files: `ruff check .`, `ruff format --check .`, and targeted `pytest`.

- [x] Add backend library stats using the same status derivation as the track list
  - Prefer returning `{ "stats": ..., "tracks": ... }` from the library track endpoint if that avoids duplicate queries and keeps the frontend simpler.
  - Include total, linked, pending, and unlinked counts.
  - Ensure stats and row statuses are produced from the same query logic or helper so they cannot drift.
  - Add backend tests that prove the counts match the returned row statuses.
  - Run the relevant backend validation for the changed backend files: `ruff check .`, `ruff format --check .`, and targeted `pytest`.

- [x] Add backend Missing Locally report endpoint with aggregated playlist usage
  - Confirm there is no existing endpoint that already provides this report before adding a new route.
  - Add `GET /api/maintenance/missing-locally` following the existing router/store/schema structure.
  - Return one row per missing `streaming_tracks` record, not one row per playlist membership.
  - Define "missing locally" as a streaming track with no `final_links` row.
  - Aggregate playlist usage into `playlist_count` and `playlist_titles` so a track that appears in multiple playlists is shown once.
  - Do not add priority/severity fields; there is no priority system.
  - Add backend tests covering tracks in one playlist, tracks in multiple playlists, and tracks with final links that should be excluded.
  - Run the relevant backend validation for the changed backend files: `ruff check .`, `ruff format --check .`, and targeted `pytest`.

- [x] Decide and document the Unidentified data source before wiring the view
  - Inspect whether existing persisted data can support "Beets-failed tracks with filename and fingerprint hash"; do not rely on static frontend fixtures.
  - Account for the current ingestion behavior: failures are currently exposed through recent in-memory `/ingest/status` entries and may not have durable `local_tracks` rows.
  - Choose one concrete path before implementation: persistent failed-ingestion records, a narrowed existing-data definition of unidentified tracks, or a recent-only view based on ingest status.
  - Document the chosen behavior in `TASKS.md` or the relevant code/tests before implementing follow-up wiring.
  - If this task changes backend behavior or documentation, run the relevant backend validation for the files touched.
  - Decision: implement Unidentified as persistent failed-ingestion records in a follow-up backend task before wiring the frontend view.
  - Rationale: current `local_tracks` rows are only created after fingerprinting and a successful Beets import, so they cannot represent Beets-failed imports. Current `/ingest/status` failure entries are recent-only in-memory records and only include `source_path` plus `error`; they are not durable and do not reliably expose a fingerprint or backend-compatible local track ID for rescue.
  - Expected backend contract: persist failed ingestion attempts with filename/source path, failure reason, failed-at timestamp, and fingerprint when fingerprinting succeeded before the failure. Rescue must remain hidden or disabled for rows without a real persisted local track ID/final link compatible with the existing rescue endpoint.

- [x] Add frontend query helpers for library and maintenance reports
  - Follow the existing `app-ui/src/features/playlists/queries.ts` pattern for typed responses, fetch helpers, query keys, and `useQuery` hooks.
  - Add library query keys for the library track/stats payload.
  - Add maintenance query keys for the Missing Locally payload and, after the data-source decision, the Unidentified payload.
  - Keep the existing rescue mutation pointed at the existing rescue endpoint unless the backend route changes.
  - Add focused frontend query tests that assert the exact API paths and error handling.
  - Run the relevant frontend validation for the changed frontend files: targeted `npm test`, `npm run lint`, and `npm run build`.

- [x] Wire the Local Library view to backend data
  - Replace hardcoded library stats and track fixtures with the new library query data.
  - Preserve the existing route, navigation, loading, error, empty, disabled, and pending UI states.
  - Keep filters client-side for now using the fetched rows unless backend filtering becomes necessary.
  - Make the stats cards use backend counts instead of fixture values.
  - Update frontend tests to mock backend payloads rather than asserting static fixture data.
  - Run the relevant frontend validation for the changed frontend files: targeted `npm test`, `npm run lint`, and `npm run build`.

- [x] Wire the Missing Locally view to backend data
  - Replace hardcoded missing-track fixtures with the new Missing Locally query data.
  - Render aggregated playlist usage per row as playlist names and/or `N playlists`, not as a single misleading playlist field.
  - Keep row labels focused on useful metadata: title, artist, album, duration, streaming ID, affected playlists, and last checked/synced timestamp if available.
  - Do not reintroduce priority/severity pills or implied "Streaming only" / "No local match" pills.
  - Update frontend tests to cover one-playlist and multi-playlist rows from mocked backend payloads.
  - Run the relevant frontend validation for the changed frontend files: targeted `npm test`, `npm run lint`, and `npm run build`.

- [x] Wire the Unidentified view after the data-source decision is complete
  - Replace hardcoded unidentified fixtures with the chosen backend or ingest-status data source.
  - Ensure every Rescue button uses a real backend-compatible local track ID; if the chosen data source cannot support rescue, hide or disable rescue with a truthful state.
  - Preserve loading, error, empty, disabled, pending, success, and failure states.
  - Update frontend tests to mock the chosen data source and the existing rescue endpoint.
  - Run the relevant validation for the changed files: backend checks if an API/data-source changed, frontend targeted `npm test`, `npm run lint`, and `npm run build`.

- [x] Replace hardcoded Library and Maintenance sidebar badges with backend-backed counts
  - Replace the static Library, Unidentified, and Missing Locally badge values in the app shell.
  - Reuse query data already loaded for the views where practical, or add small count queries only if needed.
  - Preserve existing playlist navigation and playlist badge behavior.
  - Update app shell tests to assert badges come from mocked backend data.
  - Run the relevant frontend validation for the changed frontend files: targeted `npm test`, `npm run lint`, and `npm run build`.

- [x] Clean up stale shell scripts and keep only supported manual workflows
  - Keep `scripts/ingest-track.sh`; ingestion is still file-drop based, and this script remains a useful wrapper for copying a local track into the Docker ingestion volume.
  - Keep `scripts/ytm-setup.sh`, but update it to call the current API path: `POST /api/streaming/accounts`.
  - Delete stale/manual test scripts that duplicate backend/UI coverage or call old non-`/api` paths: `scripts/ytm-test.sh`, `scripts/matching-test.sh`, `scripts/links-test.sh`, and `scripts/m3u-test.sh`.
  - Before deleting scripts, search `README.md`, `app/README.md`, `EPICS.md`, `TASKS.md`, and any command docs for references to those scripts or their old paths, then remove or update those references.
  - Preserve the actual tested behavior in unit/integration tests where it is still product, setup, or operational behavior; do not keep shell scripts just to exercise endpoints manually.
  - Run targeted validation for changed files. If only scripts/docs change, use shell syntax checks where practical and any relevant existing backend tests for touched API setup paths.

- [x] Remove unused matching debug endpoints if no active workflow depends on them
  - Candidate endpoints: `GET /api/matching/status` and `POST /api/matching/tracks/{local_track_id}/run`.
  - Current UI does not call either endpoint. First-run matching is enqueued directly after ingestion, and the product rerun action uses `POST /api/local-tracks/{local_track_id}/rematch`.
  - `GET /api/matching/status` exposes raw `suggested_links` rows across statuses; it overlaps with `GET /api/proposals`, which is the product queue and should return pending proposals only.
  - `POST /api/matching/tracks/{local_track_id}/run` enqueues matching without clearing pending suggestions; this is a lower-level debug/admin primitive, not the desired user-facing flow.
  - Remove the route handlers and route-mount assertions if the decision is to delete them.
  - Remove only tests that exist solely to prove those HTTP endpoints are exposed. Keep lower-level matching coverage for `MatchingPipeline`, `MatchingJobEnqueuer`, ingestion-triggered matching enqueue, rejected-pair blocking, and rematch behavior.
  - If an explicit admin/debug workflow is still needed, keep the endpoints but document them as operational/admin-only and update naming/routes consistently instead of leaving them as product-looking APIs.
  - Run relevant backend validation: `ruff check .`, `ruff format --check .`, and targeted `pytest` for matching, main route registration, and any deleted endpoint tests.

- [x] Remove unused ingest status endpoint and in-memory status plumbing if it has no consumer
  - Candidate endpoint: `GET /ingest/status`.
  - Current UI does not call it, scripts do not call it, and Docker healthcheck uses `GET /health` instead.
  - The endpoint currently exposes recent in-memory ingestion status and queue depths. This is not durable state, and the Unidentified maintenance view now uses persistent failed-ingestion records rather than recent `/ingest/status` failures.
  - Remove `app/app/ingestion/router.py` and the `include_router(ingestion_router)` mount if no remaining route is needed there.
  - Audit `IngestionStatusStore` and `app.state.ingestion_status`: if their only remaining consumer is the removed endpoint, remove the store wiring from `app/app/main.py` and keep ingestion failure persistence/tests focused on durable failed-ingestion records.
  - Keep ingestion processor tests that verify real behavior: prepare/transcode, fingerprint, Beets import, `local_tracks` persistence, matching job enqueue, cleanup, and durable failed-attempt persistence.
  - Keep `GET /health`; it is used by `docker-compose.yml` as the backend service healthcheck.
  - Run relevant backend validation: `ruff check .`, `ruff format --check .`, and targeted `pytest` for ingestion, main route registration, worker/queue depth only if still touched, and maintenance unidentified behavior.

- [x] Normalize local-track action API paths
  - Move metadata rescue from `POST /local-tracks/{local_track_id}/rescue` to `POST /api/local-tracks/{local_track_id}/rescue`.
  - Rationale: rescue is a user-facing action used by the Unidentified view, and `rematch` already lives at `POST /api/local-tracks/{local_track_id}/rematch`; keeping one local-track action outside `/api` is inconsistent.
  - Update frontend rescue calls in `app-ui/src/features/maintenance/queries.ts` and related tests.
  - Update backend route registration and route path tests.
  - Decide whether to keep a temporary compatibility route at the old path. Prefer removing the old path unless there is an external caller.
  - Run relevant validation for changed files: backend route tests, frontend maintenance query/view tests, `ruff check .`, `ruff format --check .`, targeted `npm test`, and frontend lint/build if frontend code changes.
