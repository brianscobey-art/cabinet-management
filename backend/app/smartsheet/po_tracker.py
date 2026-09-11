"""Push the tracker's POTracker table into a Smartsheet, one job per parent row.

What POTracker actually is (reviewed 9/11/26). Twenty-six columns on the
"PO Tracking" sheet: twelve TYPED by Brian per PO line (job code, product,
vendor, colour, factory order #, our PO #, sales order #, cost, and the order /
ship / tentative-due / actual-receipt dates); ten that are XLOOKUP into the
DATA table on Job Code (I-Code, G-Code, Ashley Code, install date, plan,
address, community, BUID, CONST LVL, install week); Cycle Time, which is
receipt minus order; and three that XLOOKUP on Our PO # into a DOMO receipt
list pasted beside the table (receipt date, supplier, landed cost).

This module does the same joins in Python. The DATA lookups are re-resolved
here rather than read as cached values, because data_only reads whatever Excel
last calculated -- stale if the workbook has not been opened since the DATA
row changed. The receipt lookups come from CabinetTron's own po_receipts, which
the DOMO pipeline refreshes, with the typed Actual Receipt Date as fallback.

The sheet is HIERARCHICAL: a parent row per job carrying the job-level fields,
and a child row per PO line beneath it. Brian's requirement was to see every
PO for a job together -- a job can carry ten -- and indenting under the job is
what Smartsheet's hierarchy is for. Filters and reports still see child rows
flat, so nothing is lost by grouping.

Writes to exactly one sheet, the one it creates. Never the Masters.
"""

from __future__ import annotations

import datetime as dt
import re
import warnings
from collections import defaultdict
from pathlib import Path

import httpx

from app.smartsheet.job_tracker import EMPTY_TEXT, _client

# --- the sheet ------------------------------------------------------------
# (column title, Smartsheet type). "Item" is primary: the job code on a parent
# row, "PO <n> · <product>" on a child. Job Code is ALSO its own column on every
# row so a flat filter or report by job works without the hierarchy.
COLUMNS: list[tuple[str, str]] = [
    ("Item", "TEXT_NUMBER"),
    ("Job Code", "TEXT_NUMBER"),
    ("Line", "TEXT_NUMBER"),
    ("Our PO #", "TEXT_NUMBER"),
    ("Product", "TEXT_NUMBER"),
    ("Vendor", "TEXT_NUMBER"),
    ("Color", "TEXT_NUMBER"),
    ("Factory Order #", "TEXT_NUMBER"),
    ("Sales Order #", "TEXT_NUMBER"),
    ("Cost", "MONEY"),
    ("Order Date", "DATE"),
    ("Ship Date", "DATE"),
    ("Tent Due Date", "DATE"),
    # What Brian typed when the truck came.
    ("Actual Receipt Date", "DATE"),
    # What DOMO says. "Received?" is yes only when the PO Receipt List carries
    # this PO's order number -- never inferred from the typed date, because the
    # point of the column is to show what the store's system knows.
    ("Received?", "TEXT_NUMBER"),
    ("Receipt #", "TEXT_NUMBER"),
    ("Receipt Date", "DATE"),
    ("Cycle Days", "TEXT_NUMBER"),
    ("Supplier", "TEXT_NUMBER"),
    ("Landed Cost", "MONEY"),
    ("Duplicate?", "TEXT_NUMBER"),
    # job-level, from DATA by Job Code -- on the parent row
    ("BUID", "TEXT_NUMBER"),
    ("Community", "TEXT_NUMBER"),
    ("Address", "TEXT_NUMBER"),
    ("Plan", "TEXT_NUMBER"),
    ("CONST LVL", "TEXT_NUMBER"),
    ("Install Date", "DATE"),
    ("Install Week", "TEXT_NUMBER"),
    ("I-Code", "TEXT_NUMBER"),
    ("G-Code", "TEXT_NUMBER"),
    ("Ashley's Code", "TEXT_NUMBER"),
    ("Updated", "DATE"),
]
PRIMARY = "Item"
MONEY_COLUMNS = {"Cost", "Landed Cost"}
CENTERED = {
    "Job Code", "Line", "Our PO #", "Factory Order #", "Sales Order #", "Cost",
    "Order Date", "Ship Date", "Tent Due Date", "Actual Receipt Date",
    "Received?", "Receipt #", "Receipt Date", "Cycle Days",
    "Landed Cost", "Duplicate?", "BUID", "CONST LVL", "Install Date",
    "Install Week", "I-Code", "G-Code", "Ashley's Code", "Updated",
}

# Same descriptor indexes job_tracker confirmed against the live API.
_F_HALIGN, _F_CURRENCY, _F_DECIMALS, _F_THOUSANDS, _F_NUMFMT = 6, 11, 12, 13, 14

# POTracker typed columns -> our titles. Header text as it appears in the
# sheet (some carry a doubled space, which is why they are matched by name
# list rather than typed by hand elsewhere).
TYPED = {
    "Job Code": ("Job Code",),
    "Product": ("Product",),
    "Vendor": ("Vendor",),
    "Color": ("Color",),
    "Factory Order #": ("Factory Order Number",),
    "Our PO #": ("Our PO #",),
    "Sales Order #": ("Our Sales  Order #", "Our Sales Order #"),
    "Cost": ("Cost",),
    "Order Date": ("Order  Date", "Order Date"),
    "Ship Date": ("Ship  Date", "Ship Date"),
    "Tent Due Date": ("Tent Due Date",),
    "Actual Receipt Date": ("Actual Receipt Date",),
}
# The ten XLOOKUPs, re-resolved: our title -> DATA column.
LOOKUPS = {
    "I-Code": "I-Code",
    "G-Code": "G-Code",
    "Ashley's Code": "Ashley's  Code",
    "Install Date": "Actual Install Date",
    "Plan": "House Plan",
    "Address": "Address",
    "Community": "Community",
    "BUID": "Builder Job Code",
    "CONST LVL": "CONST LVL",
    "Install Week": "Install Week",
}


def _clean(raw, kind: str):
    """Mirror of job_tracker._clean, plus the quirks this table produces.

    An XLOOKUP with a default of 0 renders a missing date as 00:00:00 and a
    missing code as 0; the workbook shows those as values and they are not.
    """
    if raw is None:
        return None
    if kind == "DATE":
        if isinstance(raw, dt.datetime):
            return raw.date().isoformat()
        if isinstance(raw, dt.date):
            return raw.isoformat()
        text = str(raw).strip()
        if len(text) >= 10 and text[4:5] == "-":
            try:
                return dt.datetime.fromisoformat(text[:19]).date().isoformat()
            except ValueError:
                return None
        return None
    text = str(raw).strip()
    if text.lower() in EMPTY_TEXT:
        return None
    if text.endswith(".0") and text[:-2].replace("-", "").isdigit():
        text = text[:-2]
    if kind == "MONEY":
        try:
            return round(float(text.replace("$", "").replace(",", "")), 2)
        except ValueError:
            return None
    return text


def _find_header(ws):
    """POTracker's header is the row containing 'Our PO #'; nothing above it
    is data. Only the first 26 columns are the table -- what sits to the right
    is the pasted DOMO receipt list the workbook's own lookups read."""
    for row in ws.iter_rows(max_col=26, values_only=True):
        cells = [str(c).replace("\n", " ").strip() if c else "" for c in row]
        if "Our PO #" in cells:
            return cells
    return None


def read_potracker(path: Path) -> list[dict]:
    """Every POTracker line with a PO number, typed columns only."""
    from openpyxl import load_workbook

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = load_workbook(path, data_only=True, read_only=True)
    try:
        if "PO Tracking" not in wb.sheetnames:
            return []
        ws = wb["PO Tracking"]
        hdr = _find_header(ws)
        if hdr is None:
            return []
        idx = {}
        for title, names in TYPED.items():
            for name in names:
                if name in hdr:
                    idx[title] = hdr.index(name)
                    break
        out = []
        seen_header = False
        for row in ws.iter_rows(max_col=26, values_only=True):
            if not seen_header:
                cells = [str(c).replace("\n", " ").strip() if c else "" for c in row]
                if "Our PO #" in cells:
                    seen_header = True
                continue
            po = row[idx["Our PO #"]] if "Our PO #" in idx else None
            if po in (None, ""):
                continue
            rec = {}
            for title, i in idx.items():
                kind = ("DATE" if "Date" in title else "MONEY" if title == "Cost"
                        else "TEXT")
                rec[title] = _clean(row[i], kind) if i < len(row) else None
            if rec.get("Our PO #") is None:
                continue
            out.append(rec)
        return out
    finally:
        wb.close()


def resolve(lines: list[dict], data_rows: list[dict], receipts: dict[str, dict],
            *, today: dt.date | None = None) -> list[dict]:
    """Add the job-level lookups, the receipt fields and cycle time.

    XLOOKUP returns the FIRST match, so a duplicated Job Code in DATA resolves
    to its first row here too -- same answer the workbook gives.
    """
    by_job: dict[str, dict] = {}
    for r in data_rows:
        code = _clean(r.get("Job Code"), "TEXT")
        if code and code not in by_job:
            by_job[code] = r

    stamp = (today or dt.date.today()).isoformat()
    for rec in lines:
        job = by_job.get(rec.get("Job Code") or "", {})
        for title, col in LOOKUPS.items():
            kind = "DATE" if title == "Install Date" else "TEXT"
            rec[title] = _clean(job.get(col), kind)
        rcpt = receipts.get(str(rec["Our PO #"]))
        rec["Received?"] = "yes" if rcpt else "no"
        rec["Receipt #"] = (rcpt or {}).get("receipt_number")
        rec["Receipt Date"] = (rcpt or {}).get("receipt_date")
        rec["Supplier"] = (rcpt or {}).get("supplier")
        rec["Landed Cost"] = (rcpt or {}).get("landed_cost")
        # Cycle time prefers the store's receipt; the typed date stands in only
        # when DOMO has nothing, and that is the workbook's own rule.
        od = rec.get("Order Date")
        rd = rec.get("Receipt Date") or rec.get("Actual Receipt Date")
        rec["Cycle Days"] = (
            (dt.date.fromisoformat(rd) - dt.date.fromisoformat(od)).days
            if od and rd else None)
        rec["Updated"] = stamp
    return lines


def shape(lines: list[dict]) -> list[dict]:
    """Parent per job, children per PO line, in push order.

    Each record carries `key` (stable identity across pushes) and, for a child,
    `parent_key`. A duplicate PO line keeps its own row -- Brian wants every
    line visible -- numbered by occurrence and flagged, so cleaning it in the
    tracker makes it drop off on the next push.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in lines:
        groups[rec.get("Job Code") or "(no job code)"].append(rec)

    out = []
    for job, its in sorted(groups.items()):
        first = its[0]
        parent = {
            "key": f"JOB:{job}", "parent_key": None,
            "Item": job, "Job Code": job,
            "Line": f"{len(its)} PO{'s' if len(its) != 1 else ''}",
            "Updated": first.get("Updated"),
        }
        for title in LOOKUPS:
            parent[title] = first.get(title)
        out.append(parent)

        seen: dict[str, int] = {}
        pairs = defaultdict(int)
        for rec in its:
            sig = f"{rec.get('Our PO #')}|{rec.get('Product')}"
            pairs[sig] += 1
        for n, rec in enumerate(its, start=1):
            sig = f"{rec.get('Our PO #')}|{rec.get('Product')}"
            seen[sig] = seen.get(sig, 0) + 1
            child = {
                "key": f"PO:{job}|{sig}|{seen[sig]}", "parent_key": f"JOB:{job}",
                "Item": f"PO {rec.get('Our PO #')} · {rec.get('Product') or ''}".strip(),
                "Job Code": job, "Line": str(n),
                "Duplicate?": "yes" if pairs[sig] > 1 else None,
            }
            for title, _ in COLUMNS:
                if title in child or title in LOOKUPS:
                    continue
                child[title] = rec.get(title)
            out.append(child)
    return out


# --- Smartsheet -----------------------------------------------------------
def _api_type(kind: str) -> str:
    return "DATE" if kind == "DATE" else "TEXT_NUMBER"


def create_sheet(token: str, name: str, workspace_id: int) -> dict:
    body = {"name": name, "columns": [
        {"title": t, "type": _api_type(k), **({"primary": True} if t == PRIMARY else {})}
        for t, k in COLUMNS]}
    with _client(token) as c:
        r = c.post(f"/workspaces/{workspace_id}/sheets", json=body)
        r.raise_for_status()
        return r.json()["result"]


def _column_format(title: str) -> str | None:
    f = [""] * 16
    if title in CENTERED:
        f[_F_HALIGN] = "2"
    if title in MONEY_COLUMNS:
        f[_F_CURRENCY], f[_F_DECIMALS], f[_F_THOUSANDS], f[_F_NUMFMT] = "13", "2", "1", "2"
    return ",".join(f) if any(f) else None


def apply_formats(token: str, sheet_id: int) -> dict:
    with _client(token) as c:
        r = c.get(f"/sheets/{sheet_id}", params={"exclude": "nonexistentCells"})
        r.raise_for_status()
        cols = {col["title"].strip(): col["id"] for col in r.json().get("columns", [])}
        done = []
        for title, _ in COLUMNS:
            fmt, cid = _column_format(title), cols.get(title)
            if fmt and cid:
                c.put(f"/sheets/{sheet_id}/columns/{cid}", json={"format": fmt}).raise_for_status()
                done.append(title)
    return {"formatted": done}


def set_summary(token: str, sheet_id: int, fields: dict[str, str]) -> dict:
    """Write name -> value into the sheet's Summary panel, creating fields as
    needed. Used for "Receipts as of": the Received? column is only as good as
    the newest receipt pull, and a reader has no other way to know how old that
    is. Text fields on purpose -- values arrive already formatted m/d/yy."""
    with _client(token) as c:
        r = c.get(f"/sheets/{sheet_id}/summary/fields")
        r.raise_for_status()
        have = {f["title"]: f["id"] for f in r.json().get("data", [])}
        missing = [t for t in fields if t not in have]
        if missing:
            r = c.post(f"/sheets/{sheet_id}/summary/fields",
                       json=[{"title": t, "type": "TEXT_NUMBER"} for t in missing])
            r.raise_for_status()
            for f in r.json()["result"]:
                have[f["title"]] = f["id"]
        r = c.put(f"/sheets/{sheet_id}/summary/fields",
                  json=[{"id": have[t], "objectValue": v} for t, v in fields.items()])
        r.raise_for_status()
    return {"summary": list(fields)}


# Where a row's identity is kept on the sheet. Hidden from the reader by being
# the last column; without it the parent/child rows could only be matched by
# re-deriving keys from cell text, which breaks the moment someone edits one.
KEY_COLUMN = "Row Key"


def _ensure_key_column(c: httpx.Client, sheet_id: int, cols: dict) -> dict:
    """Add whatever the sheet is missing: the Row Key, and any column added to
    COLUMNS since the sheet was created. New columns go where they sit in
    COLUMNS, so a field added mid-list lands beside its neighbours rather than
    at the far right; Row Key stays last."""
    want = [(t, _api_type(k)) for t, k in COLUMNS] + [(KEY_COLUMN, "TEXT_NUMBER")]
    missing = [(i, t, k) for i, (t, k) in enumerate(want) if t not in cols]
    if not missing:
        return cols
    for i, t, k in missing:
        r = c.post(f"/sheets/{sheet_id}/columns",
                   json=[{"title": t, "type": k, "index": min(i, len(cols))}])
        r.raise_for_status()
        res = r.json()["result"]
        for col in (res if isinstance(res, list) else [res]):
            cols[col["title"]] = col["id"]
    return cols


def _cells(rec: dict, cols: dict) -> list[dict]:
    out = []
    for title, _ in COLUMNS:
        cid = cols.get(title)
        if cid is None:
            continue
        v = rec.get(title)
        out.append({"columnId": cid, "value": v if v is not None else ""})
    out.append({"columnId": cols[KEY_COLUMN], "value": rec["key"]})
    return out


def push(token: str, sheet_id: int, records: list[dict], *, chunk: int = 200) -> dict:
    """Parents first, then children under them. Updates in place by Row Key."""
    with _client(token) as c:
        r = c.get(f"/sheets/{sheet_id}", params={"exclude": "nonexistentCells"})
        r.raise_for_status()
        payload = r.json()
        cols = {col["title"].strip(): col["id"] for col in payload.get("columns", [])}
        cols = _ensure_key_column(c, sheet_id, cols)
        key_id = cols[KEY_COLUMN]
        existing: dict[str, int] = {}
        for row in payload.get("rows", []):
            cell = next((x for x in row.get("cells", []) if x.get("columnId") == key_id), None)
            if cell and cell.get("value"):
                existing[str(cell["value"])] = row["id"]

        added = updated = 0
        # --- parents ---
        parents = [x for x in records if x["parent_key"] is None]
        upd = [{"id": existing[x["key"]], "cells": _cells(x, cols)}
               for x in parents if x["key"] in existing]
        new = [{"toBottom": True, "cells": _cells(x, cols)}
               for x in parents if x["key"] not in existing]
        for i in range(0, len(upd), chunk):
            rr = c.put(f"/sheets/{sheet_id}/rows", json=upd[i:i + chunk]); rr.raise_for_status()
            updated += len(rr.json().get("result", []))
        for i in range(0, len(new), chunk):
            rr = c.post(f"/sheets/{sheet_id}/rows", json=new[i:i + chunk]); rr.raise_for_status()
            for row in rr.json().get("result", []):
                cell = next(x for x in row["cells"] if x.get("columnId") == key_id)
                existing[str(cell["value"])] = row["id"]
            added += len(rr.json().get("result", []))
        # --- children, each under its parent ---
        children = [x for x in records if x["parent_key"] is not None]
        upd = [{"id": existing[x["key"]], "cells": _cells(x, cols)}
               for x in children if x["key"] in existing]
        new = [{"parentId": existing[x["parent_key"]], "toBottom": True,
                "cells": _cells(x, cols)} for x in children if x["key"] not in existing]
        for i in range(0, len(upd), chunk):
            rr = c.put(f"/sheets/{sheet_id}/rows", json=upd[i:i + chunk]); rr.raise_for_status()
            updated += len(rr.json().get("result", []))
        # Rows with different parents cannot share one POST -- the API refuses
        # with 1123 "Specifying multiple row locations is not yet supported"
        # (tested 9/11/26). So NEW children cost one request per job: the
        # first load of 598 lines took 12.6 minutes. Updates batch normally
        # (25s for all 1,021 rows), and a night adds a handful of jobs, so
        # this only hurts on a rebuild.
        by_parent: dict[int, list] = defaultdict(list)
        for row in new:
            by_parent[row["parentId"]].append(row)
        for pid, rows in by_parent.items():
            for i in range(0, len(rows), chunk):
                rr = c.post(f"/sheets/{sheet_id}/rows", json=rows[i:i + chunk]); rr.raise_for_status()
                added += len(rr.json().get("result", []))
    return {"added": added, "updated": updated,
            "jobs": len(parents), "po_lines": len(children)}
