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

The `app` container runs two processes: the FastAPI server (`uvicorn`) and the RQ worker — both sharing the same codebase and config.

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

Production runs on a remote Docker host via the `gluesoup-1` SSH context. Switch to it with:

```bash
docker context use gluesoup-1
```

The remote host does not have the Docker Compose plugin installed, so use `docker-compose` rather than `docker compose`:

```bash
docker-compose up --build -d
```

Services are exposed on the same ports as local development (`18100`–`18103`). To verify the deploy, check that all containers are healthy:

```bash
docker-compose ps
```

---

## Environment variables

| Variable | Purpose |
|---|---|
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting streaming auth tokens. Generate one with `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` |
| `LIBRARY_ROOT` | Container path where processed music is stored. Defaults to `/music` |
| `BEETS_LIBRARY` | Container path for the Beets SQLite database. Defaults to `/data/beets/library.db` |

## Storage and mounts

Docker Compose expects explicit host paths for ingestion, processed music, and application data:

| Host path | Container path | Purpose |
|---|---|---|
| `/srv/mergerfs/hdds/music-in` | `/ingestion` | Default manual ingest input |
| `/srv/mergerfs/hdds/soulseek/downloads` | `/soulseek` | Default Soulseek download ingest input |
| `/srv/mergerfs/hdds/media/music` | `/music` | Processed library output managed by Beets |
| `/docker/appdata/cratelynx` | `/data` | Application-owned data, including the Beets database |

Create those host directories before starting the stack, or edit `docker-compose.yml` to point at equivalent host paths on your machine. The paths configured in Settings are container paths, so any useful ingest folder should also be mounted into the `app` container.

`/music` is output only. Do not add it as an ingest folder, because completed imports are moved there and watching it would re-ingest files that Beets has already processed.

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

> **Note:** React app is not yet scaffolded — these commands will be available once E09 is complete.

```bash
npm run lint
npm test
npm run build
```

---

## How it works

### Ingestion

Ingest folders are configured in **Settings > General** and persisted in the application database. New installs seed two default container inputs: `/ingestion` and `/soulseek`.

Drop a file into one of the configured ingest folders. Watchdog picks it up, transcodes lossless formats to MP3 via FFmpeg, runs Beets for metadata enrichment, moves the processed track under `/music`, generates a Chromaprint fingerprint, and kicks off the matching pipeline.

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
