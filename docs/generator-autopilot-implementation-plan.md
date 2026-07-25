# Generator evolution and autopilot implementation plan

Status: implementation contract for the July 2026 delivery.

## Baseline and boundaries

- Baseline: clean `origin/main` at `7743e6e97fc7f1e31cc1c106b21e933391a03f06`.
- Runtime: one private Docker Compose stack on `gluesoup-0-docker`, with FastAPI
  and RQ workers in `app`, Postgres 16, Redis 7, and the React/Nginx UI.
- Generated playlists remain disposable immutable snapshots. This work does not
  add track moving, merge/split/pin/exclude controls, or a manual playlist editor.
- Existing move-based ingestion remains destructive after a successful import.
  This work does not add source archiving or lossless preservation.
- Manual Soulseek acquisition keeps one approval. Full unattended acquisition is
  a separate, explicit per-playlist opt-in and never weakens corruption or extreme
  mismatch checks.
- Existing `sync_mode` keeps its current match/export meaning. Automation intent
  is stored separately so migration defaults cannot begin downloading.

## Contract map

### Persistence and migration

One additive Alembic migration will:

1. Add `automation_level` to `streaming_playlists`, constrained to `off`,
   `sync_only`, `assist`, or `full`, with `off` as the migration-safe default.
2. Add named `playlist_generation_recipes` containing stable name, source filter,
   generation config, enabled/regenerate flags, optional export profile/config,
   last-run references, and timestamps.
3. Extend generation runs with nullable recipe, human-readable run name, trigger,
   analyzer/fallback evidence, and readiness/skipped summaries without changing
   snapshot immutability.
4. Add a singleton `autopilot_settings` row for the global pause switch, schedule,
   quiet period, concurrency/download/storage caps, and bounded retry policy.
5. Add compact `autopilot_runs` and `autopilot_run_items` audit records for
   idempotency, decisions, counts, failures, and review reasons.
6. Extend Soulseek candidates/acquisitions only with operational evidence needed
   to separate identity confidence from transfer quality and to verify unattended
   imports. Existing rows and manual flows remain valid.

The migration will be idempotent at the application/job level, use foreign keys
and uniqueness constraints for replay protection, and include a complete
downgrade. `app/app/schema.py` and migration parity tests remain authoritative.

### Generator pipeline

The generator will expose four separate functions and persisted evidence:

1. **Understand**: versioned Librosa acoustic descriptors plus a benchmarked,
   optional learned semantic embedding. The chosen model must have a compatible
   licence, a pinned checksum/version, deterministic window sampling, persistent
   per-track caching through the existing feature record, bounded retries, and an
   explicit descriptor-only degraded state when unavailable.
2. **Group**: robustly normalised acoustic and semantic groups with group-level
   weighting. Genre/style metadata is never a cluster input. Missing evidence
   reduces and explains confidence instead of being silently imputed as fact.
3. **Sequence**: an independent intent (`smooth_mix`, `rising_energy`,
   `warm_up_to_peak`, or `varied_listening`) using reliable tempo family, energy,
   diversity/repetition, and harmonic evidence only when supported.
4. **Name**: stable cluster-intrinsic evidence. Specific normalised style tags may
   assist only with strong cluster-wide agreement and agreement with acoustic
   evidence; generic, contradictory, duplicated, or weak tags are ignored.

The real preview runs the actual in-memory generator without persisting a run. It
returns proposed names, sizes, representative tracks, boundary/outlier tracks,
coverage, cohesion/confidence, skipped reasons, warnings, and leaf/export scope.
Readiness gates require enough ready tracks and useful coverage before persistence.

Named recipes can be created, edited, listed, deleted, regenerated against the
latest eligible library, and referenced by a stable human-readable run name.
Exports default to leaves/individually selected playlists so a parent and all of
its children are not redundantly emitted.

### Autopilot orchestration

One overlap-safe coordinator job performs:

1. refresh selected YouTube Music playlists;
2. reconcile unresolved membership;
3. search unresolved tracks for `assist` and `full` playlists;
4. for `full` only, evaluate identity/version/duration gates independently from
   quality/peer desirability and enqueue at most the configured caps;
5. refresh transfers and rely on the existing ingest watcher;
6. post-import verify duration, readable audio, and identity evidence;
7. auto-link verified matches, while ambiguous/corrupt/material mismatches become
   review items;
8. after a quiet/debounce window, regenerate only affected enabled recipes and
   atomically refresh their configured exports.

The coordinator uses a token-owned renewable Redis lock, database idempotency
keys, bounded exponential backoff, and no-overlap scheduling. It runs once on
service startup and periodically from a dedicated RQ scheduler process. Loss of
connectivity, host sleep, or restart produces a resumable failed/partial run rather
than duplicate downloads. The global pause switch blocks new automatic work but
does not break manual actions.

Dry-run executes refresh/planning/gates and may persist operational search and
acquisition evidence, but it never enqueues downloads, ingests, links,
regenerates, or writes exports. It is the required deployment smoke.

### API and UI

- Playlist settings lead with `Keep fresh`, then show `Sync only`, `Assist/search`,
  and explicitly labelled `Full autopilot`.
- Generator screens lead with musical intent and saved recipes; technical weights
  remain available as secondary details.
- Preview shows real playlists and evidence rather than structural estimates.
- An automation screen/settings card shows pause state, caps/schedule, last run,
  concise counts, failures, and review-required items.
- Successful routine runs remain low-noise; warnings and review work are visible.
- Generated API types and OpenAPI are regenerated and verified.

### Durable configured exports

Only recipes explicitly configured for automatic export are materialised under
the persistent app-data mount (default `/data/exports/autopilot`). Writes use a
temporary directory and atomic replacement. The feature does not recreate the
retired “export everything in the background” behaviour.

## Work ownership

- **Generator lane** owns `app/app/sonic/**`, sonic tests, and the benchmark
  harness/results. It does not edit migrations, global schema registration,
  Compose, or frontend files.
- **Autopilot lane** owns `app/app/autopilot/**`, narrowly required
  streaming/Soulseek/ingestion integrations, and autopilot tests. It consumes the
  generator recipe API contract and does not edit `app/app/sonic/**`, migrations,
  Compose, or frontend files.
- **Frontend lane** owns `app-ui/**` only and consumes the agreed API shapes.
- **Integration owner** owns the migration, `app/app/schema.py`, startup/Compose,
  shared generated artifacts, documentation, cross-lane conflict resolution,
  production backup/migration/deploy, and final verification.

## Verification and delivery gates

1. Focused lane tests and migration/schema parity.
2. Representative local-data benchmark comparing descriptor-only and hybrid
   semantic variants for cohesion, boundary behaviour, stability, runtime, and
   failure fallback. Selection is evidence-led; genre is not a grouping input.
3. Safe autopilot dry-run proving caps, gates, idempotency, pause, lock ownership,
   debounce, retry, and review routing without an unattended download.
4. Full `ruff check .`, `ruff format --check .`, and `pytest`.
5. Full frontend `npm run lint`, `npm test`, and `npm run build`, plus generated
   OpenAPI/type checks.
6. Independent integrated security/privacy/reliability review.
7. Before any production migration or deploy: timestamped custom-format `pg_dump`
   outside the Postgres data volume, checksum and `pg_restore --list` validation,
   isolated restore rehearsal, recorded version/counts/invariants and rollback.
8. Push the verified commit to `main`, deploy with the owner Compose context,
   confirm Alembic head and row-count invariants, run live health/API/UI checks,
   and perform a production dry-run with mutation flags disabled.
