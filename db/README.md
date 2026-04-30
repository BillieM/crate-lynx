# db

Database schema and migration assets for the PostgreSQL service.

## Alembic

Run migrations from the repo root with:

```bash
DATABASE_URL=postgresql+psycopg://crate_lynx:crate_lynx@localhost:18102/crate_lynx \
  alembic -c db/alembic.ini upgrade head
```
