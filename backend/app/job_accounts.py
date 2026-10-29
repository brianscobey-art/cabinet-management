"""G-code / I-code fill from DOMO's job-account list (Brian 10/28/26).

Every cabinet job gets a pair of Carter POS job accounts: G (goods) and I
(install). Until now CabinetTron only had them when someone typed them in.
DOMO's "O00010 - Sales - Customer Detail" lists every job account the day it
is set up -- before any sale posts -- and the I-account row names its G-account
("job account - final bill"), so the pair comes linked. Brian chose DOMO over
his setup-request emails as the source.

scripts/pull_domo_receipts.py writes "DOMO CAB Accounts MMDDYY.csv" beside the
receipt CSV each night; the uploader ships it to R2 domo-accounts/.

Matching: a pair -> the tracker's Job Code, by the tracker's own G-Code /
I-Code first, else by Ashley's Code (the account's "CAB GL 34A" name) -> the
CabinetTron job with that code. Rules Brian set:
  * fill a blank g_code / i_code; never overwrite one that disagrees -- list it
  * accounts with no tracker job are listed for review, nothing is created
The last run's lists are kept in app_settings for the Job Accounts report.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Job, get_setting, set_setting

REPORT_KEY = "job_accounts_report"
FILE_GLOB = "DOMO CAB Accounts*.csv"
COLS = ["Job Account", "Created", "Credit Limit", "Linked G", "Status"]
# One row per job account; the dataset is per customer x sales slice, hence GROUP BY.
ACCOUNTS_SQL = (
    "SELECT `job`, MIN(`job since`), MAX(`job credit limit`), MAX(`job account - final bill`), "
    "MAX(`customer status`) FROM table WHERE `job` LIKE '%- CAB %' GROUP BY `job`"
)

# "I7550042-238: DR HORTON CRESTVIEW - CAB GL 34A"
_JOB = re.compile(r"^(?P<acct>[GI][0-9A-Z]+-[0-9A-Z]+):\s*(?P<cust>.*?)\s+-\s+(?P<name>CAB\b.*)$", re.I)


def ash_key(name: str | None) -> str:
    """'CAB GL 34A' / 'CAB GL34A' / 'cab gl 034a' -> 'CABGL34A'. Spacing and
    zero-padding drift between DOMO and the tracker; the letters never do."""
    s = re.sub(r"\s+", "", str(name or "").upper())
    return re.sub(r"\d+", lambda m: str(int(m.group())), s)


def code_key(code: str | None) -> str:
    """'G7500042-0120' and 'G7500042-120' are one account -- the tracker pads
    some suffixes, DOMO never does. Alphanumeric suffixes (A47) are untouched
    apart from the leading zeros."""
    # Hand-typed codes use a space for the dash ("G7510100 012", JCMA0002).
    s = re.sub(r"[\s_-]+", "-", str(code or "").strip().upper())
    if "-" not in s:
        return s
    head, tail = s.split("-", 1)
    return f"{head}-{tail.lstrip('0') or '0'}"


def newest_file(folder: Path) -> Path | None:
    files = sorted(folder.glob(FILE_GLOB), key=lambda f: f.stat().st_mtime, reverse=True) if folder.is_dir() else []
    return files[0] if files else None


def load_pairs(path: Path) -> list[dict]:
    """One dict per G/I pair: {name, customer, g, i, created, limit}. A G with
    no I (or the reverse) still makes a pair with the other side blank."""
    accts = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            m = _JOB.match(str(row.get("Job Account") or "").strip())
            if not m:
                continue
            accts[m["acct"].upper()] = {
                "acct": m["acct"].upper(), "customer": m["cust"].strip(), "name": " ".join(m["name"].split()),
                "created": (row.get("Created") or "")[:10], "limit": row.get("Credit Limit") or "",
                "linked_g": (row.get("Linked G") or "").strip().upper(),
            }
    # The emailed "Job Account" card (scripts/domo_email_feed.py) has no Linked
    # G column -- pair an I with the one G account carrying the same name.
    g_by_name: dict[tuple, list[str]] = defaultdict(list)
    for a in accts.values():
        if a["acct"].startswith("G"):
            g_by_name[(a["customer"].upper(), a["name"].upper())].append(a["acct"])
    pairs, used_g = [], set()
    for a in accts.values():
        if a["acct"].startswith("I"):
            g = a["linked_g"] if a["linked_g"] in accts else None
            if g is None and not a["linked_g"]:
                same = g_by_name.get((a["customer"].upper(), a["name"].upper()), [])
                g = same[0] if len(same) == 1 else None
            if g:
                used_g.add(g)
            pairs.append({"name": a["name"], "customer": a["customer"], "g": g or a["linked_g"] or None,
                          "i": a["acct"], "created": a["created"], "limit": a["limit"]})
    for a in accts.values():
        if a["acct"].startswith("G") and a["acct"] not in used_g:
            pairs.append({"name": a["name"], "customer": a["customer"], "g": a["acct"], "i": None,
                          "created": a["created"], "limit": a["limit"]})
    return pairs


def _tracker_index():
    from app.smartsheet.api import _tracker_rows

    rows, ok, name = _tracker_rows()
    by_code, by_ash = {}, defaultdict(set)
    for r in rows:
        code = str(r.get("Job Code") or "").strip()
        if not code:
            continue
        for key in ("G-Code", "I-Code"):
            v = str(r.get(key) or "").strip().upper()
            if v and v not in ("NA", "0", "NONE"):
                by_code[code_key(v)] = code
        a = ash_key(r.get("Ashley's  Code") or r.get("Ashley's Code"))
        if a and a not in ("NA", "0"):
            by_ash[a].add(code)
    return rows, by_code, by_ash, name


def apply(db: Session, path: Path | None = None) -> dict:
    s = get_settings()
    path = path or newest_file(Path(s.domo_accounts_folder))
    if path is None:
        return {"error": "no DOMO CAB Accounts file"}
    pairs = load_pairs(path)
    trk_rows, by_code, by_ash, trk_name = _tracker_index()
    if not trk_rows:
        return {"error": "tracker unreadable -- nothing matched", "file": path.name}
    jobs = {j.job_code: j for j in db.query(Job).filter(Job.job_code.isnot(None)).all()}
    trk_codes = {str(r.get("Job Code") or "").strip(): r for r in trk_rows}

    filled, conflicts, unmatched, ambiguous, not_in_ct, tracker_differs = [], [], [], [], [], []
    already = 0
    for p in pairs:
        codes = {by_code[code_key(c)] for c in (p["g"], p["i"]) if c and code_key(c) in by_code}
        how = "tracker G/I"
        if not codes:
            codes = set(by_ash.get(ash_key(p["name"]), ()))
            how = "Ashley's Code"
        row = {k: p[k] for k in ("name", "customer", "g", "i", "created")}
        if not codes:
            unmatched.append(row)
            continue
        if len(codes) > 1:
            ambiguous.append({**row, "job_codes": sorted(codes)})
            continue
        code = codes.pop()
        t = trk_codes.get(code, {})
        for side, key in (("g", "G-Code"), ("i", "I-Code")):
            tv = str(t.get(key) or "").strip().upper()
            if p[side] and tv and tv not in ("NA", "0", "NONE") and code_key(tv) != code_key(p[side]):
                tracker_differs.append({**row, "job_code": code, "field": key, "tracker": tv, "domo": p[side]})
        job = jobs.get(code)
        if job is None:
            not_in_ct.append({**row, "job_code": code})
            continue
        changed = []
        for side, attr in (("g", "g_code"), ("i", "i_code")):
            new = p[side]
            if not new:
                continue
            cur = (getattr(job, attr) or "").strip().upper()
            if not cur:
                setattr(job, attr, new)
                changed.append(attr)
            elif code_key(cur) != code_key(new):
                conflicts.append({**row, "job_code": code, "field": attr, "cabinettron": cur, "domo": new})
        if changed:
            filled.append({**row, "job_code": code, "fields": changed, "matched_by": how})
        else:
            already += 1

    summary = {
        "at": datetime.now().isoformat(timespec="seconds"), "file": path.name, "tracker": trk_name,
        "accounts": len(pairs), "filled": len(filled), "already_set": already,
        "conflicts": len(conflicts), "unmatched": len(unmatched), "ambiguous": len(ambiguous),
        "not_in_cabinettron": len(not_in_ct), "tracker_differs": len(tracker_differs),
    }
    set_setting(db, REPORT_KEY, json.dumps({
        **summary, "lists": {
            "filled": filled, "conflicts": conflicts, "unmatched": unmatched, "ambiguous": ambiguous,
            "not_in_cabinettron": not_in_ct, "tracker_differs": tracker_differs,
        },
    }, default=str))
    db.commit()
    return summary


def last_report(db: Session) -> dict | None:
    raw = get_setting(db, REPORT_KEY)
    return json.loads(raw) if raw else None
