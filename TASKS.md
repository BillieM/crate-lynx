# E02 — Database schema & migrations

- [x] Initialise Alembic inside `db/` with `alembic init`; configure `env.py` to read `DATABASE_URL` from env
- [x] Write SQLAlchemy base model and shared `models.py` (to be mounted/imported by `app/`)
- [x] Define `local_tracks` table (id, file_path, library_root_rel_path, fingerprint, beets_id, created_at, updated_at)
- [x] Define `streaming_accounts` table (id, provider, display_name, auth_token_blob, created_at, updated_at)
- [ ] Define `streaming_playlists` table (id, account_id FK, provider_playlist_id, title, synced_at)
- [ ] Define `streaming_tracks` table (id, provider_track_id, title, artist, album, year, isrc, duration_ms)
- [ ] Define `playlist_membership` table (id, playlist_id FK, streaming_track_id FK, position)
- [ ] Define `suggested_links` table (id, local_track_id FK, streaming_track_id FK, match_method, score, status, rejected_at, created_at)
- [ ] Define `final_links` table (id, local_track_id FK unique, streaming_track_id FK, approved_at)
- [ ] Write Fernet encryption helpers (`encrypt_token` / `decrypt_token`) for `auth_token_blob`
- [ ] Generate initial Alembic migration from the model definitions
- [ ] Wire `db` container in `docker-compose.yml` to run `alembic upgrade head` on startup (or add entrypoint script)
- [ ] Smoke test: `docker compose up`, confirm all 7 tables exist in Postgres and migration history is clean
