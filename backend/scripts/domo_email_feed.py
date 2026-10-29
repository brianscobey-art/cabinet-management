"""Turn DOMO's emailed report CSVs into the files CabinetTron already reads.

WHY THIS EXISTS (Brian 10/29/26). The direct pull (pull_domo_receipts.py)
needs a live DOMO session, and DOMO idles sessions out. So DOMO also emails
Brian three card reports every morning at 5:00 AM CT ("CabinetTron feed - ..."
subjects, scheduled under his own login; DOMO caps a schedule at 3 months, so
they expire 1/29/27 and must be renewed). A Power Automate flow saves each
attachment into AI Utilities\\domo-email-feed. This script, run by Task Scheduler
through the morning, converts them into Downloads under the exact names and
columns the uploader / cloud importers expect:

    PO Receipt List.csv                         -> PO Receipt List MMDDYY.csv
    Job Account.csv                             -> DOMO CAB Accounts MMDDYY.csv
    ALL Purchase Orders by Customer and ...csv  -> DOMO Job POs MMDDYY.csv

The direct pull is richer (PO status, due date, SO #, receipt per PO, I->G
links), so a target it already wrote today is left alone; the email copy only
fills the gap on the mornings the session was dead.

Exit codes: 0 ok (wrote or nothing to do), 1 error.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import get_settings  # noqa: E402
from app.domo_pos import COLS as PO_COLS  # noqa: E402
from app.job_accounts import COLS as ACCT_COLS  # noqa: E402
from app.po_receipts import COLS as RECEIPT_COLS  # noqa: E402

INBOX = BACKEND.parents[1] / "domo-email-feed"
STATUS = BACKEND.parents[1] / "ai-health" / "domo_email_feed.json"


def _newest(pattern: str) -> Path | None:
    files = [f for f in INBOX.glob(pattern) if f.suffix.lower() == ".csv"]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]


def _pick(row: dict, *names: str) -> str:
    """First header that exists, case/space-insensitive (card aliases drift)."""
    low = {re.sub(r"\s+", " ", k).lower(): v for k, v in row.items()}
    for n in names:
        v = low.get(n.lower())
        if v is not None:
            return v
    return ""


def _num(v: str) -> float:
    try:
        return float(str(v).replace(",", "").replace("$", "") or 0)
    except ValueError:
        return 0.0


def _write(out: Path, header: list[str], rows: list[list]) -> None:
    tmp = out.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    tmp.replace(out)


def receipts(src: Path) -> list[list]:
    return [[_pick(r, c) for c in RECEIPT_COLS] for r in _read(src) if _pick(r, "Receipt #")]


def accounts(src: Path) -> list[list]:
    """The Job Account card is one column ("I7550042-238: DR HORTON ... - CAB GL
    34A"); app.job_accounts pairs I with G by name when Linked G is blank."""
    out = []
    for r in _read(src):
        job = _pick(r, "Job", "Job Account")
        if "- CAB " in job.upper():
            out.append([job, "", "", "", ""])
    return out


def job_pos(src: Path) -> list[list]:
    """ALL Purchase Orders (one row per PO, every store) -> cabinet-job POs.
    No status column on the card: 95% received means closed -- receipts land a
    little under the order (1907 against 1908.63), and special orders carry a
    $1 ordered placeholder, so any real receipt closes those."""
    out = []
    for r in _read(src):
        job = _pick(r, "Customer : Job", "Customer: Job", "Job")
        po = _pick(r, "Order Number", "Transaction Number", "PO #")
        if not po or "- CAB " not in job.upper():
            continue
        ordered, received = _num(_pick(r, "Landed Cost")), _num(_pick(r, "Received Cost"))
        closed = received > 0 and received >= ordered * 0.95
        row = dict.fromkeys(PO_COLS, "")
        row.update({"PO #": po, "Order Date": _pick(r, "Transaction Date")[:10],
                    "Status": "Closed" if closed else "Open", "Vendor": _pick(r, "Supplier"),
                    "Job Account": job, "Ordered Cost": ordered, "Received Cost": received,
                    "Salesperson": _pick(r, "Assigned Salesperson")})
        out.append([row[c] for c in PO_COLS])
    return out


def main() -> int:
    stamp = f"{dt.date.today():%m%d%y}"
    dest = Path(get_settings().po_receipt_dir)
    jobs = [
        ("PO Receipt List*.csv", f"PO Receipt List {stamp}.csv", RECEIPT_COLS, receipts),
        ("Job Account*.csv", f"DOMO CAB Accounts {stamp}.csv", ACCT_COLS, accounts),
        ("ALL Purchase Orders*.csv", f"DOMO Job POs {stamp}.csv", PO_COLS, job_pos),
    ]
    today = dt.date.today()
    result = {}
    for pattern, name, header, convert in jobs:
        src, out = _newest(pattern), dest / name
        if src is None or dt.date.fromtimestamp(src.stat().st_mtime) != today:
            result[name] = "no email attachment from today"
        elif out.exists() and out.stat().st_mtime > src.stat().st_mtime - 6 * 3600:
            result[name] = "direct pull already wrote it today - kept"
        else:
            rows = convert(src)
            _write(out, header, rows)
            result[name] = f"{len(rows)} rows from {src.name}"
    print(json.dumps(result, indent=2))
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), **result}, indent=2),
                      encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 -- the status file is how failures get seen
        print(f"error: {exc}")
        sys.exit(1)
