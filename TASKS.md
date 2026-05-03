# Refactor — domain-based package structure

- [x] Create `core/` package: move `queueing.py` and `worker.py` into `app/core/`, update all imports
- [x] Create `local_tracks/` package: move `local_tracks.py` → `local_tracks/store.py`, update all imports
- [x] Create `ingestion/` package: split `ingestion.py` into `pipeline.py` (AudioPreparer, BeetsImporter, FingerprintGenerator, IngestionProcessor) and `watcher.py` (IngestionWatcher, IngestionEventHandler); move `ingest_status.py` → `ingestion/status.py`; update all imports
- [x] Create `streaming/adapters/` subpackage: define `StreamingAdapter` protocol in `base.py`; move `youtube_music.py` → `adapters/youtube_music.py` implementing the protocol
- [ ] Split `streaming_accounts.py` into `streaming/models.py` (dataclasses/DB row types), `streaming/store.py` (StreamingAccountStore), `streaming/crypto.py` (encrypt/decrypt), `streaming/jobs.py` (RQ job functions)
- [ ] Extract Pydantic schemas from `main.py` → `streaming/schemas.py` and route handlers → `streaming/router.py`
- [ ] Slim `main.py` to app factory only: remove all route definitions, mount routers from each domain package
- [ ] Update all tests for new import paths; confirm test suite passes

---

*E05 — Matching pipeline tasks to follow once refactor is complete*
