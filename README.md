# crate-lynx

A local-first music asset manager that uses streaming services as a curation layer. Mirror your YouTube Music playlists using high-quality local files, with a manual approval system for linking local tracks to their streaming counterparts.

---

## Architecture

| Service | Stack |
|---|---|
| `app` | Python 3.12.13, FastAPI, RQ worker, Beets, FFmpeg, Chromaprint |
| `app-ui` | React (Vite), TypeScript, Tailwind CSS + Catppuccin Mocha, TanStack Query |
| `db` | PostgreSQL 16+ |
| `redis` | Message broker for RQ background jobs |

The `app` container runs the FastAPI server (`uvicorn`) plus dedicated RQ workers: one ingestion worker by default, and one worker for matching/streaming jobs. They share the same codebase and environment config.

---

## Getting started

```bash
cp .env.example .env
# Generate TOKEN_ENCRYPTION_KEY and add it to .env:
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
docker compose up --build
```

For local backend development, use Python 3.12.13. A repo-level `.python-version` file is included for tools such as `pyenv`.

The UI is served at `http://localhost:18100` (Nginx). The API is available at `http://localhost:18101` and proxied through the UI at `http://localhost:18100/api`.

---

## Deployment

Production runs on a remote Docker host via the `gluesoup-0-docker-1` SSH context. If the context is missing locally, create it with:

```bash
docker context create gluesoup-0-docker-1 --docker host=ssh://gluesoup-0-docker-1
```

Switch to it with:

```bash
docker context use gluesoup-0-docker-1
```

Deploy with Docker Compose through the active context. On machines with the Docker CLI Compose plugin:

```bash
docker compose up --build -d
```

If `docker compose version` is not available locally, use the standalone Compose command:

```bash
docker-compose up --build -d
```

Services are exposed on the same ports as local development (`18100`–`18103`). To verify the deploy, check that all containers are healthy:

```bash
docker compose ps
# or: docker-compose ps
```

The public UI is routed through Traefik at `https://cratelynx.billiem.uk`. The Crate Lynx Compose stack creates a fixed-name Docker network, `cratelynx`, and attaches only `app-ui` to it. Traefik should join that network as an external network:

```yaml
services:
  traefik:
    networks:
      - cratelynx

networks:
  cratelynx:
    external: true
```

Backend services (`app`, `db`, and `redis`) stay on the internal Compose network. The browser calls `/api/...` on the same origin, and Nginx in `app-ui` proxies those requests to FastAPI internally.

---

## Environment variables

| Variable | Purpose |
|---|---|
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting streaming auth tokens. Generate one with `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` |
| `LIBRARY_ROOT` | Container path where processed music is stored. Defaults to `/nas/media/music` |
| `BEETS_LIBRARY` | Container path for the Beets SQLite database. Defaults to `/data/beets/library.db` |
| `BEETS_IMPORT_LOCK_PATH` | Optional path for the cross-process Beets import lock. Defaults next to `BEETS_LIBRARY` |
| `CRATE_LYNX_STAGING_DIR` | Container base path for temporary app outputs. Defaults to `/nas/cratelynx/staging` in Compose |
| `INGESTION_STABILITY_WORKERS` | Number of concurrent watcher stability checks. Defaults to `4` |
| `INGESTION_WORKER_COUNT` | Number of RQ workers listening to the ingestion queue. Defaults to `1` |
| `M3U_OUTPUT_DIR` | Container path for generated M3U exports. Defaults to `/data/m3u` in Compose |

## Storage and mounts

Docker Compose reads host paths from `.env`, with production-friendly defaults:

| Env var | Default host path | Container path | Purpose |
|---|---|---|
| `NAS_DATA_HOST_PATH` | `/mnt/nas_data` | `/nas` | NAS root containing ingest inputs, staging, Soulseek downloads, and processed music |
| `APP_DATA_HOST_PATH` | `/docker/appdata/cratelynx` | service-specific paths | Application-owned state for the app, Postgres, and Redis |

Create those host directories before starting the stack, or override the host path variables in `.env`. The paths configured in Settings are container paths, so any useful ingest folder should also be mounted into the `app` container.

`/nas/media/music` is output only. Do not add it as an ingest folder, because completed imports are moved there and watching it would re-ingest files that Beets has already processed.

For same-filesystem moves and MP3 hardlinks, keep ingest inputs, staging, and the final music library under `NAS_DATA_HOST_PATH`. The production layout is:

| Host path | Container path | Purpose |
|---|---|---|
| `/mnt/nas_data/cratelynx/music-in` | `/nas/cratelynx/music-in` | Default manual ingest input |
| `/mnt/nas_data/soulseek/downloads` | `/nas/soulseek/downloads` | Default Soulseek download ingest input |
| `/mnt/nas_data/cratelynx/staging` | `/nas/cratelynx/staging` | Temporary ingestion staging |
| `/mnt/nas_data/media/music` | `/nas/media/music` | Processed library output managed by Beets |

Application state is stored under `APP_DATA_HOST_PATH`:

| Host path | Container path | Purpose |
|---|---|---|
| `/docker/appdata/cratelynx/app` | `/data` in `app` | Beets SQLite database and generated M3U exports |
| `/docker/appdata/cratelynx/postgres` | `/var/lib/postgresql/data` in `db` | Postgres data directory |
| `/docker/appdata/cratelynx/redis` | `/data` in `redis` | Redis data directory |

---

## Development

### Backend (`app/`)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r app/requirements.txt -r requirements-dev.txt
ruff check .          # lint
ruff format .         # format
pytest                # tests
```

### Frontend (`app-ui/`)

```bash
npm run lint
npm test
npm run build
```

---

## How it works

### Ingestion

Ingest folders are configured in **Settings > General** and persisted in the application database. New installs seed two default container inputs: `/nas/cratelynx/music-in` and `/nas/soulseek/downloads`.

Drop a file into one of the configured ingest folders. Watchdog picks it up, transcodes lossless formats to MP3 via FFmpeg, runs Beets for metadata enrichment, moves the processed track under `/nas/media/music`, generates a Chromaprint fingerprint, and kicks off the matching pipeline.

The watcher only discovers stable candidate files and enqueues ingestion jobs. RQ workers run the expensive ingestion pipeline, with Redis dedupe preventing the same source path from being queued repeatedly while a job is pending or running.

Adding or removing ingest folders in Settings updates the active watcher immediately. If you add a path that is not backed by a Docker host mount, the app can create and watch that directory inside the container, but files placed on the host will not appear there unless the path is mounted.

### Matching pipeline

Runs two stages in sequence:

1. **ISRC match** — near-certain if both sides have a matching ISRC
2. **Fuzzy tag match** — artist/title/album comparison via rapidfuzz, persisted as ranked suggestions across confidence bands

Results land in the **Link Proposals** queue, grouped by confidence band (High / Medium / Low).

Local Chromaprint fingerprints are generated and stored during import as internal
metadata. They are not used for streaming-track matching and are not exposed in the
maintenance API or UI.

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
