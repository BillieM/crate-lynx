# E05 — Matching pipeline

- [x] Add `matching/` package under `app/`: `__init__.py`, `models.py` (dataclasses for match result, confidence band enum: high/medium/low)
- [x] Implement ISRC match step in `matching/isrc.py`: query `streaming_tracks` by ISRC, return high-confidence result when found
- [x] Implement fuzzy tag match step in `matching/tags.py`: compare title/artist/album with rapidfuzz, return score; band = high if > 0.85, medium if 0.5–0.85, low if < 0.5
- [x] Implement acoustic fingerprint fallback in `matching/acoustic.py`: RQ job that runs fpcalc comparison, triggered only when tag score is below threshold
- [x] Implement sequential pipeline orchestrator in `matching/pipeline.py`: ISRC → fuzzy tag → acoustic (enqueue RQ job if low), write result to `suggested_links`
- [x] Ensure pipeline is re-runnable per track: clear any existing non-approved `suggested_links` row before writing new result
- [ ] Wire matching pipeline as an RQ job in `matching/jobs.py`; enqueue from ingestion pipeline on track completion
- [ ] Mount any needed status/trigger endpoints in `matching/router.py` and register in `main.py`
- [ ] Write tests: ISRC hit returns high confidence, fuzzy match scoring bands, low score triggers acoustic job enqueue, re-run clears old suggestion
