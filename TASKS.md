# E07 — M3U generation

- [x] Add `m3u/` package under `app/`: `__init__.py`, `generator.py` (core generation logic)
- [x] Implement `generate_m3u(playlist_id, base_path)` function: query `playlist_membership` joined through `final_links` to `local_tracks`, resolve file paths relative to `base_path`
- [x] Format output as valid M3U with `#EXTM3U` header and `#EXTINF` lines (duration + artist/title from `local_tracks` metadata)
- [x] Implement `GET /playlists/{id}/m3u` export endpoint: call generator and return file response with `audio/x-mpegurl` content type and appropriate filename
- [x] Hook auto-regeneration: call generator (write M3U to a defined output directory) after approve, reject, and break-link operations
- [x] Define output directory via env var (e.g. `M3U_OUTPUT_DIR`) and add to `.env.example`
- [ ] Write tests: M3U contains only final-linked tracks, paths are resolved relative to base_path, `#EXTINF` metadata is correct, empty playlist produces valid M3U with header only
