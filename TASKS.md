# Tasks

Codebase audit findings from 2026-05-05, ordered by recommended execution sequence. Each task preserves the original evidence, reasoning, and validation steps so it can be picked up cold.

Severity labels are the original Codex labels, revised where my own investigation disagreed.

---

## Phase 1 — Quick wins

Self-contained, low-risk PRs. Land these first; several of them remove offenders that show up again in the foundational tasks below.

---

### [x] Task 1.1 — Remove search functionality entirely

**Severity:** N/A (decision: delete rather than fix)
**Source:** Codex finding 4 (originally "wire sidebar search to real routes"), superseded by user decision that search has no value in its current form.

**Original problem statement (kept for context):**
- Backend returns hard-coded `route_path` values `"/youtube-music"` and `"/local-library"` (`app/app/search/router.py:58,92,120`) that don't exist in the frontend route table (`App.tsx:92–99`: `/library`, `/missing`, `/proposals`, `/settings`, `/settings/sync/youtube-music`, `/unidentified`, plus dynamic `/playlists/:id`).
- The result `<button>` in `Sidebar.tsx:183–199` has no `onClick`.
- The test only asserts that the result strings render (`App.test.tsx:1471–1533`), so this is not caught.

**Removal checklist:**

Backend:
- Delete `app/app/search/` (router.py, schemas.py, __init__.py, __pycache__).
- Remove the import + `app.include_router(create_search_router(...))` call in `app/app/main.py:17,112`.
- Delete `test_search_endpoint_returns_playlist_streaming_and_local_matches` in `app/tests/test_main.py:528+` and the `/api/search` assertion at `test_main.py:77`.

Frontend:
- Delete the `SearchPanel` component, `fetchSearchResults`, `useDebouncedValue`, `searchKindLabels`, the `Search` icon import, and the `<SearchPanel />` mount in `app-ui/src/features/shell/Sidebar.tsx` (lines 1–18, 20–34, 128–207, ~255–256). Prune now-unused `useQuery`/`useState`/`useEffect` imports.
- Delete `SearchResult` and `SearchResponse` from `app-ui/src/features/shell/types.ts:15–25`.
- Delete the `"debounces sidebar search requests…"` test at `app-ui/src/App.test.tsx:1471–1533` and any `/api/search` branches in `mockPlaylistFetch`.
- Drop `searchField` / `searchFrame` style entries from `componentClasses` if they have no other consumers.

**Why this goes first:** removes one of the per-request `create_engine` offenders (helps Task 2.2), eliminates one duplicated `fetchJson` clone (helps Task 1.4), and shrinks `Sidebar.tsx` ahead of the route registry work (Task 3.1).

**Validation:** `pytest && npm test && npm run build`.

---

### [x] Task 1.2 — Fix the `change-me` Fernet default

**Severity:** High
**Source:** Codex finding 2.

**Evidence:**
- `docker-compose.yml:50` defaults `TOKEN_ENCRYPTION_KEY` to `change-me`. `app/app/streaming/crypto.py:14–16` rejects anything that isn't a valid 32-byte url-safe base64 Fernet key, so the first call to encrypt or decrypt raises `RuntimeError`.
- `.env.example:4` is similarly broken (`replace-me-with-a-fernet-key`). README only says "fill in TOKEN_ENCRYPTION_KEY" with no hint about generation.
- Same compose file ships `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-crate_lynx}` — weak credential default, but at least functional.

**Impact:** `docker-compose up` can look healthy, then fail when creating or decrypting streaming accounts.

**Recommendation:**
- Drop the default in `docker-compose.yml` so startup hard-fails with a clear message.
- In `.env.example`, show the exact generation command as a comment: `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`. Or add a `scripts/gen-fernet-key.sh` helper.
- Reference it from README.

**Validation:** `source .venv/bin/activate && pytest db/test_crypto.py app/tests/test_streaming_accounts.py -q`.

---

### [x] Task 1.3 — Update stale docs

**Severity:** Low
**Source:** Codex finding 8.

**Evidence:**
- `README.md:96` says "React app is not yet scaffolded — these commands will be available once E09 is complete."
- `app-ui/README.md:5–10` says "Until the React app is added, the build emits a small placeholder page."
- Reality: `app-ui/src/` has a real Vite/React/Tailwind/TanStack Query app with 1500-line tests and a built `dist/`.

**Impact:** New contributors get wrong setup expectations.

**Recommendation:**
- Rewrite `app-ui/README.md` to describe the current Vite/Tailwind/Catppuccin/TanStack Query setup and the validation commands from `AGENTS.md:34–39`.
- Drop the "not yet scaffolded" note in the root README.

**Validation:** docs-only; optionally rerun `npm run build`.

---

### [x] Task 1.4 — Centralize `fetchJson` into a shared API client

**Severity:** Low
**Source:** Codex finding 7.

**Evidence:** Identical `fetchJson` helper duplicated in:
- `app-ui/src/features/playlists/queries.ts:139`
- `app-ui/src/features/settings/queries.ts:22`
- `app-ui/src/features/library/queries.ts:37`
- `app-ui/src/features/maintenance/queries.ts:44`

(A fifth copy in `Sidebar.tsx` as `fetchSearchResults` will already be gone after Task 1.1.)

**Impact:** Inconsistent errors, headers, and future auth/retry behavior.

**Recommendation:** add `app-ui/src/lib/api.ts` exporting `fetchJson` and a tiny `endpoints` builder. Trivial refactor; reduces change cost for future API work.

**Validation:** `npm test && npm run build`.

---

### [x] Task 1.5 — Move `db/test_crypto.py` into the backend test tree

**Severity:** Medium
**Source:** Additional finding (Codex missed).

**Evidence:** `db/test_crypto.py` is the only test under `db/` and isn't picked up by `pytest` from the project root unless you cd or pass the path explicitly. Codex's "validation" command in finding 2 (`pytest db/test_crypto.py app/tests/test_streaming_accounts.py`) implicitly works around this.

**Recommendation:** move it to `app/tests/test_crypto.py`, or configure `pyproject.toml`/`pytest.ini` `testpaths` so default `pytest` covers it.

**Validation:** `pytest` from project root should discover and run it without an explicit path argument.

---

## Phase 2 — Foundational refactors

Do these before further feature work. They unblock cleaner future development and remove a class of recurring bugs.

---

### [x] Task 2.1 — Consolidate schema authority + add Alembic-driven test fixture

**Severity:** High
**Source:** Codex findings 1 + 6 + additional finding A — these are one structural problem and should land together.

**Evidence (finding 1 — Alembic metadata drift):**
- `db/env.py:33` points Alembic at `db.models.Base.metadata` (a single declarative `Base`).
- The running app **does not use `db.models` at all**. Every feature module declares its own `MetaData()` and `Table(...)`s on it:
  - `app/app/streaming/models.py:23`
  - `app/app/matching/pipeline.py:34`
  - `app/app/settings/models.py:11`
  - `app/app/ingestion/failures.py:20`
  - `app/app/local_tracks/store.py:19`
  - `app/app/links/store.py:6`
- None feed into `Base.metadata`. The `selected_for_sync` mismatch is only the most visible symptom — `db/models.py:80–146` already lacks fingerprint columns the app removed in migration `9b7e3c2d1a4f` and never updated for. Autogenerate today would propose to drop `ingest_folders` etc., because `db.models` doesn't know about them.
- The migration that adds `selected_for_sync` lives at `db/versions/bc4c3e1785d7_add_selected_for_sync_to_playlists.py:20`. The app table at `app/app/streaming/models.py:43` has it. The ORM model at `db/models.py:105` `StreamingPlaylist` does not.

**Evidence (finding 6 — test fixture duplication):**
- Backend `conftest.py` is nearly empty (8 lines of sys.path setup).
- Every router/store test individually does `local_tracks_metadata.create_all(engine)` + `streaming_metadata.create_all(engine)` + `links_metadata.create_all(engine)` etc.:
  - `test_links_router.py:30–32,136–138,254–257,330+`
  - `test_m3u_generator.py:23–25,141–143`
  - `test_rescue_metadata.py:27–29`
- Adding any new module metadata means hand-editing N test files. This duplication compounds finding 1 — it's why the drift was never caught by the suite.

**Evidence (additional A — schema authority confusion is structural):**
Because feature modules define `Table` against private `MetaData()` instances and only Alembic migrations use `op.create_table(...)`, the *only* source of truth for "what columns does production have" is the migration history. The two parallel definitions (`db/models.py` ORM + `app/app/*/models.py` Core tables) just create surface area for them to drift. Pick one.

**Impact:** future autogenerate work may propose incorrect schema changes; DB/test setup using `db.models` will not match production; new schema columns can land in production without a corresponding test failure.

**Recommendation:** choose one schema authority. Two options:
- **(a)** Make `db/models.py` the single declarative source and have feature modules import its `Table` objects.
- **(b)** Drop `db/models.py` entirely; build `target_metadata` in `env.py` by importing each feature's `metadata` and combining them. Matches the way the app already organizes code — preferred.

Then add a `conftest.py` fixture that creates a tmp SQLite engine and runs Alembic to head. Delete per-test `create_all` calls. This single change closes the drift gap, removes the duplicated bootstrapping, and gives you a test that fails immediately if a future migration disagrees with the table definitions.

**Validation:** `source .venv/bin/activate && pytest app/tests/test_migrations.py -q` plus the full backend suite.

---

### [x] Task 2.2 — Lifespan-scoped engine + dependency-injected stores

**Severity:** Medium
**Source:** Codex finding 3 + additional finding C (folds into the same refactor).

**Evidence (finding 3 — async + per-request engines):**
- `app/app/streaming/router.py:131` uses `async def` and instantiates `StreamingAccountStore`, whose constructor creates an engine at `app/app/streaming/store.py:64`.
- Per-request `create_engine` calls show up in many places, not just three:
  - `app/app/links/router.py:45,105,175,212` (four handlers)
  - `app/app/matching/router.py:23`
  - `app/app/rescue/router.py:21`
- Stores instantiated inside handlers also build engines: `app/app/streaming/router.py:131,140,153,165,178,188`.
- All handlers are `async def`, so blocking psycopg calls hold the event loop. `create_engine` itself is cheap (lazy pool), but you also lose all connection reuse.

**Evidence (additional C — m3u generator builds engines twice per call):**
- `app/app/m3u/generator.py:29,97` each `create_engine` for short reads, called from approve/reject/break-link handlers in `links/router.py` after work that already opened an engine. Folding M3U regeneration onto the shared engine introduced here removes the duplication for free.

**Impact:** avoidable pool churn and event-loop blocking as traffic grows.

**Recommendation:**
- Initialize a single `Engine` (and the stores that wrap it) in the `lifespan` block in `app/app/main.py:28`.
- Inject via FastAPI dependencies (`Depends(get_engine)`).
- Make handlers `def` (sync) — Starlette will run them in a threadpool — or move to async drivers. Plain `def` is the smaller change and fits the existing psycopg sync code.
- Update `m3u/generator.py` to accept the injected engine instead of building its own.

**Validation:** `source .venv/bin/activate && pytest app/tests/test_main.py app/tests/test_links_router.py -q`.

---

## Phase 3 — Higher-risk refactors

Bigger surface area. Tackle once Phase 2 is stable.

---

### [x] Task 3.1 — Extract a route/view registry and split `App.tsx`

**Severity:** Medium
**Source:** Codex finding 5.

**Evidence:**
- `app-ui/src/App.tsx` is 452 lines and owns: nav-item builders for every section (`buildPlaylistNavItems`, `buildMaintenanceNavItems`, `buildLibraryNavItems`, `buildSettingsNavItems`), the route ↔ viewId map (`staticViewRoutes` at line 92), `PlaylistView` itself (line 183+), and `ViewShell`'s long ternary chain (`App.tsx:298–312`).
- Adding views or changing routes requires editing one large component and broad tests.

**Impact:** central coupling point; broad test-file blast radius for small feature additions.

**Recommendation:** the `staticViewRoutes` map plus the `ViewShell` ternary is begging to become a registry: `{ id, path, render: () => Component, navItem: () => NavItem }[]`. Each feature owns its entry. `App.tsx` becomes ~80 lines of routing/layout. Move `PlaylistView` and `ViewShell` rendering into per-feature modules.

**Validation:** `npm test && npm run build`.

---

### Task 3.2 — Frontend mock-API helper + reusable backend builders

**Severity:** Medium
**Source:** Codex finding 6 (second half — frontend portion + reusable backend builders not covered by Task 2.1's Alembic fixture).

**Evidence:**
- `app-ui/src/App.test.tsx:278+` contains `mockPlaylistFetch`, a 250-line hand-written URL router; nothing reusable.
- Backend route tests repeatedly create engines and metadata, e.g. `app/tests/test_main.py:106`. Task 2.1 handles the metadata bootstrapping; this task handles the rest of the per-test boilerplate (e.g. fixture builders for streaming accounts, playlists, tracks, links).

**Impact:** tests pass, but fixtures are costly to extend and encourage implementation-detail assertions.

**Recommendation:**
- Add `app-ui/src/test/mockApi.ts` with a builder API; let feature tests register only the endpoints they care about.
- Add backend test data builders (e.g. `app/tests/factories.py`) for common entities, paired with the Alembic fixture from Task 2.1.

**Validation:** full backend and frontend suites.

---

## Miscellaneous cleanup

Trivial; can be folded into any unrelated PR touching the file.

---

### Task M.1 — Remove unused imports in `streaming/router.py`

**Severity:** Low
**Source:** Additional finding D (Codex missed).

**Evidence:** `app/app/streaming/router.py:1` imports `os` and `Path` that aren't used (left over from prior refactors).

**Recommendation:** `ruff --fix` would catch it. Either run that or delete the lines manually.

**Validation:** `ruff check .`.

---

## Notes on sequencing

- **Task 1.1 (search removal) goes first.** It removes one of the per-request `create_engine` offenders (helps 2.2), kills one `fetchJson` clone (helps 1.4), and shrinks `Sidebar.tsx` ahead of 3.1.
- **Tasks 1.1–1.5 are all independent** of each other and can be parallelized across PRs if useful.
- **Task 2.1 unblocks 2.2:** the Alembic-driven test fixture makes it safer to refactor engine ownership without losing test coverage of schema-touching code paths.
- **Task 3.1 should land after 1.1** so the route/view registry doesn't have to account for the search panel.
- **Task 3.2 depends on 2.1** for the backend half (its fixtures sit on top of the Alembic-driven setup).
