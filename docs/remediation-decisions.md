# Audit remediation decisions

This log records observed facts separately from product decisions and assumptions for
the remediation programme begun on 2026-07-11.

## Baseline

- Observed: the worktree started clean and detached at
  `a7981abac2ac1540cefe63c562d034425b9d4f20`.
- Observed: local `origin/main` resolved to the same commit.
- Decision: preserve the documented personal, single-operator local/LAN threat model.
  Authentication and multi-tenancy are outside this programme.

## Data contracts

- Decision: one local track may link to at most one exact streaming track, and one
  streaming track or streaming-equivalence group may link to at most one local track.
- Decision: exact-target uniqueness is a database invariant. Equivalence-group
  uniqueness is enforced by the shared mutation service while locking the affected
  streaming-track rows; stale or racing mutations return HTTP 409.
- Decision: migrations preflight conflicting existing data and stop with an auditable
  report instead of choosing a winner automatically. No production repair is run here.
- Decision: historical Soulseek and accepted relationship-suggestion rows are retained
  when their final link or relationship is removed; nullable references use `ON DELETE
  SET NULL`.
- Decision: API timestamps are UTC-aware ISO 8601 values. Tests must not depend on
  PostgreSQL returning naive timestamps.

## Metadata Rescue

- Decision: a successful rescue updates file tags, reconciles Beets and the PostgreSQL
  mirror, resolves the relevant failed ingestion attempt, and returns refreshed state.
- Decision: irreversible steps and partial failures are reported explicitly; a response
  must not claim the whole workflow succeeded when only the file tags changed.

## Persisted M3U direction

- Observed: `README.md` documents one background-generated M3U per streaming playlist,
  says link changes auto-regenerate it, and documents `/data/m3u` through
  `M3U_OUTPUT_DIR` and the Compose `/data` mount.
- Observed: no in-repository downstream consumer reads `/data/m3u`; the separate
  on-demand export API/UI generates downloadable M3U/M3U8 archives.
- Observed: no service in Compose mounts or reads the generated directory, no repository
  code consumes the persisted files, and the documentation names no external player,
  watcher, bind mount, or sync process that depends on them.
- Decision: the repository contains no real supported consumer. Retire background
  persistence and its queue/regeneration wiring, correct the stale documentation, and
  retain the existing on-demand playlist, ZIP, M3U8, and Rekordbox exports as the single
  export product.

## Operator workflow and responsive UI

- Decision: proposal review remains one inbox, grouped as one local-track task with
  ranked alternatives. Filtering changes what is visible without changing the pending
  backend count; exact proposal links retain explicit pending, resolved, stale, and
  missing states.
- Decision: mobile navigation is an off-canvas modal interaction with Escape, focus
  containment/restoration, and route-close behavior. Core Soulseek work becomes a
  single-pane queue/detail flow below the desktop breakpoint.
- Decision: export labels distinguish selected targets from the full linked local
  library. The full-library Rekordbox action never inherits the selected-playlist
  scope implicitly.
- Observed: after final integration the production entry chunk is 333.86 kB raw
  and 103.30 kB gzip, compared with the audited 328.93 kB raw snapshot. Operational
  views remain route-split into lazy chunks; the small entry increase is accepted in
  exchange for global job refresh and accessible shell behavior.

## Operational readiness

- Decision: Compose uses a one-shot, non-mutating configuration preflight before the
  app starts. Direct runtime loading preserves clamp-and-warning compatibility for
  worker counts; Compose treats those warnings and invalid Soulseek values as startup
  errors.
- Decision: Soulseek remains optional. Once enabled, its API, webhook, path, timeout,
  polling, result-limit, queue, and upload-speed settings must form a complete bounded
  configuration.
- Decision: production browser smoke uses deterministic intercepted API fixtures so
  deep links, responsive behavior, and accessibility do not depend on a personal
  library snapshot.
- Observed: axe exposed light-scheme contrast failures in the stock Catppuccin
  subtext, blue, mauve, and success-green tokens. Light-only overrides use
  `#52556d`, `#1650c3`, `#7731d2`, and `#2a6f1b`; the full `color-contrast` rule
  now passes on the smoke routes.
- Observed: a redacted offline Gitleaks scan found one generic-key candidate in the
  historical `.env.example`; inspection confirmed it is the empty `SLSKD_API_KEY`
  field followed by `SLSKD_VERIFY_SSL=true`, not a credential. The independent custom
  current/history scan likewise found no confirmed credentials.
- Observed: history contains removed `.claude/projects/-Users-billie-Code-crate-lynx`
  memory paths added in `4f43b13d8f93bd97e6d1e4150c19ff6397012f7a` and removed in
  `ee3f7674f16e2dab59207c6995c086d9d1a2ced9`. This is a low-severity local-path and
  internal-debug-note hygiene finding only; no history rewrite is authorized or
  recommended by this programme.

## Verification boundary

- Decision: disposable local containers and databases are permitted. Production data is
  never inspected or mutated by this programme.
- Decision: commits, pushes, pull requests, deploys, publication, and history rewriting
  remain out of scope until separately requested.
