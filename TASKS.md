# E04 — YouTube Music adapter

- [x] Add ytmusicapi to `app/` dependencies and create a `YouTubeMusicAdapter` module that wraps all ytmusicapi calls (no direct ytmusicapi usage elsewhere in the codebase)
- [x] Implement the auth flow: accept OAuth credentials, encrypt the resulting token with Fernet, and write it to the `streaming_accounts` table
- [x] Add a `GET /streaming/accounts` endpoint and a `POST /streaming/accounts` endpoint to initiate and complete YouTube Music auth
- [x] Implement playlist sync in `YouTubeMusicAdapter`: fetch all playlists for an authenticated account and upsert into `streaming_playlists`
- [x] Implement track sync: for each playlist, fetch its tracks via ytmusicapi and upsert into `streaming_tracks` and `playlist_membership`
- [x] Extract ISRC from ytmusicapi track metadata where available and store on `streaming_tracks`
- [x] Expose a `POST /streaming/accounts/{id}/sync` endpoint that enqueues an RQ job to run the full playlist + track sync
- [x] Add a `GET /streaming/playlists` endpoint returning all synced playlists with track counts and last-synced timestamp
- [x] Handle ytmusicapi auth errors and token expiry gracefully: surface a clear error state on `streaming_accounts` rather than crashing
- [x] Write unit tests for `YouTubeMusicAdapter` using mocked ytmusicapi responses (playlists, tracks with and without ISRC)

## E04 follow-up — browser auth pivot

### Cleanup
- [x] Delete `scripts/ytm-debug.py`
- [x] Remove `BadOAuthClient` / `UnauthorizedOAuthClient` imports and exception handling from `streaming_accounts.py`
- [x] Remove `_WRONG_CLIENT_HINT` constant and the OAuth-specific branch from `_format_auth_error`

### Switch to browser auth
- [x] Remove `YouTubeMusicOAuthCredentials`, `begin_oauth`, `complete_oauth`, and `setup_oauth` from `youtube_music.py`
- [x] Replace `create_youtube_music_account` in `streaming_accounts.py` with a version that accepts raw browser headers (dict) instead of an OAuth token; rename `StoredStreamingAccount.oauth_token` → `browser_headers`
- [x] Update `_run_youtube_music_sync` to call `from_browser_auth` instead of `from_oauth_token`; remove `credentials` param from all sync methods and `run_youtube_music_sync_job`
- [x] Remove `begin_youtube_music_account_oauth` / `complete_youtube_music_account_oauth` module-level functions from `streaming_accounts.py`
- [x] Replace the two-step OAuth flow in `POST /streaming/accounts` with a single endpoint that accepts `display_name` + `browser_headers` (raw headers dict copied from browser DevTools); remove `client_id` / `client_secret` from all request/response models
- [x] Remove `client_id` / `client_secret` from `SyncStreamingAccountRequest` and the sync job enqueuer
- [x] Update unit tests: replace OAuth credential fixtures and mocks with browser-auth equivalents throughout `test_youtube_music.py`, `test_streaming_accounts.py`, `test_main.py`, and `test_queueing.py`
- [ ] Remove `YOUTUBE_MUSIC_CLIENT_ID` / `YOUTUBE_MUSIC_CLIENT_SECRET` from `.env.example` if present
