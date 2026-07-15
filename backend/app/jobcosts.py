"""Import Domo actual-cost rows into job_costs and compute per-house P&L.

Domo can only be pulled from a logged-in browser session, so the flow is:
a browser-side pull writes a JSON export (list of cost rows) to the Domo tool
folder; the app imports the newest one (manually via the report's Update
button, or by passing rows to import_rows directly after a live pull).

Each row keys to a job by i_code, then g_code, then job_code. Labor billed on
codes other than C9009 is recorded on the JobCost for review.
"""

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Job, JobCost

K_AND_B_LABOR_CODE = "C9009"


def _money(value) -> Decimal | None:
    if value is None or isinstance(value, str) and not value.strip().lstrip("-").replace(".", "").isdigit():
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _match_job(db: Session, row: dict) -> Job | None:
    for field in ("i_code", "g_code", "job_code"):
        val = row.get(field)
        if not val:
            continue
        col = {"i_code": Job.i_code, "g_code": Job.g_code, "job_code": Job.job_code}[field]
        job = db.query(Job).filter(col == str(val).strip()).first()
        if job:
            return job
    return None


def _format_other_labor(labor_codes: dict | None) -> str | None:
    """Labor billed on codes != C9009, formatted for display."""
    if not labor_codes:
        return None
    others = []
    for code, amt in labor_codes.items():
        if str(code).upper() == K_AND_B_LABOR_CODE:
            continue
        a = _money(amt)
        if a is not None and a != 0:
            others.append(f"{code}: ${a:,.2f}")
    return "; ".join(others) or None


def import_rows(db: Session, rows: list[dict], source: str | None = None) -> dict:
    counts = {"matched": 0, "unmatched": 0}
    for row in rows:
        job = _match_job(db, row)
        if job is None:
            counts["unmatched"] += 1
            continue
        cost = db.query(JobCost).filter(JobCost.job_id == job.id).first()
        if cost is None:
            cost = JobCost(job_id=job.id)
            db.add(cost)
        cost.revenue = _money(row.get("revenue"))
        cost.product_cost = _money(row.get("product_cost"))
        cost.labor_revenue = _money(row.get("labor_revenue"))
        cost.labor_cost = _money(row.get("labor_cost"))
        rev = (cost.revenue or 0) + (cost.labor_revenue or 0)
        cst = (cost.product_cost or 0) + (cost.labor_cost or 0)
        cost.margin = rev - cst if (cost.revenue is not None or cost.labor_cost is not None) else None
        cost.other_labor_codes = _format_other_labor(row.get("labor_codes"))
        cost.source_file = source
        counts["matched"] += 1
    db.commit()
    return counts


def latest_export(directory: Path) -> Path | None:
    files = [f for f in directory.glob("KB Job Costs*.json") if not f.name.startswith("~")]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def refresh_from_file(db: Session) -> dict:
    """Re-import the newest Domo cost export JSON (used by the Update button)."""
    directory = Path(get_settings().domo_export_dir)
    if not directory.is_dir():
        return {"error": f"folder not found: {directory}"}
    f = latest_export(directory)
    if f is None:
        return {"error": "no 'KB Job Costs*.json' export found — run the Domo pull first"}
    data = json.loads(f.read_text(encoding="utf-8"))
    rows = data.get("rows", data) if isinstance(data, dict) else data
    return {"file": f.name, **import_rows(db, rows, source=f.name)}
