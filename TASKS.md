# E06 — Link proposal & approval API

- [x] Add `links/` package under `app/`: `__init__.py`, `models.py` (Pydantic schemas for proposal response, approve/reject request bodies)
- [x] Implement `GET /proposals` endpoint: list `suggested_links` joined with `local_tracks` and `streaming_tracks`, supporting confidence band filter query param
- [x] Implement `POST /proposals/{id}/approve` endpoint: write row to `final_links`, update `suggested_links.status` to approved
- [x] Implement `POST /proposals/{id}/reject` endpoint: set `suggested_links.status = rejected` and `rejected_at = now()`
- [ ] Implement `DELETE /final-links/{id}` (break link) endpoint: remove from `final_links`, write a rejected `suggested_links` entry for the same pair
- [ ] Implement `POST /local-tracks/{id}/rematch` endpoint: clear existing non-final suggestion for the track, re-enqueue matching pipeline RQ job
- [ ] Enforce rejected-pair guard: matching pipeline and approve endpoint must check `suggested_links` for rejected status before writing or approving a link for the same local+streaming pair
- [ ] Mount router in `main.py` under `/api` prefix
- [ ] Write tests: list filtering by band, approve writes final_link, reject marks rejected, break link removes final and writes rejected suggestion, rematch re-enqueues, rejected pair cannot be re-approved
