# E01 — Project Scaffolding

- [x] Create repo directory structure (app-ui/, app/, db/, redis/)
- [x] Write Dockerfile for `app` container (FastAPI + Beets + FFmpeg + fpcalc + ytmusicapi + RQ)
- [x] Write entrypoint script for `app` container (uvicorn + RQ worker)
- [x] Add FastAPI skeleton with `/health` endpoint
- [x] Write Dockerfile + Nginx config for `app-ui` container (multi-stage, SPA proxy)
- [x] Write Redis config (maxmemory-policy=noeviction)
- [ ] Write `docker-compose.yml` (4 services, volumes, health-check depends_on)
- [ ] Write `.env.example` (all required vars, no real secrets)
- [ ] Smoke test: `docker compose up --build`, verify all 4 services reach healthy state
