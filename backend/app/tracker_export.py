"""Phase data pushed back OUT to the 3.0 Online Sales Tracker.

Feeds the tracker's "Import Data" sheet (table Table21), whose columns are:
    Job Code | Date Checked | Phase | Date Measured | Full Phase
"Full Phase" is a calculated XLOOKUP column in the workbook — we never write it.

Only phase-tracked, active houses that have actually been checked are exported,
so Date Checked and Phase are always populated (a blank Phase would make the
workbook's XLOOKUP throw #N/A). Date Measured is blank when not yet measured.
"""

import csv
import io

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.models import Job, PhaseUpdate
from app.phases import PHASE_HIDDEN_STATUSES

COLUMNS = ["Job Code", "Date Checked", "Phase", "Date Measured"]


def rows(db) -> list[dict]:
    """Latest phase check per job, newest first by job code."""
    latest = (
        db.query(PhaseUpdate.job_id, func.max(PhaseUpdate.id).label("max_id"))
        .group_by(PhaseUpdate.job_id)
        .subquery()
    )
    updates = {
        pu.job_id: pu
        for pu in db.query(PhaseUpdate).join(latest, PhaseUpdate.id == latest.c.max_id).all()
    }
    jobs = (
        db.query(Job)
        .options(joinedload(Job.community))
        .filter(Job.job_code.isnot(None), Job.status.notin_(PHASE_HIDDEN_STATUSES))
        .all()
    )
    out = []
    for j in sorted(jobs, key=lambda x: (x.job_code or "")):
        pu = updates.get(j.id)
        if pu is None:
            continue  # never checked — nothing to report
        out.append({
            "Job Code": j.job_code,
            "Date Checked": pu.noted_at.date().isoformat() if pu.noted_at else "",
            "Phase": pu.phase or "",                       # already just the number
            "Date Measured": j.measure_date.isoformat() if j.measure_date else "",
        })
    return out


def full_phase(code: str | None) -> str:
    """'12' -> '12-Cabinets Installed', '4.1' -> '4.1-Pre Walk Complete': the
    tracker's "Full Phase" style (code-name, no spaces round the dash), from
    CabinetTron's own phase list -- the tracker's PhasesTable stops at the old
    '12-TKB Cab Installed' and predates the 4.x renumber (Brian 10/26/26)."""
    from app.phases import PHASE_LABELS

    if not code:
        return ""
    label = PHASE_LABELS.get(str(code))
    return label.replace(" - ", "-", 1) if label else str(code)


def _excel_phase(code: str):
    """'12' -> 12, '4.1' -> 4.1: the workbook's PhasesTable keys are numbers,
    so a text "12" pasted in would make Full Phase's XLOOKUP miss."""
    try:
        f = float(code)
    except (TypeError, ValueError):
        return code
    return int(f) if f.is_integer() else f


LIVE_COLUMNS = ["Job Code", "Date Checked", "Phase", "Date Measured", "Full Phase", "Pulled"]


def pulled_at():
    """When the tracker pulled this feed, in Dothan (Central) time to the
    minute -- Render runs in UTC. The tracker's Import Data A1 shows it as
    "Last update: 10/27/26, 4:36am" (Brian 10/27/26)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/Chicago")).replace(tzinfo=None, second=0, microsecond=0)


def live_rows(db) -> list[list]:
    """Every house in CabinetTron with a job code, for the tracker's live
    Import Data link (Brian 10/26/26: "all houses ... if there is no data
    then it will return nothing"). A house with no phase logged still gets a
    row, with blank Date Checked / Phase, so lookups against the table come
    back empty rather than missing."""
    latest = (
        db.query(PhaseUpdate.job_id, func.max(PhaseUpdate.id).label("max_id"))
        .group_by(PhaseUpdate.job_id)
        .subquery()
    )
    updates = {
        pu.job_id: pu
        for pu in db.query(PhaseUpdate).join(latest, PhaseUpdate.id == latest.c.max_id).all()
    }
    out = []
    for j in sorted(db.query(Job).filter(Job.job_code.isnot(None)).all(), key=lambda x: x.job_code or ""):
        pu = updates.get(j.id)
        out.append([
            j.job_code,
            pu.noted_at.date() if pu and pu.noted_at else None,
            _excel_phase(pu.phase) if pu and pu.phase else None,
            j.measure_date,
            full_phase(pu.phase) if pu else "",
        ])
    return out


def live_csv(db) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(LIVE_COLUMNS)
    pulled = pulled_at().isoformat(timespec="minutes")
    for code, checked, phase, measured, lvl in live_rows(db):
        w.writerow([code, checked.isoformat() if checked else "", "" if phase is None else phase,
                    measured.isoformat() if measured else "", lvl, pulled])
    return buf.getvalue()


def phase_report_xlsx(db) -> tuple[bytes, int, int]:
    """The Phase Report for pasting into the tracker's Import Data table
    (Brian 10/26/26): DR Horton + Century houses at CONST LVL 1.x-4.x, one row
    per house with its current phase and the date it was last updated, in the
    table's own column order (Job Code | Date Checked | Phase | Date Measured)
    so the block pastes straight over A4:D. Houses never checked are left out
    -- a blank Phase would make Full Phase show #N/A.
    Returns (xlsx bytes, rows written, houses skipped for no phase)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    from app.models import Account

    latest = (
        db.query(PhaseUpdate.job_id, func.max(PhaseUpdate.id).label("max_id"))
        .group_by(PhaseUpdate.job_id)
        .subquery()
    )
    updates = {
        pu.job_id: pu
        for pu in db.query(PhaseUpdate).join(latest, PhaseUpdate.id == latest.c.max_id).all()
    }
    jobs = (
        db.query(Job).join(Account, Job.account_id == Account.id)
        .filter(Job.job_code.isnot(None))
        .all()
    )
    keep = []
    skipped = 0
    for j in jobs:
        acct = (j.account.name if j.account else "").lower()
        if not (acct.startswith("dr horton") or acct.startswith("century")):
            continue
        level = (j.status.value if hasattr(j.status, "value") else str(j.status or ""))[:1]
        if level not in ("1", "2", "3", "4"):
            continue
        pu = updates.get(j.id)
        if pu is None or not pu.phase:
            skipped += 1
            continue
        keep.append((j, pu))
    keep.sort(key=lambda t: t[0].job_code or "")

    wb = Workbook()
    ws = wb.active
    ws.title = "Import Data"
    # Column E is the phase written out ("12-Cabinets Installed") -- Brian
    # 10/26/26 swapped it from CONST LVL to the tracker's Full Phase style.
    ws.append(COLUMNS + ["Full Phase"])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="125952")
        c.alignment = Alignment(horizontal="center")
    for j, pu in keep:
        ws.append([
            j.job_code,
            pu.noted_at.date() if pu.noted_at else None,
            _excel_phase(pu.phase),
            j.measure_date,
            full_phase(pu.phase),
        ])
    for row in ws.iter_rows(min_row=2):
        for c in row[1:]:
            c.alignment = Alignment(horizontal="center")
        row[1].number_format = "m/d/yy"
        row[3].number_format = "m/d/yy"
    for col, width in zip("ABCDE", (16, 14, 10, 15, 30)):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), len(keep), skipped


def to_csv(db) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows(db))
    return buf.getvalue()


# --- Deliveries (PO receipts) -> the tracker's "Deliveries" sheet ------------
# Same idea as Import Data, different payload: the receipts the Operations
# report shows. Only receipts matched to one of our jobs through POTracker —
# the raw DOMO list covers every Carter store and department, and the unmatched
# rows are windows/millwork with no cabinet job behind them.
DELIVERY_COLUMNS = [
    "Job Code", "Receipt #", "Receipt Date", "Supplier",
    "Supplier Cost", "Landed Cost", "Order #", "Product",
]


def _supplier_name(s: str | None) -> str:
    """DOMO writes "70408: EVERYTHING BUILDING PRODUCTS LLC" — drop the code."""
    if not s:
        return ""
    return s.split(":", 1)[1].strip() if ":" in s else s.strip()


def delivery_rows(db) -> list[dict]:
    """Matched receipts, newest first. Reuses the report's join so the sheet and
    the Operations page can never disagree."""
    from app.po_receipts import build_report

    out = []
    for r in build_report(db).get("rows", []):
        if not r.get("job_code"):
            continue  # receipt for a PO we track but a job we don't — skip
        out.append({
            "Job Code": r["job_code"],
            "Receipt #": r.get("receipt_number") or "",
            "Receipt Date": r.get("receipt_date") or "",
            "Supplier": _supplier_name(r.get("supplier")),
            "Supplier Cost": r.get("supplier_cost") if r.get("supplier_cost") is not None else "",
            "Landed Cost": r.get("landed_cost") if r.get("landed_cost") is not None else "",
            "Order #": r.get("order_number") or "",
            "Product": r.get("product") or "",
        })
    return out


def deliveries_to_csv(db) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=DELIVERY_COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(delivery_rows(db))
    return buf.getvalue()


def deliveries_to_tsv(db) -> str:
    """Tab-separated for the Excel Online route: put this on the clipboard and
    one paste fills the sheet. Commas in supplier names would split cells in CSV."""
    rows_ = delivery_rows(db)
    lines = ["\t".join(DELIVERY_COLUMNS)]
    lines.extend("\t".join(str(r[c]) for c in DELIVERY_COLUMNS) for r in rows_)
    return "\n".join(lines)
