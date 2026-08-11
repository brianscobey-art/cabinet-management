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
