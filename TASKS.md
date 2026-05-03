# E08 — Metadata rescue

- [x] Add `rescue/` package under `app/`: `__init__.py`, `metadata.py` (core rewrite logic)
- [x] Implement `rescue_metadata(local_track_id)` function: look up `final_links` to find the linked streaming track, fetch streaming track metadata (title, artist, album, year, album art URL)
- [x] Write ID3 tags to the local MP3 file using mutagen: TIT2, TPE1, TALB, TDRC, and APIC (album art, downloaded from URL and embedded)
- [ ] Add `POST /local-tracks/{id}/rescue` endpoint: validate a final link exists, call `rescue_metadata`, return updated track record
- [ ] Return 409 if no final link exists for the given local track
- [ ] Write tests: tags are correctly written, APIC frame is embedded, 409 is returned when no final link exists
