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
# Overhead/rebill "wash" codes: they net ~$0 company-wide but park cost on cabinet
# jobs (C9091 install-sales allocation, C9002 labor rebill). Per Brian, they are NOT
# real cabinet labor — shown for transparency but excluded from the cabinet margin.
MARGIN_EXCLUDED_LABOR_CODES = {"C9091", "C9002"}

# For DR Horton jobs, the DRH Combined report's PO amount (what DRH actually pays) is
# the authoritative revenue — used in lieu of Domo's product sales. Voided POs never
# count; every other status (Paid, Vouchered, Open) does. Flip to {"paid"}-only by
# swapping this for an included-set check if Brian wants realized cash only.
DRH_ACCOUNT_PREFIX = "DR Horton"
DRH_PO_EXCLUDED_STATUSES = {"voided"}


def drh_po_revenue(job, cost) -> tuple[float, str]:
    """Product-side revenue for the P&L: the DRH builder PO in lieu of Domo where it applies.

    Returns (product_revenue, source) with source "DRH PO" or "Domo".
    """
    name = (job.account.name if getattr(job, "account", None) else "") or ""
    if name.startswith(DRH_ACCOUNT_PREFIX) and job.po_amount is not None:
        if (job.po_status or "").strip().lower() not in DRH_PO_EXCLUDED_STATUSES:
            return float(job.po_amount), "DRH PO"
    return float(cost.revenue or 0), "Domo"


def pl_components(job, cost) -> tuple[float, float, float, float, str]:
    """(revenue, cost, other_labor_net, all_in_margin, revenue_source) for a house,
    with the DRH-PO revenue override applied. Revenue = product (DRH PO or Domo) +
    C9009 labor billed; margin folds in real non-C9009 labor (wash codes excluded)."""
    prod_rev, source = drh_po_revenue(job, cost)
    revenue = prod_rev + float(cost.labor_revenue or 0)
    cost_total = float(cost.product_cost or 0) + float(cost.labor_cost or 0)
    other_net = float(cost.other_labor_net or 0)
    return revenue, cost_total, other_net, revenue - cost_total + other_net, source


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


def _fmt_signed(a: Decimal) -> str:
    """-1234.5 -> '-$1,234.50', 200 -> '$200.00'."""
    return f"-${abs(a):,.2f}" if a < 0 else f"${a:,.2f}"


def _other_labor(labor_codes: dict | None) -> tuple[Decimal, str | None, Decimal]:
    """Split net P&L of non-C9009 labor into real cabinet labor vs overhead wash.

    Each labor_codes value is already the net dollars for that code on the job.
    Returns (included_net, included_display, wash_net):
      - included_net folds into the cabinet margin (real miscoded install labor),
      - wash_net is the excluded C9091/C9002 overhead/rebill parked on the job.
    """
    if not labor_codes:
        return Decimal("0"), None, Decimal("0")
    included = Decimal("0")
    wash = Decimal("0")
    parts = []
    for code, amt in labor_codes.items():
        code_u = str(code).upper()
        if code_u == K_AND_B_LABOR_CODE:
            continue
        a = _money(amt)
        if a is None or a == 0:
            continue
        if code_u in MARGIN_EXCLUDED_LABOR_CODES:
            wash += a
        else:
            included += a
            parts.append(f"{code}: {_fmt_signed(a)}")
    return included, ("; ".join(parts) or None), wash


def import_rows(db: Session, rows: list[dict], source: str | None = None) -> dict:
    counts = {"matched": 0, "unmatched": 0}
    seen: dict[int, JobCost] = {}  # dedupe rows that resolve to the same job in one batch
    for row in rows:
        job = _match_job(db, row)
        if job is None:
            counts["unmatched"] += 1
            continue
        cost = seen.get(job.id) or db.query(JobCost).filter(JobCost.job_id == job.id).first()
        if cost is None:
            cost = JobCost(job_id=job.id)
            db.add(cost)
            db.flush()
        seen[job.id] = cost
        cost.revenue = _money(row.get("revenue"))
        cost.product_cost = _money(row.get("product_cost"))
        cost.labor_revenue = _money(row.get("labor_revenue"))
        cost.labor_cost = _money(row.get("labor_cost"))
        other_net, other_str, wash_net = _other_labor(row.get("labor_codes"))
        cost.other_labor_net = other_net if other_str else None
        cost.other_labor_codes = other_str
        cost.wash_labor_net = wash_net if wash_net != 0 else None
        rev = (cost.revenue or 0) + (cost.labor_revenue or 0)
        cst = (cost.product_cost or 0) + (cost.labor_cost or 0)
        # all-in cabinet margin: product + C9009 + real non-C9009 labor (wash codes excluded)
        has_data = cost.revenue is not None or cost.labor_cost is not None or other_str
        cost.margin = (rev - cst + other_net) if has_data else None
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
