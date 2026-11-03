"""Installed but not final billed (Brian 11/3/26).

A house's dollars sit on its I-code while it's active; the final bill puts
them on its G-code. Brian chose DOMO sales on the G-code as the "final billed"
signal, and the tracker's Actual Install Date (today or earlier) as "installed".

scripts/pull_domo_receipts.py writes "DOMO Job Billing MMDDYY.csv" each night:
K&B sales (product category Kitchen and Bath, or C90xx install labor) summed
per G/I job account from DOMO's Sales Details dataset. The uploader ships it
to R2 domo-billing/.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.job_accounts import code_key
from app.models import Job, JobStatus

FILE_GLOB = "DOMO Job Billing*.csv"
COLS = ["Job Account", "Sales", "Lines"]
# Same K&B scope as app.domo's cost pull: installed-sales accounts are
# whole-house, so product is limited to Kitchen and Bath plus the C90xx labor.
BILLING_SQL = (
    "SELECT SUBSTRING_INDEX(`job`,':',1), SUM(`sales`), COUNT(*) FROM table "
    "WHERE (`job` LIKE 'G%' OR `job` LIKE 'I%') "
    "AND (`product category` = 'Kitchen and Bath' OR `sku` LIKE 'C90%') "
    "GROUP BY SUBSTRING_INDEX(`job`,':',1)"
)

_CACHE: dict[str, object] = {"key": None, "sales": {}, "name": None}


def newest_file(folder: Path) -> Path | None:
    files = sorted(folder.glob(FILE_GLOB), key=lambda f: f.stat().st_mtime, reverse=True) if folder.is_dir() else []
    return files[0] if files else None


def load_sales() -> tuple[dict[str, float], str | None]:
    """code_key(account) -> K&B sales, from the newest billing file (cached on
    the file's identity, like the tracker)."""
    f = newest_file(Path(get_settings().domo_billing_folder))
    if f is None:
        return {}, None
    stat = f.stat()
    key = f"{f.name}|{stat.st_size}|{int(stat.st_mtime)}"
    if _CACHE["key"] != key:
        sales: dict[str, float] = {}
        with f.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                acct = code_key(row.get("Job Account"))
                try:
                    amt = float(str(row.get("Sales") or 0).replace(",", "").replace("$", ""))
                except ValueError:
                    continue
                if acct:
                    sales[acct] = sales.get(acct, 0.0) + amt
        _CACHE.update(key=key, sales=sales, name=f.name)
    return _CACHE["sales"], _CACHE["name"]  # type: ignore[return-value]


def _code(v) -> str | None:
    s = str(v or "").strip().upper()
    return None if s in ("", "NA", "N/A", "0", "NONE") else s


def build_report(db: Session, today: date | None = None, until: date | None = None) -> dict:
    """Every house with a tracker Actual Install Date on or before today whose
    G-code shows no K&B sales in DOMO -- oldest install first. `until` narrows
    it to houses installed on or before that date."""
    from app.smartsheet.api import _tracker_rows
    from scripts.import_tracker import as_date

    today = today or date.today()
    rows, ok, tracker_name = _tracker_rows()
    sales, billing_name = load_sales()
    jobs = {
        j.job_code: j
        for j in db.query(Job).options(joinedload(Job.account), joinedload(Job.community))
        .filter(Job.job_code.isnot(None)).all()
    }

    out, installed = [], 0
    for r in rows:
        code = str(r.get("Job Code") or "").strip()
        actual = as_date(r.get("Actual Install Date"))
        if not code or actual is None or actual > min(today, until or today):
            continue
        job = jobs.get(code)
        if job is not None and job.status == JobStatus.void:
            continue
        installed += 1
        g = _code(job.g_code if job and job.g_code else r.get("G-Code"))
        i = _code(job.i_code if job and job.i_code else r.get("I-Code"))
        g_sales = sales.get(code_key(g), 0.0) if g else 0.0
        if g and g_sales > 0:
            continue
        out.append({
            "job_id": job.id if job else None,
            "job_code": code,
            "account_name": job.account.name if job and job.account else (r.get("Builder") or None),
            "community_name": job.community.name if job and job.community else (r.get("Community") or None),
            "lot_number": job.lot_number if job else (str(r.get("Lot #") or "") or None),
            "address": job.address if job else (r.get("Address") or None),
            "actual_install": actual,
            "days_since_install": (today - actual).days,
            "status": job.status.value if job else (r.get("CONST LVL") or None),
            "salesperson": (job.salesperson if job else None) or (r.get("Salesperson") or None),
            "g_code": g,
            "i_code": i,
            "i_sales": round(sales.get(code_key(i), 0.0), 2) if i else None,
            "reason": "no G-code on file" if not g else "no sales on the G-code",
        })
    out.sort(key=lambda x: (x["actual_install"], x["job_code"]))
    return {
        "rows": out,
        "installed": installed,
        "tracker_file": tracker_name,
        "tracker_ok": ok,
        "billing_file": billing_name,
    }


EXPORT_COLUMNS = [
    ("Installed", "actual_install", 11), ("Days", "days_since_install", 7), ("Job Code", "job_code", 15),
    ("Builder", "account_name", 26), ("Community", "community_name", 22), ("Lot", "lot_number", 7),
    ("Address", "address", 30), ("Status", "status", 12), ("Salesperson", "salesperson", 16),
    ("G-Code", "g_code", 15), ("I-Code", "i_code", 15), ("Billed on I-Code", "i_sales", 15),
    ("Why", "reason", 22),
]


def report_xlsx(db: Session, until: date | None = None) -> tuple[bytes, int]:
    """The same list as an Excel sheet (Brian 11/3/26) -- header row frozen and
    filterable, dates m/d/yy, dollars $#,##0.00. Returns (bytes, rows)."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    data = build_report(db, until=until)
    wb = Workbook()
    ws = wb.active
    ws.title = "Not Final Billed"
    ws.append([h for h, _, _ in EXPORT_COLUMNS])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0E2133")
        c.alignment = Alignment(horizontal="center")
    for r in data["rows"]:
        ws.append([r[k] for _, k, _ in EXPORT_COLUMNS])
    for row in ws.iter_rows(min_row=2):
        row[0].number_format = "m/d/yy"
        row[11].number_format = "$#,##0.00"
        for c in (row[0], row[1], row[5]):
            c.alignment = Alignment(horizontal="center")
    for i, (_, _, width) in enumerate(EXPORT_COLUMNS):
        ws.column_dimensions[chr(65 + i)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), len(data["rows"])
