# E17 — Acoustic fingerprint matching via yt-dlp

- [x] Inspect the existing low-confidence matching flow and document the current acoustic stub behavior
- [x] Add durable streaming-track fingerprint fields and a migration for acoustic fallback results
- [x] Implement yt-dlp audio download to a temporary file for candidate streaming tracks
- [x] Run Chromaprint `fpcalc` on downloaded streaming audio and persist the resulting fingerprint data
- [x] Compare local and streaming fingerprints and derive an acoustic similarity score
- [x] Update the acoustic RQ job handler to promote or discard low-confidence suggestions based on fingerprint similarity
- [ ] Ensure temporary audio files are always cleaned up after success, failure, or cancellation
- [ ] Add backend tests for download, fingerprint extraction, similarity scoring, suggestion promotion, suggestion discard, and cleanup behavior
- [ ] Run relevant backend validation: `ruff check .`, `ruff format --check .`, and targeted `pytest`
