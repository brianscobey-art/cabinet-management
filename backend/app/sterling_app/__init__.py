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



def mount(app: FastAPI) -> None:
    from app.api.deps import read_access
    from app.sterling_app import xlsx_store
    from app.sterling_app.api import router
    from app.sterling_app.database import Base, SessionLocal, engine

    Base.metadata.create_all(bind=engine)
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
