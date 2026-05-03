---
name: YouTube Music sync HTTP 400 bug
description: Active investigation into get_library_playlists() returning HTTP 400 on authenticated requests
type: project
---

OAuth sync returns HTTP 400 "Request contains an invalid argument" when calling `get_library_playlists()`. Unauthenticated calls to ytmusicapi work fine.

**Why:** Unknown — initial suspicion was wrong OAuth client type, but user confirmed credentials ARE already "TV and Limited Input devices".

**How to apply:** The bug is still open. Next step is to run `scripts/ytm-debug.py` inside the container to see the exact headers being sent and the full raw error response from YouTube.

---

## What's confirmed working
- Auth flow completes — `POST /streaming/accounts` (with device_code) returns account with `auth_state: connected`
- Sync job enqueues and runs (doesn't crash the worker)
- Unauthenticated ytmusicapi calls succeed (API connectivity is fine)
- Token is stored encrypted in DB, decrypted and passed to `from_oauth_token` correctly

## What's broken
- `sync_youtube_music_account` → `sync_library_playlist_tracks` → `adapter.list_library_playlists()` → `yt.get_library_playlists()` → HTTP 400 "Request contains an invalid argument"
- Error is caught by `except (YTMusicError, BadOAuthClient, UnauthorizedOAuthClient)` and stored as `auth_error` on the account

## Code path
`run_youtube_music_sync_job` → `StreamingAccountStore.sync_youtube_music_account` → `_run_youtube_music_sync` → `YouTubeMusicAdapter.from_oauth_token(account.oauth_token, credentials=credentials)` → `YTMusic(auth=token_dict, oauth_credentials=OAuthCredentials(client_id, client_secret))` → `get_library_playlists()` → HTTP 400

## Key files
- `app/app/youtube_music.py` — `YouTubeMusicAdapter`, `from_oauth_token`, `list_library_playlists`
- `app/app/streaming_accounts.py` — `_run_youtube_music_sync`, `_format_auth_error`, `run_youtube_music_sync_job`
- `scripts/ytm-debug.py` — diagnostic script (run inside container)
- `scripts/ytm-auth.sh` / `ytm-test.sh` — manual test scripts

## Changes already committed/pending
- `from_oauth_token` strips `refresh_token_expires_in` and computes `expires_at` if missing
- `db/versions/a3f82c91d450_add_auth_state_to_streaming_accounts.py` — migration adding auth_state/auth_error/auth_error_at columns
- `requirements.txt` bumped to `ytmusicapi==1.12.0`
- `_run_youtube_music_sync` catches `BadOAuthClient`/`UnauthorizedOAuthClient` (these weren't caught before)
- `_format_auth_error` appends credential-type hint for HTTP 400 "invalid argument" errors

## ytmusicapi OAuth internals (1.10.3/1.12.0)
- `YTMusic(auth=dict, oauth_credentials=OAuthCredentials(...))` → `auth_type = OAUTH_CUSTOM_CLIENT`
- `base_headers` uses `initialize_headers()` (NOT the token dict) for OAUTH_CUSTOM_CLIENT
- `headers` property adds `Authorization: Bearer <access_token>` + `X-Goog-Request-Time`
- `RefreshingToken` auto-refreshes `access_token` when `expires_at - time.time() < 60`
- Context sent: `{"clientName": "WEB_REMIX", "clientVersion": "1.YYYYMMDD.01.00"}`

## Next steps
1. Run `scripts/ytm-debug.py` in container to see exact headers and full error response
2. Check `azp` field from Google tokeninfo — confirms which client issued the token
3. Inspect the raw YouTube Music API response body (not just the error message)
