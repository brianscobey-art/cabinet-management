"""Endpoints for the Smartsheet timeline + discrepancy report."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.deps import read_access, write_access
from app.config import get_settings
from app.database import get_db
from app.models import Job, PhaseUpdate, SmartsheetRow
from app.smartsheet import report as R
from app.smartsheet import sync as S

router = APIRouter(tags=["smartsheet"])


# Parsing the 3.0 tracker costs ~19 seconds -- it is a large .xlsm and openpyxl
# cannot open it read-only here (the DATA table's range comes from ws.tables).
# Doing that on every page load made the report unusable, so the parse is cached
# against the file's identity: same name, size and mtime means same rows, and a
# saved workbook re-reads on the next request.
_TRACKER_CACHE: dict[str, object] = {"key": None, "rows": [], "ok": False, "name": None}


def _tracker_rows() -> tuple[list[dict], bool, str | None]:
    """Newest READABLE 3.0 tracker. The live .xlsm is routinely open in Excel,
    so fall through the recent copies rather than reporting no data."""
    try:
        from app.storage import TRACKER_GLOB
        from scripts.import_tracker import load_rows
    except Exception:  # noqa: BLE001 — tracker reader unavailable in this deploy
        return [], False, None
    folder = Path(get_settings().tracker_dir)
    if not folder.is_dir():
        return [], False, None
    files = sorted(folder.glob(TRACKER_GLOB), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    for f in files[:5]:
        try:
            stat = f.stat()
            key = f"{f.name}|{stat.st_size}|{int(stat.st_mtime)}"
            if _TRACKER_CACHE["key"] == key:
                return _TRACKER_CACHE["rows"], True, _TRACKER_CACHE["name"]
            rows = load_rows(f)
            _TRACKER_CACHE.update(key=key, rows=rows, ok=True, name=f.name)
            return rows, True, f.name
        except (PermissionError, OSError):
            continue
    return [], False, None


def _with_audit(db: Session, data: dict) -> dict:
    """Attach the tracker-first audit. Export only.

    It is ~284 rows x 26 fields that the web report never renders, and the JSON
    response is already half a megabyte, so the page must not pay for it.
    """
    from app.smartsheet import audit

    # Re-reading the tracker is free -- _tracker_rows caches on the file's
    # identity -- and keeps 1.5MB of raw rows out of the report dict, where the
    # web endpoint would have had to remember to strip them.
    tracker, _, _ = _tracker_rows()
    data["audit"] = audit.build(tracker, S.stored_rows(db),
                                drop_levels=R.DROPPED_CONST_LVLS)
    data["audit_summary"] = audit.summary(data["audit"])
    return data


def _build(db: Session) -> dict:
    jobs = (db.query(Job)
            .options(joinedload(Job.community), joinedload(Job.account))
            .all())
    sub = (db.query(PhaseUpdate.job_id, func.max(PhaseUpdate.id).label("mid"))
           .group_by(PhaseUpdate.job_id).subquery())
    phases = {p.job_id: (p.phase, p.noted_at)
              for p in db.query(PhaseUpdate).join(sub, PhaseUpdate.id == sub.c.mid)}
    tracker, ok, name = _tracker_rows()
    # The builder's own portal -- VendorSuite for DR Horton, SupplyPro for
    # Century. Read live from the feed folders, same as the tracker leg.
    from app.smartsheet.portal import load as load_portal

    s = get_settings()
    try:
        portal_rows, portal_meta = load_portal(
            s.vendorsuite_dir, s.century_dir, s.century_alt_dir)
    except Exception as exc:  # noqa: BLE001 — the other three sources still work
        portal_rows, portal_meta = [], {"error": str(exc)}
    data = R.build(S.stored_rows(db), jobs, tracker, phases=phases, tracker_ok=ok,
                   portal_rows=portal_rows, portal_meta=portal_meta)
    data["tracker_file"] = name
    latest = db.query(func.max(SmartsheetRow.pulled_at)).scalar()
    data["pulled_at"] = latest.isoformat() if latest else None
    return data


@router.get("/reports/smartsheet", dependencies=[Depends(read_access)])
def smartsheet_report(db: Session = Depends(get_db),
                      builder: str | None = Query(None),
                      status: str | None = Query(None)):
    """The full report. Filtering happens here so the browser is not handed
    3,000 houses to sift on every keystroke."""
    data = _build(db)
    rows = data["rows"]
    if builder:
        rows = [r for r in rows if r["builder"] == builder]
    if status:
        rows = [r for r in rows if r["status"] == status]
    data["rows"] = rows
    data["builders"] = sorted({r["builder"] for r in data["rows"] if r["builder"]})
    return data


@router.post("/reports/smartsheet/sync", dependencies=[Depends(write_access)])
def smartsheet_sync(db: Session = Depends(get_db)):
    """Pull now rather than waiting for the nightly run."""
    s = get_settings()
    return S.sync(db, token=s.smartsheet_api_token or None, folder=s.smartsheet_folder)


@router.post("/reports/smartsheet/push", dependencies=[Depends(write_access)])
def smartsheet_push(db: Session = Depends(get_db)):
    """Push the live job list to the CabinetTron Job Tracker sheet, now.

    The only write CabinetTron makes to Smartsheet, and it targets one sheet it
    created and owns. write_access rather than read_access on purpose: this
    changes something outside the app.
    """
    from app.smartsheet.job_tracker import apply_formats, push, shape

    s = get_settings()
    if not s.smartsheet_api_token:
        return {"error": "no Smartsheet token configured"}
    if not (s.smartsheet_push_enabled and s.smartsheet_job_sheet_id):
        return {"error": "push disabled"}
    rows, ok, name = _tracker_rows()
    if not ok or not rows:
        return {"error": "tracker unreadable (open in Excel?)"}
    records = shape(rows)
    result = push(s.smartsheet_api_token, s.smartsheet_job_sheet_id, records)
    # Formatting lives on the column and survives a push, so this is a no-op
    # almost every time -- it is here so a rebuilt or hand-edited sheet comes
    # back to the agreed layout without anyone remembering to ask.
    try:
        apply_formats(s.smartsheet_api_token, s.smartsheet_job_sheet_id)
    except Exception as exc:  # noqa: BLE001 — the rows are already in
        result["format_warning"] = str(exc)
    return {"tracker": name, "jobs": len(records), **result}


def _tracker_file():
    """The newest tracker workbook that can be opened. POTracker lives in the
    same workbook as DATA, on a different sheet."""
    from app.storage import TRACKER_GLOB

    folder = Path(get_settings().tracker_dir)
    if not folder.is_dir():
        return None
    for f in sorted(folder.glob(TRACKER_GLOB), key=lambda p: p.stat().st_mtime,
                    reverse=True)[:5]:
        try:
            with open(f, "rb"):
                return f
        except (PermissionError, OSError):
            continue
    return None


def _po_records(db: Session, tracker_rows: list[dict]) -> list[dict]:
    """POTracker lines resolved against DATA and CabinetTron's receipts, shaped
    as job parents with PO children. Receipts come from po_receipts (the DOMO
    pipeline) rather than the block pasted beside the workbook's table, so the
    sheet moves when the receipts do."""
    from app.models import PoReceipt
    from app.smartsheet import po_tracker as P

    f = _tracker_file()
    if f is None:
        return []
    receipts: dict[str, dict] = {}
    for rc in db.query(PoReceipt).filter(PoReceipt.order_number.isnot(None)):
        receipts.setdefault(str(rc.order_number).strip().split(".")[0], {
            "receipt_date": rc.receipt_date.isoformat() if rc.receipt_date else None,
            "supplier": rc.supplier,
            "landed_cost": float(rc.landed_cost) if rc.landed_cost is not None else None,
        })
    return P.shape(P.resolve(P.read_potracker(f), tracker_rows, receipts))


@router.post("/reports/smartsheet/push-pos", dependencies=[Depends(write_access)])
def smartsheet_push_pos(db: Session = Depends(get_db)):
    """Push POTracker to the CabinetTron PO Tracker sheet, now. The second of
    the two sheets CabinetTron writes; still never the Masters."""
    from app.smartsheet import po_tracker as P

    s = get_settings()
    if not s.smartsheet_api_token:
        return {"error": "no Smartsheet token configured"}
    if not (s.smartsheet_push_enabled and s.smartsheet_po_sheet_id):
        return {"error": "push disabled"}
    rows, ok, name = _tracker_rows()
    if not ok or not rows:
        return {"error": "tracker unreadable (open in Excel?)"}
    records = _po_records(db, rows)
    if not records:
        return {"error": "POTracker unreadable"}
    result = P.push(s.smartsheet_api_token, s.smartsheet_po_sheet_id, records)
    try:
        P.apply_formats(s.smartsheet_api_token, s.smartsheet_po_sheet_id)
    except Exception as exc:  # noqa: BLE001
        result["format_warning"] = str(exc)
    return {"tracker": name, **result}


@router.get("/reports/smartsheet/export", dependencies=[Depends(read_access)])
def smartsheet_export(db: Session = Depends(get_db)):
    """Excel: a summary tab, the coverage evidence, then one tab per builder."""
    from app.smartsheet.export import to_xlsx

    data = _with_audit(db, _build(db))
    buf = to_xlsx(data)
    name = f"Smartsheet vs CabinetTron {dt.date.today():%m%d%y}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
