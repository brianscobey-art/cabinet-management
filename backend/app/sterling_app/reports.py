"""Sterling reports — one definition, three renderings (screen, Excel, PowerPoint).

A report is a REPORTS entry: a title, a subtitle, columns, and a build function
returning {"meta": {...}, "rows": [...]}. The screen, the .xlsx and the .pptx all
read that one structure, so a column added here shows up in every export and the
three can never drift apart.

Column spec: (key, label, kind) where kind is
    text | num | money | pct | pill   — kind drives alignment and formatting.
"""

from __future__ import annotations

import collections
import statistics
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

CARTER_GREEN = "125952"
NEG = "9E2B25"
POS = "2F6F5E"
WARN = "B07D21"


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    blurb: str
    columns: list[tuple[str, str, str]]
    build: Callable
    notes: str = ""
    inputs: list[dict] = field(default_factory=list)
    group_by: str | None = None   # column to split into per-group tabs


# --------------------------------------------------------------------------
# Plan margin vs actual PO
# --------------------------------------------------------------------------
MARGIN_COLUMNS = [
    ("plan", "Plan", "text"),
    ("division", "Division", "text"),
    ("n", "Houses", "num"),
    ("po_price", "PO price", "pill"),
    ("avg", "Avg PO", "money"),
    ("cogs", "Our cost", "money"),
    ("sale", "Our price", "money"),
    ("gap", "Gap / house", "money"),
    ("exp", "12-month", "money"),
    ("margin", "Margin", "pct"),
    ("target", "Target", "pct"),
    ("status", "Status", "text"),
]


ADJUST_BELOW = 0.10   # a division under this needs its pricing revisited


def rollup(rows: list[dict], group_key: str, target_default: float = 0.15) -> list[dict]:
    """Group plan rows into a per-division summary.

    Margin is DOLLAR-WEIGHTED, not the mean of the plan margins: a plan built
    once should not move a division as much as one built twenty times, and the
    mean would let a single bad one-off drag the whole division under.
    """
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        groups[r.get(group_key) or "—"].append(r)

    out = []
    for name, rs in groups.items():
        houses = sum(r["n"] for r in rs)
        revenue = sum(r["avg"] * r["n"] for r in rs)
        cost = sum(r["cogs"] * r["n"] for r in rs)
        margin = (revenue - cost) / revenue if revenue else 0.0
        target = max((r.get("target") or target_default) for r in rs) if rs else target_default
        below = sum(1 for r in rs if r["margin"] < ADJUST_BELOW)
        action = ("Adjust pricing" if margin < ADJUST_BELOW
                  else "Watch" if margin < target else "OK")
        out.append({
            "division": name, "plans": len(rs), "houses": houses,
            "revenue": round(revenue, 2), "cost": round(cost, 2),
            "avg_po": round(revenue / houses, 2) if houses else 0.0,
            "margin": round(margin, 4), "target": round(target, 4),
            "below10": below,
            "exposure": round(sum(r["exp"] for r in rs), 2),
            "action": action,
        })
    out.sort(key=lambda g: g["margin"])
    return out


DIVISION_COLUMNS = [
    ("division", "Division", "text"),
    ("plans", "Plans", "num"),
    ("houses", "Houses", "num"),
    ("avg_po", "Avg PO", "money"),
    ("revenue", "Revenue", "money"),
    ("cost", "Cost", "money"),
    ("margin", "Avg margin", "pct"),
    ("below10", "Plans under 10%", "num"),
    ("exposure", "12-month", "money"),
    ("action", "Action", "text"),
]


def _vs_po_by_job(path: str) -> tuple[dict, list]:
    """{job number: summed PO amount} from the Vendor Suite combined report.

    Summed per JOB, not per row: a house can carry a change order or backcharge
    as a second PO line, and counting those as separate houses turns a -$100
    adjustment into a whole house at -$100.
    """
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    name = next((s for s in wb.sheetnames if s.startswith("DRH Cabinets Combined")), None)
    if name is None:
        wb.close()
        raise ValueError("no 'DRH Cabinets Combined*' sheet in that workbook")
    ws = wb[name]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    hdr = [str(h).strip() if h else "" for h in rows[0]]
    ix = {h: i for i, h in enumerate(hdr)}
    by_job: dict[str, float] = collections.defaultdict(float)
    dates = []
    for r in rows[1:]:
        job, amt = r[ix["Job Number"]], r[ix["PO Amount"]]
        if job and isinstance(amt, (int, float)):
            by_job[str(job).strip()] += float(amt)
        d = r[ix.get("PO Date", 0)]
        if hasattr(d, "year"):
            dates.append(d)
    wb.close()
    return dict(by_job), dates


def build_plan_margin(db, vs_path: str | None = None, **_) -> dict:
    """Priced plans against what DR Horton actually paid."""
    from app.sterling_app.compute import national_pricing_rows

    if not vs_path:
        vs_path = _newest_vs()
    if not vs_path:
        raise ValueError("No Vendor Suite combined report found — pick one to run this report.")

    by_job, dates = _vs_po_by_job(vs_path)

    # BUID -> plan comes from CabinetTron, which is a separate database.
    from app.database import SessionLocal as CtSession
    from app.models import Job as CtJob, OrderingChecklist

    with CtSession() as ct:
        plan_of = {
            str(c.buid).strip(): (j.plan or "").strip()
            for j, c in ct.query(CtJob, OrderingChecklist)
            .join(OrderingChecklist, OrderingChecklist.job_id == CtJob.id)
            .all()
            if c.buid
        }

    priced = {r["plan"]: r for r in national_pricing_rows(db, None, None)}

    agg: dict[str, list[float]] = collections.defaultdict(list)
    skipped = collections.Counter()
    for buid, total in by_job.items():
        plan = plan_of.get(buid)
        if plan is None:
            skipped["no job in CabinetTron"] += 1
        elif not plan:
            skipped["job has no plan"] += 1
        elif plan not in priced:
            skipped["plan not priced in Sterling"] += 1
        else:
            agg[plan].append(total)

    rows = []
    for plan, amounts in agg.items():
        p = priced[plan]
        cogs, sale = float(p["cogs"]), float(p["sale"])
        target = float(p["margin_pct"])
        target = target / 100 if target > 1 else target
        avg = statistics.mean(amounts)
        spread = max(amounts) - min(amounts)
        margin = (avg - cogs) / avg if avg else 0.0
        status = ("Below cost" if margin < 0
                  else "Below target" if margin < target - 0.005 else "OK")
        rows.append({
            "plan": plan, "division": p["division"], "n": len(amounts),
            "po_price": "Fixed" if spread < 1 else f"Varies ${spread:,.0f}",
            "avg": round(avg, 2), "cogs": round(cogs, 2), "sale": round(sale, 2),
            "gap": round(avg - sale, 2), "exp": round((avg - sale) * len(amounts), 2),
            "margin": round(margin, 4), "target": round(target, 4), "status": status,
        })
    rows.sort(key=lambda r: r["exp"])

    under = -sum(r["exp"] for r in rows if r["exp"] < 0)
    over = sum(r["exp"] for r in rows if r["exp"] > 0)
    meta = {
        "source": Path(vs_path).name,
        "period": (f"{min(dates).month}/{min(dates).day}/{min(dates):%y} – "
                   f"{max(dates).month}/{max(dates).day}/{max(dates):%y}" if dates else ""),
        "houses": sum(r["n"] for r in rows),
        "plans": len(rows),
        "under": round(under, 2),
        "over": round(over, 2),
        "net": round(under - over, 2),
        "below_cost": sum(1 for r in rows if r["margin"] < 0),
        "skipped": dict(skipped),
        "headline": [
            ("Net, 12 months", f"-${under - over:,.0f}", "under-contract minus over"),
            ("Priced below", f"-${under:,.0f}",
             f"{sum(1 for r in rows if r['exp'] < 0)} plans"),
            ("Priced above", f"+${over:,.0f}",
             f"{sum(1 for r in rows if r['exp'] > 0)} plans"),
            ("Below cost", str(sum(1 for r in rows if r["margin"] < 0)),
             "plans under our cost"),
        ],
    }
    return {"meta": meta, "rows": rows}


def _newest_vs() -> str | None:
    """Newest DRH_Cabinets_Combined_*.xlsx from the feed folder."""
    from app.config import get_settings

    folder = Path(get_settings().vendorsuite_dir)
    if not folder.is_dir():
        return None
    files = sorted(folder.glob("DRH_Cabinets_Combined_*.xlsx"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    return str(files[0]) if files else None


REPORTS: dict[str, Report] = {
    "plan-margin": Report(
        key="plan-margin",
        title="Plan Margin vs Actual PO",
        blurb="Every priced house plan against what DR Horton actually paid, "
              "ranked by 12-month exposure.",
        columns=MARGIN_COLUMNS,
        build=build_plan_margin,
        group_by="division",
        notes=(
            "PO amounts are summed per job — a house can carry a change order or "
            "backcharge as a second PO line. Margin is against cabinet cost, not "
            "total: the DRH cabinet PO covers cabinets and install, while "
            "countertops are billed separately."
        ),
    ),
}


def run(key: str, db, **kwargs) -> dict:
    rep = REPORTS.get(key)
    if rep is None:
        raise KeyError(key)
    data = rep.build(db, **kwargs)
    data["report"] = {"key": rep.key, "title": rep.title, "blurb": rep.blurb,
                      "notes": rep.notes, "group_by": rep.group_by,
                      "columns": [{"key": k, "label": lb, "kind": kd}
                                  for k, lb, kd in rep.columns],
                      "group_columns": [{"key": k, "label": lb, "kind": kd}
                                        for k, lb, kd in DIVISION_COLUMNS]}
    if rep.group_by:
        data["groups"] = rollup(data["rows"], rep.group_by)
    today = date.today()
    # %-m is glibc-only; this app runs on Windows too.
    data["meta"]["generated"] = f"{today.month}/{today.day}/{today:%y}"
    return data


def catalog() -> list[dict]:
    return [{"key": r.key, "title": r.title, "blurb": r.blurb} for r in REPORTS.values()]
