"""Sterling — the COAST suite's pricing app, mounted inside CabinetTron.

Runs at /sterling (page) + /sterling/api/* (endpoints), the same pattern as
Optimus (/ordering-platform) and Autobot. Sterling keeps its own storage: the
Excel workbook on the data disk is the source of truth, SQLite is a cache —
CabinetTron's Postgres is untouched. API access requires an office login.
"""

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import event


def _ensure_columns(engine) -> None:
    """Add columns that create_all() cannot.

    Sterling has no migration tool — Base.metadata.create_all() creates missing
    TABLES but never alters an existing one, so a new column on a model that is
    already in the SQLite file is silently absent until someone deletes the db.
    Each ALTER is idempotent and additive; nothing here drops or rewrites.
    """
    from sqlalchemy import inspect, text

    wanted = {
        "plan_tops": [
            ("k_cutouts", "INTEGER"),
            ("v_cutouts", "INTEGER"),
            ("k_sink_rate", "NUMERIC(8, 2)"),
            ("k_cutout_rate", "NUMERIC(8, 2)"),
            ("v_sink_rate", "NUMERIC(8, 2)"),
            ("v_cutout_rate", "NUMERIC(8, 2)"),
        ],
    }
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _seed_cover_refs(SessionLocal) -> None:
    """First run only: the PO-type presets and superintendents from Brian's
    cover-sheet workbook. Both are editable in the app (and in the workbook)."""
    from app.sterling_app.models import CoverVendor, Superintendent

    VENDORS = [
        ("product", "Cabinets", "CAB", "Everything Building Products", "70408"),
        ("product", "Building Materials", "BLD", "Carter Building Materials", "10003"),
        ("product", "Countertops", "CTP", None, None),
        ("product", "Hardware", "HDW", "Hardware Resources", None),
        ("labor", "Install", "INS", "Lynn's Cabinet Installation", "953426"),
        ("labor", "Assembly", "ASM", None, None),
    ]
    SUPERS = [
        ("Dylan Pope", "8503380165", "dylan@jubileebuilders.com"),
        ("Larry Wooley", "3346481422", "larry@jubileebuilders.com"),
        ("Calvin Nowell", "3343798441", "calvinnowell1999@gmail.com"),
        ("Kyle Whitehead", "3346617473", "kyle@tollesonconstruction.com"),
        ("Justin Killebrew", "3347465617", "justin@jubileebuilders.com"),
        ("Suzanne Vickers", "8502581460", "suzanne@vickersconstruction.com"),
        ("Summer Holt", "7015903315", "summer@phillipshomesfl.com"),
        ("Ryan Swinney", "8506280319", "swinneymma@gmai.com"),
    ]
    with SessionLocal() as db:
        if not db.query(CoverVendor).first():
            for kind, po_type, abb, vendor, code in VENDORS:
                db.add(CoverVendor(kind=kind, po_type=po_type, po_abb=abb,
                                   vendor=vendor, vendor_code=code))
        if not db.query(Superintendent).first():
            for name, phone, email in SUPERS:
                db.add(Superintendent(name=name, phone=phone, email=email))
        db.commit()
        _fix_cover_tax(db)


def _fix_cover_tax(db) -> None:
    """One-time: sales tax is always 7%. Early cover sheets were seeded at 9%
    (read off Brian's sample workbook) — correct them, once."""
    from decimal import Decimal

    from app.sterling_app.models import CoverSheet, Setting

    flag = db.get(Setting, "cover_tax_7_applied")
    if flag:
        return
    db.query(CoverSheet).filter(CoverSheet.tax_pct == Decimal("9")).update(
        {CoverSheet.tax_pct: Decimal("7")}, synchronize_session=False
    )
    db.add(Setting(key="cover_tax_7_applied", value="1"))
    db.commit()



def mount(app: FastAPI) -> None:
    from app.api.deps import read_access
    from app.sterling_app import xlsx_store
    from app.sterling_app.api import router
    from app.sterling_app.database import Base, SessionLocal, engine, ensure_columns

    Base.metadata.create_all(bind=engine)
    for col in ensure_columns():          # models gained a field since last boot
        print(f"Sterling: added {col}")
    _ensure_columns(engine)
    # every committed change debounce-saves the workbook
    event.listens_for(SessionLocal, "after_commit")(lambda session: xlsx_store.mark_dirty())
    xlsx_store.startup()  # seed/load the workbook into the cache
    _seed_cover_refs(SessionLocal)

    def _flush():
        if xlsx_store.state["dirty"]:
            xlsx_store.save_now()

    app.router.on_shutdown.append(_flush)

    app.include_router(router, prefix="/sterling", dependencies=[Depends(read_access)])

    static = Path(__file__).resolve().parent / "static"

    @app.get("/sterling", include_in_schema=False)
    def sterling_page():
        # no-cache so open tabs pick up new builds immediately
        return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})
