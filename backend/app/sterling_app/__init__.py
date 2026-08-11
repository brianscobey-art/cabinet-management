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


def mount(app: FastAPI) -> None:
    from app.api.deps import read_access
    from app.sterling_app import xlsx_store
    from app.sterling_app.api import router
    from app.sterling_app.database import Base, SessionLocal, engine

    Base.metadata.create_all(bind=engine)
    # every committed change debounce-saves the workbook
    event.listens_for(SessionLocal, "after_commit")(lambda session: xlsx_store.mark_dirty())
    xlsx_store.startup()  # seed/load the workbook into the cache

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
