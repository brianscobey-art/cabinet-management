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
