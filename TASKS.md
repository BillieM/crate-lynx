# Audit fixes

## T01 — Fix: Approve proposal crashes with 500 when track already linked

**File:** `app/app/links/router.py`

- [x] Before the `insert()` into `final_links_table`, query whether a row already exists for `proposal["local_track_id"]`
- [x] If a row exists, return HTTP 409 with a descriptive JSON error body (`{"detail": "Track already has an approved link"}`)
- [x] Write test: create a track with an existing final link, call the approve endpoint again for the same `local_track_id`, assert 409 is returned and no IntegrityError is raised

---

## T02 — Fix: Ingestion staging path collision for same-basename files

**File:** `app/app/ingestion/pipeline.py`

- [x] Replace `output_root / source.name` (MP3 branch) with a UUID-prefixed staging filename, e.g. `output_root / f"{uuid.uuid4().hex}_{source.name}"`
- [x] Replace `output_root / f"{source.stem}.mp3"` (lossless branch) with `output_root / f"{uuid.uuid4().hex}_{source.stem}.mp3"`
- [x] Verify `PreparedTrack` downstream consumers use the returned `prepared_path` and nothing hardcodes the old naming scheme
- [x] Run existing ingestion tests to confirm no regressions

---

## T03 — Improve: YouTube Music N+1 ISRC lookups

**File:** `app/app/streaming/adapters/youtube_music.py`

- [ ] Check whether ytmusicapi exposes a bulk song-detail endpoint that could replace individual `get_song()` calls
- [ ] Restructure the loop to collect tracks missing ISRCs in a first pass, then enrich them in a second pass — keeps the hot path readable and makes future batching straightforward
- [ ] If no batch API exists, add an in-memory cache (dict keyed by `provider_track_id`) so repeated calls for the same track within one sync don't hit the network twice
- [ ] Add a test that mocks the playlist response with multiple ISRC-less tracks and asserts `get_song()` is called at most once per unique track ID
