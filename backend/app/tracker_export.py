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
