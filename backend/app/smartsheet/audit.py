"""What Smartsheet actually holds for the houses WE think we have.

The main report is Smartsheet-first: it starts from a Smartsheet row and asks
who else knows about it. This is the other direction, which answers a different
question -- take every DR Horton and Century house in the 3.0 tracker, and show
what, if anything, Smartsheet carries for it.

That direction matters because Smartsheet cannot report a house it has never
heard of. 68 of the 284 live DRH/Century houses in the tracker have no
Smartsheet row at all, and no amount of reading Smartsheet would ever surface
them.
"""

from __future__ import annotations

from app.smartsheet.match import norm_buid, norm_lot, norm_sub
from app.smartsheet.scopes import SCOPES, as_date, scope_matrix

# Builders this sheet covers. Matched on the tracker's "Full Builder", which
# spells out the division ("DR Horton Panama City East", "Century PC").
BUILDER_PREFIXES = ("DR Horton", "Century")

# Smartsheet fields shown as their own column, in the order Brian reads them.
IDENTITY = [
    ("SS job status", "Job Status"),
    ("SS plan", "Plan Name"),
]
CABINET_DATES = [
    ("SS measure req", "Cabinet Measure Requested Date"),
    ("SS delivery req", "Cabinet Delivery Requested Date"),
    ("SS delivery planned", "Cabinet Delivery Planned Date"),
    ("SS cabinet punch", "Initial Cabinet Punch"),
    ("SS blue tape", "Blue Tape Ready"),
    ("SS homeowner walk", "Homeowner Walk Date"),
    ("SS closing", "Home Closing Date"),
]
UPSTREAM_DATES = [
    ("SS foundation", "Foundation Delivery Requested Date"),
    ("SS framing", "Framing Delivery Requested Date"),
    ("SS truss", "Truss Delivery Date Request"),
    ("SS wdw/door", "Window and Door Delivery Date Request"),
    ("SS int trim", "Interior Trim Delivery Request Date"),
]
# The score counts only fields that genuinely vary. Job Status and Plan Name are
# ~100% filled on any row that exists, so including them would flatter every
# house by two and hide the difference between a rich row and a bare one.
SCORED = CABINET_DATES + UPSTREAM_DATES

COLUMNS = (
    ["Job code", "Builder", "Community", "Lot", "BUID", "CONST LVL",
     "Actual install", "In Smartsheet", "Matched by"]
    + [label for label, _ in IDENTITY]
    + ["SS cabinets ticked"]
    + [label for label, _ in CABINET_DATES]
    + [label for label, _ in UPSTREAM_DATES]
    + ["SS scopes", f"SS dates filled (of {len(SCORED)})"]
)


def _value(raw):
    """A date as a date, a real value as text, Excel's empty-cell formula
    output as nothing at all."""
    d = as_date(raw)
    if d:
        return d
    if raw is None:
        return None
    text = str(raw).strip()
    if text.lower() in {"", "na", "n/a", "#n/a", "none", "false", "0", "00:00:00"}:
        return None
    return text


def build(tracker_rows: list[dict], smartsheet_rows: list[dict],
          *, drop_levels: set[str]) -> list[dict]:
    """One row per live DRH/Century tracker house, worst-covered first."""
    by_buid: dict[str, dict] = {}
    by_key: dict[tuple, dict] = {}
    for r in smartsheet_rows:
        b = norm_buid(r.get("Lot ID"))
        if b:
            by_buid.setdefault(b, r)
        k = (norm_sub(r.get("Subdivision")), norm_lot(r.get("Lot #")))
        if k[0]:
            by_key.setdefault(k, r)

    out = []
    for t in tracker_rows:
        if not str(t.get("Full Builder") or "").startswith(BUILDER_PREFIXES):
            continue
        if str(t.get("CONST LVL") or "").strip() in drop_levels:
            continue

        buid = norm_buid(t.get("Builder Job Code"))
        key = (norm_sub(t.get("Community")), norm_lot(t.get("Lot #")))
        ss = by_buid.get(buid) if buid else None
        how = "BUID" if ss else ""
        if ss is None:
            ss = by_key.get(key)
            how = "community + lot" if ss else "not found"

        row = {
            "Job code": _value(t.get("Job Code")),
            "Builder": _value(t.get("Full Builder")),
            "Community": _value(t.get("Community")),
            "Lot": _value(t.get("Lot #")),
            "BUID": buid,
            "CONST LVL": _value(t.get("CONST LVL")),
            "Actual install": _value(t.get("Actual Install Date")),
            "In Smartsheet": "yes" if ss else "NO",
            "Matched by": how,
        }
        for label, field in IDENTITY:
            row[label] = _value(ss.get(field)) if ss else None
        # The checkbox has three states and they mean different things: ticked,
        # deliberately unticked, and never touched. Collapsing the last two into
        # "no" would lose the distinction between a decision and an omission.
        if not ss:
            row["SS cabinets ticked"] = None
        else:
            raw = ss.get("Cabinets")
            row["SS cabinets ticked"] = (
                "YES" if str(raw).strip().lower() in {"true", "yes", "x", "1"}
                else "no" if raw is not None and str(raw).strip() != ""
                else "(never set)")
        for label, field in CABINET_DATES + UPSTREAM_DATES:
            row[label] = _value(ss.get(field)) if ss else None
        row["SS scopes"] = (", ".join(sorted(scope_matrix(ss))) or None) if ss else None
        row[COLUMNS[-1]] = sum(1 for label, _ in SCORED if row.get(label) is not None)
        out.append(row)

    # Worst first: the houses Smartsheet knows least about are the point of the
    # sheet, so they should not be on page four.
    out.sort(key=lambda r: (r[COLUMNS[-1]], r["In Smartsheet"] == "yes",
                            r["Builder"] or "", r["Community"] or ""))
    return out


def summary(rows: list[dict]) -> dict:
    found = sum(1 for r in rows if r["In Smartsheet"] == "yes")
    score_col = COLUMNS[-1]
    return {
        "houses": len(rows),
        "found": found,
        "missing": len(rows) - found,
        "by_match": {k: sum(1 for r in rows if r["Matched by"] == k)
                     for k in ("BUID", "community + lot", "not found")},
        "no_dates": sum(1 for r in rows if r[score_col] == 0),
        "avg_filled": round(sum(r[score_col] for r in rows) / len(rows), 1) if rows else 0,
    }
