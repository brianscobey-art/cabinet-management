"""PO Line Items -- item-level detail for every purchase order (Brian 11/24/26).

DOMO's "ALL Purchase Orders by Customer and Supplier" card (1515720862, the
daily "CabinetTron feed - Purchase Orders" email) has one row per PO. Its
drill-down card (584540536) has the items, but a drill card cannot be put on
a DOMO scheduled report, so scripts/domo_po_lines_pull.py exports it through
Brian's signed-in Chrome every morning and writes "DOMO PO Lines MMDDYY.csv".

Rows (columns: Transaction Date, Order Number, Assigned Salesperson,
Customer : Job, Supplier, SKU, Spec Description, Quantity Ordered, Ordered
Cost, Quantity Received, Received Cost):
  * one header row per PO -- Spec Description "-" (the export writes "'-"),
    the PO's ordered cost (special orders: a $1 placeholder);
  * one item row per item -- Spec Description = the item code, whole-dollar
    received cost; item rows total to the PO's received cost within dollars.

Links: po_number -> DomoPo.our_po (the Purchase Orders feed); account (I or G
code, prefix kept) -> I-Account Detail / G-Account Billed and the job's own
I/G code; cab_job_code (text after "CAB " in the account name) -> job_code.

Also here: the I-Account Detail email ("DOMO I-Account Detail MMDDYY.csv")
and the three checks every run makes.
"""
from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.orm import Session

from app.job_accounts import code_key
from app.models import DomoPo, IAccountLine, Job, PoLineItem

FILE_GLOB = "DOMO PO Lines*.csv"
IACCOUNT_GLOB = "DOMO I-Account Detail*.csv"
COLS = ["Transaction Date", "Order Number", "Assigned Salesperson", "Customer : Job", "Supplier", "SKU",
        "Spec Description", "Quantity Ordered", "Ordered Cost", "Quantity Received", "Received Cost"]
IACCOUNT_COLS = ["Job Final Bill", "Job", "SKU", "Status", "Cost", "Sales"]

# Shown next to DOMO's supplier name. Hype Mill sells the range hoods: cabinet
# material, not install labor.
VENDOR_ALIASES = {"70322": "Hoodsly"}

RECEIVED_TOLERANCE = Decimal("5")  # item lines vs the PO feed's received cost
_HEADER_SPECS = {"-", "'-"}
_CAB = re.compile(r"\bCAB\s+(.+?)\s*$", re.I)


def newest_file(folder: Path, pattern: str = FILE_GLOB) -> Path | None:
    files = sorted(folder.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True) if folder.is_dir() else []
    return files[0] if files else None


def _dec(v) -> Decimal | None:
    s = str(v or "").replace(",", "").replace("$", "").strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _date(v) -> date | None:
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", str(v or "").strip())
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def _split_code(v) -> tuple[str | None, str | None]:
    """'70322: HYPE MILL LLC' -> ('70322', 'HYPE MILL LLC')."""
    s = str(v or "").strip()
    if ":" in s:
        a, b = s.split(":", 1)
        return a.strip() or None, b.strip() or None
    return None, s or None


def parse(text: str) -> list[dict]:
    """The export's CSV -> one dict per line, ready for PoLineItem."""
    out = []
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        po = r.get("Order Number")
        if not po:
            continue
        spec = r.get("Spec Description", "")
        header = spec in _HEADER_SPECS
        supplier_id, supplier_name = _split_code(r.get("Supplier"))
        account, account_name = _split_code(r.get("Customer : Job"))
        cab = _CAB.search(account_name or "")
        out.append({
            "po_number": po,
            "line_type": "header" if header else "item",
            "transaction_date": _date(r.get("Transaction Date")),
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "vendor_alias": VENDOR_ALIASES.get(supplier_id or ""),
            "carter_sku": r.get("SKU") or None,
            "item_code": None if header else (spec or None),
            "qty_ordered": _dec(r.get("Quantity Ordered")),
            "ordered_cost": _dec(r.get("Ordered Cost")),
            "qty_received": _dec(r.get("Quantity Received")),
            "received_cost": _dec(r.get("Received Cost")),
            "account": account.upper() if account else None,
            "account_name": account_name,
            "cab_job_code": cab[1].strip().upper() if cab else None,
            "salesperson": r.get("Assigned Salesperson") or None,
        })
    return out


def _alnum(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _job_index(db: Session) -> tuple[dict[str, int], dict[str, int]]:
    by_account, by_code = {}, {}
    for j in db.query(Job).all():
        for c in (j.i_code, j.g_code):
            if c and c.strip():
                by_account.setdefault(code_key(c), j.id)  # code_key keeps the I/G prefix
        if j.job_code:
            by_code.setdefault(_alnum(j.job_code), j.id)
    return by_account, by_code


def replace_lines(db: Session, rows: list[dict], pulled_at: datetime | None = None) -> dict:
    """Every PO in `rows` gets exactly the fresh set; POs not in the pull are
    left alone. Each line is tied to a job by its account's I/G code, else by
    the CAB name against the job code."""
    pulled_at = pulled_at or datetime.now(timezone.utc)
    pos = {r["po_number"] for r in rows}
    if pos:
        db.query(PoLineItem).filter(PoLineItem.po_number.in_(pos)).delete(synchronize_session=False)
    by_account, by_code = _job_index(db)
    linked = 0
    for r in rows:
        job_id = (by_account.get(code_key(r["account"])) if r["account"] else None) \
            or by_code.get(_alnum(r["cab_job_code"]))
        linked += job_id is not None
        db.add(PoLineItem(**r, job_id=job_id, pulled_at=pulled_at))
    db.commit()
    items = [r for r in rows if r["line_type"] == "item"]
    return {
        "pos": len(pos), "lines": len(rows), "items": len(items), "linked_to_job": linked,
        "received_total": float(sum((r["received_cost"] or 0) for r in items)),
    }


def import_file(db: Session, path: Path) -> dict:
    return {"file": path.name, **replace_lines(db, parse(path.read_text(encoding="utf-8-sig")))}


# --- I-Account Detail ------------------------------------------------------------
def parse_iaccount(text: str) -> list[dict]:
    out = []
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        g, _ = _split_code(r.get("Job Final Bill"))
        i, i_name = _split_code(r.get("Job"))
        if not i and not g:
            continue
        out.append({"g_account": g.upper() if g else None, "i_account": i.upper() if i else None,
                    "i_account_name": i_name, "sku": r.get("SKU") or None, "status": r.get("Status") or None,
                    "cost": _dec(r.get("Cost")), "sales": _dec(r.get("Sales"))})
    return out


def replace_iaccount(db: Session, rows: list[dict]) -> dict:
    """The card is a full snapshot (this year), so the table is replaced whole."""
    db.query(IAccountLine).delete()
    db.add_all(IAccountLine(**r) for r in rows)
    db.commit()
    return {"lines": len(rows), "i_accounts": len({r["i_account"] for r in rows})}


def import_iaccount_file(db: Session, path: Path) -> dict:
    return {"file": path.name, **replace_iaccount(db, parse_iaccount(path.read_text(encoding="utf-8-sig")))}


# --- checks ------------------------------------------------------------------------
def checks(db: Session, po_numbers: set[str] | None = None) -> dict:
    """The three checks Brian asked for on every run:
    1. item received costs total within $5 of the PO's received cost in the
       Purchase Orders feed;
    2. placeholder POs -- ordered cost $1 but items received;
    3. I-accounts whose lines show sales equal to cost (posted at cost, not
       final billed)."""
    q = db.query(PoLineItem)
    if po_numbers is not None:
        q = q.filter(PoLineItem.po_number.in_(po_numbers))
    by_po: dict[str, dict] = defaultdict(lambda: {"items": 0, "received": Decimal(0), "ordered": None,
                                                    "supplier": None, "alias": None, "account": None,
                                                    "cab_job_code": None})
    for ln in q.all():
        b = by_po[ln.po_number]
        b["supplier"] = b["supplier"] or ln.supplier_name
        b["alias"] = b["alias"] or ln.vendor_alias
        b["account"] = b["account"] or ln.account
        b["cab_job_code"] = b["cab_job_code"] or ln.cab_job_code
        if ln.line_type == "header":
            b["ordered"] = ln.ordered_cost
        else:
            b["items"] += 1
            b["received"] += ln.received_cost or 0
    feed = {p.our_po: p for p in db.query(DomoPo).filter(DomoPo.our_po.in_(list(by_po))).all()} if by_po else {}

    mismatch, placeholder = [], []
    for po, b in sorted(by_po.items()):
        base = {"po_number": po, "supplier": b["supplier"], "vendor_alias": b["alias"],
                "account": b["account"], "cab_job_code": b["cab_job_code"]}
        f = feed.get(po)
        if f is None:
            mismatch.append({**base, "items_received": float(b["received"]), "feed_received": None,
                             "issue": "not in the Purchase Orders feed"})
        elif abs(b["received"] - (f.received_cost or 0)) > RECEIVED_TOLERANCE:
            mismatch.append({**base, "items_received": float(b["received"]),
                             "feed_received": float(f.received_cost or 0),
                             "issue": f"items differ by ${abs(b['received'] - (f.received_cost or 0)):,.2f}"})
        if b["ordered"] is not None and b["ordered"] == 1 and b["items"] and b["received"] > 0:
            placeholder.append({**base, "items": b["items"], "items_received": float(b["received"])})

    totals: dict[str, dict] = defaultdict(lambda: {"cost": Decimal(0), "sales": Decimal(0), "lines": 0,
                                                    "g_account": None, "name": None})
    for ln in db.query(IAccountLine).all():
        if not ln.i_account:
            continue
        t = totals[ln.i_account]
        t["cost"] += ln.cost or 0
        t["sales"] += ln.sales or 0
        t["lines"] += 1
        t["g_account"] = t["g_account"] or ln.g_account
        t["name"] = t["name"] or ln.i_account_name
    at_cost = [
        {"i_account": a, "g_account": t["g_account"], "name": t["name"], "lines": t["lines"],
         "cost": float(t["cost"]), "sales": float(t["sales"])}
        for a, t in sorted(totals.items())
        if t["cost"] > 0 and abs(t["sales"] - t["cost"]) < Decimal("0.5")
    ]
    return {"pos_checked": len(by_po), "received_mismatch": mismatch, "placeholder_pos": placeholder,
            "posted_at_cost": at_cost}


# --- report --------------------------------------------------------------------------
def job_report(db: Session, q: str) -> dict:
    """Every PO (and its lines) for one job, matched by job code, CAB code,
    account (I/G, prefix kept) or PO number."""
    key = _alnum(q)
    job = next((j for j in db.query(Job).filter(Job.job_code.isnot(None)).all() if _alnum(j.job_code) == key), None)
    lines = db.query(PoLineItem).all()
    accounts = {code_key(c) for c in ((job.i_code, job.g_code) if job else ()) if c}
    pick = [ln for ln in lines if (job and ln.job_id == job.id) or _alnum(ln.cab_job_code) == key
            or (ln.account and (code_key(ln.account) in accounts or _alnum(ln.account) == key))
            or ln.po_number == q.strip()]
    feed = {p.our_po: p for p in db.query(DomoPo).filter(DomoPo.our_po.in_({ln.po_number for ln in pick})).all()} \
        if pick else {}
    pos: dict[str, dict] = {}
    for ln in sorted(pick, key=lambda x: (x.po_number, x.line_type != "header", x.item_code or "")):
        p = pos.setdefault(ln.po_number, {
            "po_number": ln.po_number, "transaction_date": ln.transaction_date, "supplier_id": ln.supplier_id,
            "supplier_name": ln.supplier_name, "vendor_alias": ln.vendor_alias, "carter_sku": ln.carter_sku,
            "account": ln.account, "account_name": ln.account_name, "cab_job_code": ln.cab_job_code,
            "job_id": ln.job_id, "salesperson": ln.salesperson, "ordered_cost": None, "items": [],
            "items_received": 0.0, "feed_received": None, "pulled_at": ln.pulled_at,
        })
        if ln.line_type == "header":
            p["ordered_cost"] = float(ln.ordered_cost) if ln.ordered_cost is not None else None
        else:
            p["items"].append({"item_code": ln.item_code, "qty_received": float(ln.qty_received or 0),
                               "received_cost": float(ln.received_cost or 0)})
            p["items_received"] += float(ln.received_cost or 0)
    for po, p in pos.items():
        f = feed.get(po)
        p["feed_received"] = float(f.received_cost) if f is not None and f.received_cost is not None else None
        p["in_feed"] = f is not None
        p["placeholder"] = p["ordered_cost"] == 1 and p["items_received"] > 0
        p["received_ok"] = p["feed_received"] is not None and \
            abs(p["items_received"] - p["feed_received"]) <= float(RECEIVED_TOLERANCE)
    out = sorted(pos.values(), key=lambda p: p["po_number"])
    return {
        "query": q, "job_id": job.id if job else None, "job_code": job.job_code if job else None,
        "pos": out, "po_count": len(out), "item_lines": sum(len(p["items"]) for p in out),
        "items_received": round(sum(p["items_received"] for p in out), 2),
    }
