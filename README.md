# crate-lynx

A local-first music asset manager that uses streaming services as a curation layer. Mirror your YouTube Music playlists using high-quality local files, with a manual approval system for linking local tracks to their streaming counterparts.

---

## Architecture

| Service | Stack |
|---|---|
| `app` | Python 3.12, FastAPI, RQ worker, Beets, FFmpeg, Chromaprint |
| `app-ui` | React (Vite), TypeScript, Tailwind CSS + Catppuccin Mocha, TanStack Query |
| `db` | PostgreSQL 16+ |
| `redis` | Message broker for RQ background jobs |

The `app` container runs two processes: the FastAPI server (`uvicorn`) and the RQ worker — both sharing the same codebase and config.

---

## Getting started

```bash
cp .env.example .env
# fill in TOKEN_ENCRYPTION_KEY and LIBRARY_ROOT
docker compose up --build
```

The UI is served at `http://localhost` (Nginx). The API is available at `http://localhost/api`.

---

## Environment variables

| Variable | Purpose |
|---|---|
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting streaming auth tokens |
| `LIBRARY_ROOT` | Absolute path to your local music library (e.g. `/mnt/library`) |

---

## Development

### Backend (`app/`)

```bash
ruff check .          # lint
ruff format .         # format
pytest                # tests
```

### Frontend (`app-ui/`)

> **Note:** React app is not yet scaffolded — these commands will be available once E09 is complete.

```bash
npm run lint
npm test
npm run build
```

---

## How it works

### Ingestion

Drop a file into the `ingestion/` folder. Watchdog picks it up, transcodes lossless formats to MP3 via FFmpeg, runs Beets for metadata enrichment, generates a Chromaprint fingerprint, and kicks off the matching pipeline.

### Matching pipeline

Runs three stages in sequence, stopping at the first high-confidence result:

1. **ISRC match** — near-certain if both sides have a matching ISRC
2. **Fuzzy tag match** — artist/title/album comparison via rapidfuzz
3. **Acoustic fingerprint** — fallback when tag score is below threshold

Results land in the **Link Proposals** queue, grouped by confidence band (High / Medium / Low).

### Approval

- **Approve** — writes to `final_links`, triggers M3U regeneration
- **Reject** — marks the pair as rejected so it never resurfaces
- **Break Link** — removes from `final_links`, marks rejected
- **Re-match** — clears the suggestion and reruns the pipeline

### M3U generation

One M3U file per streaming playlist, generated from `playlist_membership` joined through `final_links` to `local_tracks`. Auto-regenerated on any link change. Paths resolve relative to the consuming tool.

---

## Security

Streaming auth tokens are encrypted at the application layer using Fernet before being written to the database. The encryption key never touches the database.
