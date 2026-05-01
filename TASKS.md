# E04 — YouTube Music adapter

- [x] Add ytmusicapi to `app/` dependencies and create a `YouTubeMusicAdapter` module that wraps all ytmusicapi calls (no direct ytmusicapi usage elsewhere in the codebase)
- [x] Implement the auth flow: accept OAuth credentials, encrypt the resulting token with Fernet, and write it to the `streaming_accounts` table
- [x] Add a `GET /streaming/accounts` endpoint and a `POST /streaming/accounts` endpoint to initiate and complete YouTube Music auth
- [x] Implement playlist sync in `YouTubeMusicAdapter`: fetch all playlists for an authenticated account and upsert into `streaming_playlists`
- [x] Implement track sync: for each playlist, fetch its tracks via ytmusicapi and upsert into `streaming_tracks` and `playlist_membership`
- [ ] Extract ISRC from ytmusicapi track metadata where available and store on `streaming_tracks`
- [ ] Expose a `POST /streaming/accounts/{id}/sync` endpoint that enqueues an RQ job to run the full playlist + track sync
- [ ] Add a `GET /streaming/playlists` endpoint returning all synced playlists with track counts and last-synced timestamp
- [ ] Handle ytmusicapi auth errors and token expiry gracefully: surface a clear error state on `streaming_accounts` rather than crashing
- [ ] Write unit tests for `YouTubeMusicAdapter` using mocked ytmusicapi responses (playlists, tracks with and without ISRC)
