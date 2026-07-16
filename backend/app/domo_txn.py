"""Domo transaction ingest + the date-sliced Domo P&L aggregation.

The browser transaction pull writes dated cost/sales lines to a
``KB Job Txns*.json`` export in the Domo tool folder. import_txns() loads the
newest one (full refresh), matching each line to a job by G/I code prefix so the
report can slice by builder, job, date window, quarter, half-year, YTD, or
year-over-year.
"""

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.jobcosts import drh_po_revenue
from app.models import DomoTxn, Job, JobCost

K_AND_B_LABOR_CODE = "C9009"
WASH_CODE = "C9091"  # stand-in sku for the excluded overhead/rebill net when snapshot-derived


def _num(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _prefix(job_field) -> str:
    return str(job_field or "").split(":")[0].strip()


def _parse_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    s = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _job_lookup(db: Session) -> dict[str, Job]:
    """code prefix (g_code or i_code) -> Job."""
    lookup: dict[str, Job] = {}
    for job in db.query(Job).filter((Job.g_code.isnot(None)) | (Job.i_code.isnot(None))).all():
        for code in (job.g_code, job.i_code):
            if code:
                lookup[code.strip()] = job
    return lookup


def import_txns(db: Session, rows: list[dict], source: str | None = None) -> dict:
    """Full-refresh the domo_txns table from a list of dated transaction lines.

    Each row: {"date", "job", "sku", "sales", "cost"}.
    """
    db.query(DomoTxn).delete()
    lookup = _job_lookup(db)
    inserted = matched = 0
    for r in rows:
        prefix = _prefix(r.get("job"))
        if not prefix:
            continue
        job = lookup.get(prefix)
        if job:
            matched += 1
        db.add(DomoTxn(
            txn_date=_parse_date(r.get("date")),
            job_field=str(r.get("job"))[:80] if r.get("job") is not None else None,
            code_type=prefix[:1].upper() or None,
            code_prefix=prefix[:40],
            sku=(str(r.get("sku")).strip()[:40] if r.get("sku") else None),
            sales=_num(r.get("sales")),
            cost=_num(r.get("cost")),
            job_id=job.id if job else None,
            job_code=job.job_code if job else None,
            account_name=(job.account.name if job and job.account else None),
            community_name=(job.community.name if job and job.community else None),
            source_file=source,
        ))
        inserted += 1
    db.commit()
    return {"inserted": inserted, "matched": matched, "unmatched": inserted - matched}


def latest_txn_export(directory: Path) -> Path | None:
    files = [f for f in directory.glob("KB Job Txns*.json") if not f.name.startswith("~")]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def refresh_txns_from_file(db: Session) -> dict:
    directory = Path(get_settings().domo_export_dir)
    if not directory.is_dir():
        return {"error": f"folder not found: {directory}"}
    f = latest_txn_export(directory)
    if f is None:
        return {"error": "no 'KB Job Txns*.json' export found — run the Domo transaction pull first"}
    data = json.loads(f.read_text(encoding="utf-8"))
    rows = data.get("rows", data) if isinstance(data, dict) else data
    return {"file": f.name, **import_txns(db, rows, source=f.name)}


SNAPSHOT_SOURCE = "last Domo cost pull (install-dated)"


def build_txns_from_jobcosts(db: Session) -> dict:
    """Synthesize dated period data from the last Domo cost pull (the JobCost snapshot).

    No transaction-level Domo pull is required: each house's actual P&L is attributed
    to its install date (measure date as a fallback), so the period report can slice
    by quarter / YTD / year-over-year off data already in hand. Houses without a date
    are skipped and reported.
    """
    db.query(DomoTxn).delete()
    pairs = (
        db.query(Job, JobCost)
        .join(JobCost, JobCost.job_id == Job.id)
        .options(joinedload(Job.account), joinedload(Job.community))
        .all()
    )
    houses = skipped = 0
    for job, cost in pairs:
        d = job.install_date or job.measure_date
        if d is None:
            skipped += 1
            continue
        houses += 1
        base = dict(
            txn_date=d, job_id=job.id, job_code=job.job_code,
            account_name=job.account.name if job.account else None,
            community_name=job.community.name if job.community else None,
            source_file=SNAPSHOT_SOURCE,
        )
        # product side (G-code) — DRH jobs use the builder PO amount in lieu of Domo sales
        prod_rev, _ = drh_po_revenue(job, cost)
        db.add(DomoTxn(**base, code_type="G", code_prefix=job.g_code, sku="CAB",
                       sales=prod_rev, cost=cost.product_cost or 0))
        # C9009 install labor (I-code)
        db.add(DomoTxn(**base, code_type="I", code_prefix=job.i_code, sku=K_AND_B_LABOR_CODE,
                       sales=cost.labor_revenue or 0, cost=cost.labor_cost or 0))
        # net of the real non-C9009 cabinet labor (folded into margin)
        if cost.other_labor_net:
            db.add(DomoTxn(**base, code_type="I", code_prefix=job.i_code, sku="OTHERLBR",
                           sales=cost.other_labor_net, cost=0))
        # excluded overhead/rebill net (kept for transparency, out of margin)
        if cost.wash_labor_net:
            db.add(DomoTxn(**base, code_type="I", code_prefix=job.i_code, sku=WASH_CODE,
                           sales=cost.wash_labor_net, cost=0))
    db.commit()
    return {"source": SNAPSHOT_SOURCE, "houses": houses, "skipped_no_date": skipped}


def refresh_domo_txns(db: Session) -> dict:
    """The Domo P&L report's button: prefer a real dated transaction export if present,
    otherwise calculate period data from the last Domo cost pull (install-dated)."""
    directory = Path(get_settings().domo_export_dir)
    if directory.is_dir() and latest_txn_export(directory) is not None:
        return refresh_txns_from_file(db)
    return build_txns_from_jobcosts(db)


# --------------------------------------------------------------------------
# Date-range helpers
# --------------------------------------------------------------------------

def quarter_range(year: int, q: int) -> tuple[date, date]:
    start_month = (q - 1) * 3 + 1
    start = date(year, start_month, 1)
    end = date(year + 1, 1, 1) if q == 4 else date(year, start_month + 3, 1)
    return start, _prev_day(end)


def half_range(year: int, h: int) -> tuple[date, date]:
    return (date(year, 1, 1), date(year, 6, 30)) if h == 1 else (date(year, 7, 1), date(year, 12, 31))


def ytd_range(year: int, ref: date) -> tuple[date, date]:
    """Jan 1..year -> through the same month/day as the reference date (for YoY)."""
    try:
        end = date(year, ref.month, ref.day)
    except ValueError:  # Feb 29 on a non-leap year
        end = date(year, ref.month, 28)
    return date(year, 1, 1), end


def _prev_day(d: date) -> date:
    return date.fromordinal(d.toordinal() - 1)
