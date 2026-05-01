# E03 — Local library ingestion pipeline

- [x] Add Watchdog dependency to `app/` and write a file-system observer that watches the `ingestion/` folder for new files
- [x] Implement format detection: MP3 passes through unchanged; FLAC/WAV/AIFF are transcoded to MP3 via FFmpeg
- [x] Wire the transcoder to output files into a staging area before Beets import
- [x] Run `beets import -q` on each incoming file for metadata enrichment and move to `/library/`
- [x] Generate a Chromaprint fingerprint via `fpcalc` for each ingested file and store the result
- [ ] Persist the ingested track to `local_tracks` with `file_path` stored relative to `LIBRARY_ROOT`
- [ ] Enqueue a matching pipeline job on RQ once ingestion is complete for a track
- [ ] Handle ingestion errors gracefully: log failures, do not crash the watcher loop
- [ ] Write an RQ worker entrypoint inside `app/` that processes ingestion and matching queue jobs
- [ ] Ensure Supervisor (or the existing shell script) starts both uvicorn and the RQ worker
- [ ] Add a `/ingest/status` health/status endpoint showing queue depth and recent ingestion results
- [ ] Integration smoke test: drop a FLAC and an MP3 into `ingestion/`, confirm both end up in `local_tracks` with fingerprints
