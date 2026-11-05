"""Sterling's database + Excel workbook, INSIDE CabinetTron.

Two modes:

* Cache (default, live today): the Excel workbook is the source of truth (see
  xlsx_store) and this SQLite file is a disposable runtime cache.
* Shared (STERLING_DATABASE_URL set): Sterling's tables live in the shared
  database, in their own "sterling" schema on Postgres so names like jobs and
  settings never collide with CabinetTron's. The database is the source of
  truth and the workbook is linked both ways (Brian 11/5/26): every app change
  is written to the workbook, and edits made in the workbook are merged back
  row by row, with a row changed on both sides flagged instead of overwritten.

Data lives on STERLING_DATA_DIR when set, else Render's /data disk, else a
sterling-data folder under backend/ for local dev.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

APP_DIR = Path(__file__).resolve().parent  # the sterling_app package (holds the seed workbook)
_default = Path("/data") if Path("/data").is_dir() else APP_DIR.parents[1] / "sterling-data"
DATA_DIR = Path(os.environ.get("STERLING_DATA_DIR", str(_default)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "ckb_pricing.db"


def _normalize(url: str) -> str:
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


SHARED_URL = os.environ.get("STERLING_DATABASE_URL") or None
SHARED = SHARED_URL is not None
_url = _normalize(SHARED_URL) if SHARED else f"sqlite:///{DB_PATH}"
# Postgres keeps Sterling in its own schema; SQLite has no schemas.
SCHEMA = "sterling" if _url.startswith("postgresql") else None

engine = create_engine(
    _url,
    connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {},
)
if SCHEMA:
    from sqlalchemy import text as _text

    with engine.begin() as _conn:
        _conn.execute(_text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
    engine = engine.execution_options(schema_translate_map={None: SCHEMA})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def qualified(table: str) -> str:
    """A table name ready for raw DDL in either mode."""
    return f'"{SCHEMA}"."{table}"' if SCHEMA else f'"{table}"'


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_columns() -> list[str]:
    """Add columns the models have gained since this cache file was written.

    create_all() only creates missing TABLES, so a new field on an existing
    model leaves the SQLite file a column short and every query on it fails.
    The workbook is the source of truth, so the data is safe either way — but
    adding the column in place beats deleting the cache and losing whatever had
    not been flushed to the workbook yet.
    """
    from sqlalchemy import inspect, text

    added: list[str] = []
    insp = inspect(engine)
    tables = set(insp.get_table_names(schema=SCHEMA))
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name, schema=SCHEMA)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = col.type.compile(engine.dialect)
                conn.execute(text(f'ALTER TABLE {qualified(table.name)} ADD COLUMN "{col.name}" {ddl}'))
                added.append(f"{table.name}.{col.name}")
    return added
