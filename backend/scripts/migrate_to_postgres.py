"""One-time data copy from the local SQLite dev.db into a managed Postgres.

The target must already have the schema. Render runs `alembic upgrade head` on
every deploy, so once the app is live on Render its Postgres is migrated; you can
also run it yourself against any target:

    DATABASE_URL="postgresql://USER:PASS@HOST:PORT/DB" python -m alembic upgrade head

Then copy the data (run from backend/ with the app's virtualenv):

    python -m scripts.migrate_to_postgres "postgresql://USER:PASS@HOST:PORT/DB"

Use the target's EXTERNAL connection string (Render → the database → "External
Database URL"). The script copies every row table-by-table in foreign-key order,
then resets Postgres sequences so new inserts continue past the copied IDs.

Safety: it refuses to run if any target table already holds rows — migrate into
a fresh, empty database only. Re-running is not an upsert.
"""

import sys

from sqlalchemy import create_engine, func, select, text

from app.config import get_settings
from app.database import Base, _normalize
import app.main  # noqa: F401 — importing the app registers every table on Base.metadata


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python -m scripts.migrate_to_postgres "<target postgres URL>"')
        sys.exit(1)

    target_url = _normalize(sys.argv[1])
    source_url = _normalize(get_settings().database_url)
    if not source_url.startswith("sqlite"):
        print(f"Source is not SQLite ({source_url}). Leave DATABASE_URL unset so it points at dev.db.")
        sys.exit(1)
    if not target_url.startswith("postgresql"):
        print(f"Target does not look like Postgres: {sys.argv[1]}")
        sys.exit(1)

    src = create_engine(source_url, connect_args={"check_same_thread": False})
    dst = create_engine(target_url)
    tables = Base.metadata.sorted_tables  # parents before children (FK-safe)

    with src.connect() as s, dst.begin() as d:
        # Guard: never copy into a database that already has data.
        for t in tables:
            if d.execute(select(func.count()).select_from(t)).scalar():
                print(f"ABORT: target table '{t.name}' already has rows. Migrate into an empty DB.")
                sys.exit(1)

        total = 0
        for t in tables:
            rows = [dict(r._mapping) for r in s.execute(select(t))]
            if rows:
                d.execute(t.insert(), rows)
                total += len(rows)
            print(f"  {t.name}: {len(rows)}")

        # Reset each serial sequence to MAX(id) so future inserts don't collide.
        for t in tables:
            pk = list(t.primary_key.columns)
            if len(pk) == 1 and pk[0].name == "id":
                seq = d.execute(text("SELECT pg_get_serial_sequence(:tbl, 'id')"),
                                {"tbl": t.name}).scalar()
                if seq:
                    max_id = d.execute(text(f'SELECT COALESCE(MAX(id), 0) FROM "{t.name}"')).scalar()
                    if max_id:
                        d.execute(text("SELECT setval(:seq, :val, true)"),
                                  {"seq": seq, "val": max_id})

    print(f"Done. Copied {total} rows across {len(tables)} tables into Postgres.")


if __name__ == "__main__":
    main()
