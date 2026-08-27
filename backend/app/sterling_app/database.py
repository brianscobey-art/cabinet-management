"""Sterling's own SQLite cache + Excel workbook, INSIDE CabinetTron.

Sterling keeps its own engine on purpose: the Excel workbook is the source of
truth (see xlsx_store) and this SQLite file is a disposable runtime cache —
none of it touches CabinetTron's Postgres.

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

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


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
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = col.type.compile(engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}'))
                added.append(f"{table.name}.{col.name}")
    return added
