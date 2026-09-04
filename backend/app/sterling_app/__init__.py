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
        _apply_data_fixes(db)


# Data corrections made against one copy of the workbook that every copy
# needs — the hosted app keeps its own on Render's /data disk, and git only
# seeds a fresh disk. Each fix runs once per disk, keyed by its Setting flag,
# and is a no-op wherever the values already match.
DATA_FIXES = [
    ("data_fix_2026_09_04_install_rules", {
        # sku -> field: value. Fillers, skins and the touch-up kit carry no
        # install box; the dishwasher return panel installs but is not assembled.
        "catalog": {
            "DWR3": {"assemble_value": 0},
            **{s: {"install_value": 0} for s in (
                "BSV", "TUK", "F342", "F396", "F642", "F696", "F124", "F130", "F136",
                "F142", "F148", "F160", "F224", "F230", "F236", "F242", "F248", "F260")},
        },
        # (division, plan) -> sku: qty (None drops the line). Reconciled to the
        # Everluxe sales orders for the Aisle (SO46632) and Embry (SO45881).
        "plan_templates": {
            ("DRH PC", "EX1 Aisle STD"): {"F642": 3, "SHM": 6, "BSV": 9, "WSV42": 4},
            ("DRH PC", "DRH1 Embry STD"): {"VS30": 5, "VS36": None, "BSV": 6, "WSV42": 4},
        },
    }),
]


def _apply_data_fixes(db) -> None:
    from sqlalchemy import func

    from app.sterling_app.models import CatalogItem, PlanTemplateItem, Setting

    for key, fix in DATA_FIXES:
        if db.get(Setting, key):
            continue
        for sku, fields in fix.get("catalog", {}).items():
            item = (db.query(CatalogItem)
                    .filter(CatalogItem.vendor == "Everluxe",
                            func.upper(CatalogItem.sku) == sku.upper())
                    .first())
            if item is None:
                continue
            for field, value in fields.items():
                setattr(item, field, value)
        for (division, plan), skus in fix.get("plan_templates", {}).items():
            existing = (db.query(PlanTemplateItem)
                        .filter(PlanTemplateItem.division == division,
                                PlanTemplateItem.plan == plan).all())
            if not existing:            # this disk never had the plan — nothing to correct
                continue
            by_sku = {i.sku.strip().upper(): i for i in existing}
            for sku, qty in skus.items():
                item = by_sku.get(sku.upper())
                if qty is None:
                    if item is not None:
                        db.delete(item)
                elif item is not None:
                    item.qty = qty
                else:
                    db.add(PlanTemplateItem(division=division, plan=plan, sku=sku,
                                            qty=qty, area="All"))
        db.add(Setting(key=key, value="1"))
        db.commit()
        print(f"Sterling: applied {key}")


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
