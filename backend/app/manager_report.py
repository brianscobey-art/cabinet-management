"""Manager's Sales Report — pipeline visibility for upper management.

Pulls installed-by-period, open pipeline, YTD sales by KSR, the official P&L net
sales, and the field-capacity / travel-miles story into one payload. Shared by
the authed endpoint and the public read-only link.
"""

from datetime import date, datetime, timedelta, timezone
from math import ceil

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.models import Job, JobStatus
from app.pl_report import read_net_sales
from app.sales import KSR_ROSTER, effective_ksr
from app.travel import fill_base_miles, job_miles

INACTIVE = (JobStatus.closed, JobStatus.void)
NEW_Q2_KSRS = {"Paula Cook", "Laurie Reel"}


def _period_bounds(today: date) -> dict:
    first_this = today.replace(day=1)
    prev_month_end = first_this - timedelta(days=1)
    first_prev = prev_month_end.replace(day=1)
    cur_q_start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
    prev_q_end = cur_q_start - timedelta(days=1)
    prev_q_start = date(prev_q_end.year, ((prev_q_end.month - 1) // 3) * 3 + 1, 1)
    return {
        "current_month": (first_this, today, first_this.strftime("%B %Y")),
        "previous_month": (first_prev, prev_month_end, first_prev.strftime("%B %Y")),
        "previous_quarter": (prev_q_start, prev_q_end, f"Q{(prev_q_start.month - 1)// 3 + 1} {prev_q_start.year}"),
        "ytd": (date(today.year, 1, 1), today, f"YTD {today.year}"),
    }


def _money(v) -> float:
    return round(float(v or 0), 2)


def build(db, today: date | None = None) -> dict:
    s = get_settings()
    today = today or date.today()
    bounds = _period_bounds(today)

    # 1) Houses installed by period (Actual Install Date in range; drop void).
    installed = {}
    for key, (start, end, label) in bounds.items():
        cnt, tot = db.query(
            func.count(Job.id), func.coalesce(func.sum(Job.po_amount), 0)
        ).filter(
            Job.status != JobStatus.void,
            Job.install_date.isnot(None),
            Job.install_date >= start, Job.install_date <= end,
        ).one()
        installed[key] = {"label": label, "count": cnt or 0, "po_total": _money(tot)}

    # 2) Open pipeline — has a PO, active, not yet installed.
    cnt, tot = db.query(
        func.count(Job.id), func.coalesce(func.sum(Job.po_amount), 0)
    ).filter(
        Job.status.notin_(INACTIVE),
        Job.po_amount.isnot(None), Job.po_amount > 0,
        or_(Job.install_date.is_(None), Job.install_date > today),
    ).one()
    open_pipeline = {"count": cnt or 0, "po_total": _money(tot)}

    # 3) Sales by KSR YTD (closed + open combined, dated by sale_date).
    ytd_start = date(today.year, 1, 1)
    ysales = (
        db.query(Job).options(joinedload(Job.account))
        .filter(Job.status != JobStatus.void,
                Job.sale_date.isnot(None),
                Job.sale_date >= ytd_start, Job.sale_date <= today)
        .all()
    )
    agg: dict[str, list] = {}
    for j in ysales:
        k = effective_ksr(j) or "Unassigned"
        row = agg.setdefault(k, [0, 0.0])
        row[0] += 1
        row[1] += float(j.po_amount or 0)
    by_ksr = [
        {"ksr": k, "count": c, "po_total": round(t, 2), "is_new_q2": k in NEW_Q2_KSRS}
        for k, (c, t) in agg.items()
    ]
    by_ksr.sort(key=lambda r: (r["ksr"] == "Unassigned", -r["po_total"]))

    # 4) Official P&L net sales (newest workbook).
    pl = read_net_sales(s)

    # 5) Field capacity + travel miles.
    try:
        fill_base_miles(db, s, max_jobs=400)  # warm the OSRM cache (no-op once full)
    except Exception:  # noqa: BLE001 — miles fall back to estimates
        pass
    active_jobs = (
        db.query(Job).options(joinedload(Job.account))
        .filter(Job.status.notin_(INACTIVE)).all()
    )
    active_count = len(active_jobs)
    trips = s.ksr_trips_per_job
    miles_agg: dict[str, list] = {}
    any_estimated = False
    for j in active_jobs:
        m = job_miles(j, s)
        if m is None:
            continue
        if j.base_drive_miles is None:
            any_estimated = True
        k = effective_ksr(j) or "Unassigned"
        row = miles_agg.setdefault(k, [0, 0.0])
        row[0] += 1
        row[1] += m * trips * 2  # round trip
    by_ksr_miles = [
        {"ksr": k, "jobs": c, "monthly_miles": round(t)}
        for k, (c, t) in sorted(miles_agg.items(), key=lambda kv: -kv[1][1])
    ]
    capacity = {
        "active_houses": active_count,
        "houses_per_person": s.ksr_houses_per_year,
        "field_people_needed": ceil(active_count / s.ksr_houses_per_year) if s.ksr_houses_per_year else None,
        "coverage_sq_miles": s.coverage_sq_miles,
        "trips_per_job": trips,
        "by_ksr_miles": by_ksr_miles,
        "miles_estimated": any_estimated,
        "total_monthly_miles": round(sum(r["monthly_miles"] for r in by_ksr_miles)),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": today.isoformat(),
        "roster": KSR_ROSTER,
        "installed": installed,
        "open_pipeline": open_pipeline,
        "by_ksr": by_ksr,
        "pl_net_sales": pl,
        "capacity": capacity,
    }
