# Music Asset Manager — Revised Plan

## 1. Core Vision & System Logic

The goal is a local-first music asset manager that treats streaming services (YouTube Music, etc.) as curation layers. The system mirrors streaming playlists using local high-quality files.

- **Ownership Layer:** High-quality local MP3 files processed via Beets.
- **Curation Layer:** Playlists and discovery on streaming services.
- **The Bridge:** A manual-approval linking system that maps local track IDs to streaming provider IDs.

---

## 2. Technical Stack

| Layer | Technology |
|---|---|
| Containerisation | Docker Compose (4 services) |
| Frontend | React (Vite), Tailwind CSS + Catppuccin Mocha plugin, TanStack Query |
| Backend API | Python (FastAPI) |
| Processing | Beets (CLI) for ingestion; FFmpeg for transcoding (lossless sources only) |
| Analysis | Chromaprint (fpcalc) for acoustic fingerprinting |
| Database | PostgreSQL 16+ |
| Task Broker | Redis + RQ for background tasks |
| Streaming | ytmusicapi (wrapped via adapter pattern) |

---

## 3. Docker Services

| Container | Contents |
|---|---|
| `app-ui` | React frontend served via Nginx |
| `app` | FastAPI server + Beets + FFmpeg + fpcalc + ytmusicapi + RQ worker |
| `db` | PostgreSQL 16+ |
| `redis` | Message broker for task distribution |

Inside `app`, the entrypoint starts two processes: the FastAPI server (`uvicorn`) and the RQ worker (`rq worker`). Both share the same codebase, models, and config. Supervisor or a simple shell script manages both processes.

---

## 4. Database Schema (PostgreSQL)

### A. Local Assets

**`local_tracks`**
- `id` (UUID, PK)
- `file_path` (Relative path from `LIBRARY_ROOT`)
- `fingerprint` (Chromaprint hash)
- `isrc` (varchar, nullable)
- `beets_metadata` (JSONB: artist, album, title, year, etc.)
- `file_exists` (bool, default true)

### B. Streaming Service Mirroring

**`streaming_accounts`**
- `id`, `provider` (YTM, Spotify), `auth_token_blob` (encrypted at application layer via Fernet)

**`streaming_playlists`**
- `id`, `service_playlist_id`, `account_id`, `name`, `last_synced`

**`streaming_tracks`**
- `id`, `service_track_id`, `metadata_json` (raw API data), `isrc` (varchar, nullable), `available` (bool, default true)

**`playlist_membership`** (Join table)
- `playlist_id`, `streaming_track_id`, `position`, `removed_at` (timestamp, nullable)

### C. The Linking Engine

**`suggested_links`** (The Queue)
- `local_track_id` (FK)
- `streaming_track_id` (FK)
- `isrc_match` (bool)
- `tag_match_score` (float)
- `acoustic_match_score` (float, nullable — only populated when tag score is low)
- `status` (pending, rejected)
- `rejected_at` (timestamp, nullable)

**`final_links`** (The Map)
- `local_track_id` (FK)
- `streaming_track_id` (FK)
- `approved_at` (timestamp, nullable)

One local track can map to multiple streaming IDs across different services.

---

## 5. Matching Logic

Matching follows a sequential pipeline. Each stage is only triggered if the previous stage did not produce a high-confidence result.

1. **ISRC match** — if both sides have an ISRC and they match, treat as near-certain. Surfaced at top of Link Proposals queue.
2. **Fuzzy tag match** — artist, title, album comparison. Produces a `tag_match_score`.
3. **Acoustic fingerprint** — fallback only when `tag_match_score` is below confidence threshold. Populates `acoustic_match_score`.

### Threshold Bands

| Band | Condition | Behaviour |
|---|---|---|
| High confidence | `isrc_match = true` or `tag_match_score > 0.85` | Top of queue, highlighted |
| Medium confidence | `tag_match_score` 0.5–0.85 | Surfaced normally |
| Low confidence | `tag_match_score < 0.5` | Triggers acoustic fingerprint job |

---

## 6. UI/UX Design

### Design System

- **Theme:** Catppuccin Mocha (via official Tailwind CSS plugin)
- **Base background:** `#1e1e2e`
- **CSS variables used throughout** — all colours reference theme tokens so future theme switching requires only a config change

### Progress Bubble Colour States

| State | Catppuccin Colour | Hex |
|---|---|---|
| 0% linked | Red | `#f38ba8` |
| ~50% linked | Yellow | `#f9e2af` |
| 100% linked | Green | `#a6e3a1` |

Non-linear curve applied for better perceptual evenness:
```javascript
const hue = Math.pow(ratio, 0.7) * 120
```

Numeric ratio (e.g. `5/62`) always visible alongside colour — not tooltip-only.

### Sidebar Structure

**🛠 Maintenance**
- Unidentified — tracks where Beets failed to find a MusicBrainz/Discogs match
- Link Proposals — tracks awaiting user approval, sorted by confidence band
- Missing Locally — streaming tracks with no local match (future auto-grab queue)

**🔴 YouTube Music**
- All synced playlists with progress bubbles (e.g. `5/62`)

**🏠 Local Library**
- Folder-based navigation of the physical library

### Search & Filter

- Global search bar at top of sidebar (searches title, artist, album, playlist name, filename)
- Dedicated Library view with faceted filters:

| Filter | Options |
|---|---|
| Link status | Linked / Unlinked / Pending |
| Match method | ISRC / Tag / Acoustic / Manual |
| File status | OK / Missing |
| Playlist | Multi-select from synced playlists |

---

## 7. Operational Workflows

### Ingestion Pipeline (Automatic)

1. **Watchdog** — detects file in `ingestion/` folder
2. **Format check** — if already MP3, skip transcoding and move directly; if lossless (FLAC, WAV, AIFF), transcode to MP3 via FFmpeg
3. **Beets** — runs `import -q`, enriches metadata, moves to `/library/`
4. **Fingerprint** — worker generates Chromaprint hash
5. **Auto-search** — runs matching pipeline (ISRC → tag → acoustic fallback)

### Manual Approval

- User clicks **Approve** in Link Proposals to write to `final_links`
- User clicks **Reject** — pair written back to `suggested_links` with `status = rejected` and `rejected_at` timestamp to prevent resurfacing
- User clicks **Break Link** — removes from `final_links`, pair written to `suggested_links` with `status = rejected`
- User clicks **Re-match** — clears existing suggestion, reruns matching pipeline

### Metadata Rescue

If a local file has poor metadata (Beets failed), the user can **Rescue** it by writing the streaming service's metadata and high-res album art directly to the local MP3 tags via the backend.

### Mirroring

M3U files generated locally based on `streaming_tracks` membership via `final_links`. Updated automatically whenever a link is approved, rejected, or overridden. Paths in M3U files resolve from the perspective of the consuming tool, not the container.

### Missing Locally View

Populated by:
```sql
SELECT st.* FROM streaming_tracks st
LEFT JOIN final_links fl ON fl.streaming_track_id = st.id
WHERE fl.streaming_track_id IS NULL
AND st.available = true
```
This view acts as the input queue for a future auto-grab feature.

---

## 8. Security & Configuration

### Token Encryption

`auth_token_blob` is encrypted at the application layer using Fernet before writing to the database. The encryption key never touches the database.

```python
from cryptography.fernet import Fernet
key = os.environ["TOKEN_ENCRYPTION_KEY"]
fernet = Fernet(key)
encrypted = fernet.encrypt(raw_token.encode())
raw_token = fernet.decrypt(encrypted).decode()
```

### Environment Variables

| Variable | Purpose |
|---|---|
| `TOKEN_ENCRYPTION_KEY` | Fernet key for auth token encryption |
| `LIBRARY_ROOT` | Absolute path to music library (e.g. `/mnt/library`) |

### Path Portability

All `file_path` values stored relative to `LIBRARY_ROOT`. Full path resolved at runtime:
```python
full_path = Path(os.environ["LIBRARY_ROOT"]) / track.file_path
```

---

## 9. Engineering Notes

### ytmusicapi Adapter Pattern

All ytmusicapi calls are routed through a single `YouTubeMusicAdapter` module. The rest of the codebase calls the adapter interface, not the library directly. This isolates breakage when YouTube updates its internals.

### Links Are Never Immutable

The UI must always expose **Re-match** and **Break Link** on any approved link. No link is treated as permanent.

---

## 10. Future / V2 Features

- Auto-grab for Missing Locally tracks
- Customisable theme switching (Catppuccin flavours: Latte, Frappé, Macchiato, Mocha already available)
- Spotify integration (note: Spotify API access has been progressively restricted — build provider abstraction assuming capabilities may change)
- Reverse sync / Push to Streaming playlist
- Additional UI views and navigation improvements based on real-world DJ workflow usage
