# E11 — YouTube Music sync reliability

- [x] Introduce a typed `MalformedPlaylistPayloadError` (or similar) and update `list_playlist_tracks()` in `app/app/streaming/adapters/youtube_music.py` to raise it on unparseable upstream payloads instead of returning `[]`, while still returning `[]` for a legitimately empty playlist
- [x] Update per-playlist callers of `list_playlist_tracks()` to catch the new typed error and skip `replace_playlist_membership()` so prior memberships are preserved on malformed payloads
- [x] Wrap each iteration of the playlist sync loop in `app/app/streaming/adapters/youtube_music.py` (around lines 271-277) in try/except so a single playlist failure logs and is skipped without aborting the rest
- [x] Apply the same per-iteration error isolation to the ISRC backfill loop in `_lookup_missing_isrcs` (`youtube_music.py:144`) so one bad lookup does not abort the whole pass
- [x] Persist per-playlist sync failures: add fields (last-error string + timestamp) to `streaming_playlists` (or equivalent job-result store) and write them whenever a playlist iteration fails
- [x] Add Alembic migration for the new per-playlist last-error/timestamp columns (if stored on `streaming_playlists`) and update SQLAlchemy models accordingly
- [ ] Add unit/integration tests covering: malformed payload raises and skips replace; legitimately empty playlist returns `[]` and clears membership normally; one failing playlist does not abort the loop; ISRC backfill failure is isolated; last-error fields are written
- [ ] Run validation: backend `ruff check .`, `ruff format --check .`, `pytest`
