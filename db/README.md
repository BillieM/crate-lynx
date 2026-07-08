# db

Database schema and migration assets for the PostgreSQL service.

## Alembic

Run migrations from the repo root with:

```bash
set -a
source .env
set +a
DATABASE_URL="postgresql+psycopg://${POSTGRES_USER:-crate_lynx}:${POSTGRES_PASSWORD}@localhost:18102/${POSTGRES_DB:-crate_lynx}" \
  alembic -c db/alembic.ini upgrade head
```
