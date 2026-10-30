"""Our POs per job, straight from DOMO (Brian 10/29/26: "daily check DOMO for
any received or ordered items for each job and update the information").

DOMO's "O00059 - Purchases - Purchase Order Details" carries every PO line
with the job account it was bought for ("I7510029-304: DR HORTON PC ONLY - CAB
CESF 24"), its open/closed status, request date, and the receipt that closed
it. scripts/pull_domo_receipts.py writes it nightly, rolled up one row per PO,
as "DOMO Job POs MMDDYY.csv"; the uploader ships it to R2 domo-pos/.

Each PO is matched to a CabinetTron job by that account code against the job's
I-code / G-code (filled from DOMO's account list, app.job_accounts), else by
the account's name ("CAB CESF 24") against the tracker's Ashley's Code. Until
now a job only knew a PO if someone typed it into the tracker's PO Tracking
sheet; the job page and My Stuff now merge both (app.po_receipts).
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.job_accounts import ash_key, code_key
from app.models import DomoPo, Job, get_setting, set_setting

REPORT_KEY = "domo_pos_report"
FILE_GLOB = "DOMO Job POs*.csv"
COLS = ["PO #", "Order Date", "Due Date", "Status", "Close Date", "Vendor", "Product", "Job Account",
        "Sales Order #", "Ordered Cost", "Received Cost", "Last Receipt Date", "Last Receipt #",
        "Salesperson", "POS", "Lines"]
# Cabinet-job POs, one row per PO: any "- CAB ..." job account, plus any G/I job
# account buying kitchen cabinets / tops / cabinet hardware -- hand-named
# accounts ("CB PG 96", "DR Horton Montgomery - DRPREX-0116") were missed when
# this keyed on the name alone (Brian 10/30/26). Salespeople's Z accounts stay out.
PO_SQL = (
    "SELECT `transaction number`, MIN(`transaction date`), MAX(`request date`), MAX(`po status`), "
    "MAX(`po close date`), MAX(`supplier name title`), MAX(`sku description`), MAX(`job`), "
    "MAX(`sales order number`), SUM(`landed cost - ordered`), SUM(`landed cost - received`), "
    "MAX(`receipt date`), MAX(`receipt number`), MAX(`assigned salesperson`), MAX(`pos`), COUNT(*) "
    "FROM table WHERE `job` LIKE '%- CAB %' OR ((`job` LIKE 'G%' OR `job` LIKE 'I%') AND "
    "(`minor category` LIKE '2201%' OR `minor category` LIKE '2202%' OR `minor category` LIKE '2206%')) "
    "GROUP BY `transaction number`"
)

# "I7510029-304: DR HORTON PC ONLY - CAB CESF 24": the job name is whatever
# follows the LAST " - " ("... Montgomery - DRPREX-0116" keeps its hyphen).
_JOB = re.compile(
    r"^(?P<acct>[GI][0-9A-Z]+-[0-9A-Z]+):\s*(?:(?P<cust>.*)\s+-\s+(?P<name>.+?)|(?P<only>.*?))\s*$", re.I)


def _date(v) -> date | None:
    """DOMO hands back '2026-10-23', 20261023 (receipt date) or ''."""
    s = str(v or "").strip()
    if not s:
        return None
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", s)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def _num(v) -> float | None:
    try:
        return round(float(str(v).replace(",", "")), 2)
    except (TypeError, ValueError):
        return None


def _strip_code(v) -> str | None:
    """'70408: EVERYTHING BUILDING PRODUCTS LLC' -> 'EVERYTHING BUILDING PRODUCTS LLC'."""
    s = str(v or "").strip()
    return (s.split(":", 1)[1].strip() if re.match(r"^[A-Za-z]?\d+:", s) else s) or None


def newest_file(folder: Path) -> Path | None:
    files = sorted(folder.glob(FILE_GLOB), key=lambda f: f.stat().st_mtime, reverse=True) if folder.is_dir() else []
    return files[0] if files else None


def load_rows(path: Path) -> list[dict]:
    out = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            po = str(r.get("PO #") or "").strip()
            if not po:
                continue
            m = _JOB.match(str(r.get("Job Account") or "").strip())
            receipt = str(r.get("Last Receipt #") or "").strip()
            out.append({
                "our_po": po,
                "job_account": m["acct"].upper() if m else None,
                "customer": (m["cust"] or m["only"] or "").strip()[:200] or None if m else None,
                "job_name": " ".join((m["name"] or "").split())[:120] or None if m else None,
                "vendor": (_strip_code(r.get("Vendor")) or "")[:160] or None,
                "product": (str(r.get("Product") or "").strip()[:200]) or None,
                "order_date": _date(r.get("Order Date")),
                "due_date": _date(r.get("Due Date")),
                "status": (str(r.get("Status") or "").strip()[:20]) or None,
                "close_date": _date(r.get("Close Date")),
                "ordered_cost": _num(r.get("Ordered Cost")),
                "received_cost": _num(r.get("Received Cost")),
                "last_receipt_date": _date(r.get("Last Receipt Date")),
                "last_receipt_number": receipt[:40] if receipt and receipt != "0" else None,
                "sales_order": (str(r.get("Sales Order #") or "").strip()[:40]) or None,
                "salesperson": (_strip_code(r.get("Salesperson")) or "")[:120] or None,
                "pos": (str(r.get("POS") or "").strip()[:80]) or None,
                "lines": int(_num(r.get("Lines")) or 0) or None,
            })
    return out


def _ash_index() -> dict[str, set[str]]:
    """Tracker Ashley's Code -> job codes, for jobs whose I/G code is still blank."""
    try:
        from app.job_accounts import _tracker_index

        _rows, _by_code, by_ash, _name = _tracker_index()
        return by_ash
    except Exception:  # noqa: BLE001 -- the code match still works without it
        return {}


def apply(db: Session, path: Path | None = None) -> dict:
    path = path or newest_file(Path(get_settings().domo_pos_folder))
    if path is None:
        return {"error": "no DOMO Job POs file"}
    rows = load_rows(path)
    jobs = db.query(Job).all()
    by_code: dict[str, Job] = {}
    for j in jobs:
        for c in (j.i_code, j.g_code):
            if c and c.strip():
                by_code.setdefault(code_key(c), j)
    by_job_code = {j.job_code: j for j in jobs if j.job_code}
    by_ash = None

    db.query(DomoPo).delete()
    matched, unmatched, how = 0, [], {"code": 0, "ashley": 0}
    for r in rows:
        job = by_code.get(code_key(r["job_account"])) if r["job_account"] else None
        if job is not None:
            how["code"] += 1
        elif r["job_name"] and r["job_name"].upper() in by_job_code:
            # hand-named accounts often carry the job code itself ("... - DRPREX-0116")
            job = by_job_code[r["job_name"].upper()]
            how["job_code"] = how.get("job_code", 0) + 1
        elif r["job_name"]:
            by_ash = _ash_index() if by_ash is None else by_ash
            codes = by_ash.get(ash_key(r["job_name"]), set())
            if len(codes) == 1:
                job = by_job_code.get(next(iter(codes)))
                if job is not None:
                    how["ashley"] += 1
        if job is not None:
            matched += 1
        else:
            unmatched.append({k: r[k] for k in ("our_po", "job_account", "job_name", "customer", "status")}
                             | {"order_date": r["order_date"]})
        db.add(DomoPo(job_id=job.id if job else None, **r))

    summary = {
        "at": datetime.now().isoformat(timespec="seconds"), "file": path.name, "pos": len(rows),
        "matched": matched, "matched_by": how, "unmatched": len(unmatched),
        "open": sum(1 for r in rows if (r["status"] or "").lower() == "open"),
    }
    unmatched.sort(key=lambda u: u["order_date"] or date.min, reverse=True)
    set_setting(db, REPORT_KEY, json.dumps({**summary, "unmatched_list": unmatched[:200]}, default=str))
    db.commit()
    return summary


def last_report(db: Session) -> dict | None:
    raw = get_setting(db, REPORT_KEY)
    return json.loads(raw) if raw else None
