"""The Smartsheet timeline + discrepancy report.

Three columns per compared field -- CabinetTron, the 3.0 tracker, Smartsheet --
with no system treated as the baseline. That was deliberate: the question this
report exists to answer is whether Smartsheet is trustworthy, and a report that
picks a winner in advance cannot answer it.

Alongside the comparison sits the timeline, because on cabinet dates Smartsheet
is mostly blank (measure requested 10%, planned delivery 2%) while the scopes
running ahead of cabinets are kept up. See timeline.py for why we predict.
"""

from __future__ import annotations

import datetime as dt

from app.phases import PHASE_LABELS
from app.smartsheet import compare as C
from app.smartsheet import match as M
from app.smartsheet.scopes import SCOPES, as_date, read_house
from app.smartsheet.timeline import assess, learn_intervals, predict

# Each compared field names which two sources actually decide the verdict. They
# are not always CabinetTron vs Smartsheet: workflow status is a like-for-like
# check against the tracker, while construction stage only makes sense as
# CabinetTron's phase against Smartsheet's job status. All three values are
# still shown -- the verdict just says which pair it is judging.
# Status for a house Smartsheet already calls finished.
DONE = "complete"

# Tracker levels that take a house off the report entirely -- not greyed, not
# filtered by default, just gone. Brian's call 9/10/26: a job that is finished
# or cancelled has nothing left to reconcile, and 106 of them were crowding out
# the houses that do. Read off the tracker's own CONST LVL rather than any
# status the app derives, so it follows what Brian types into the DATA table.
DROPPED_CONST_LVLS = {"6.0-Clsd", "8.0-Void"}

FIELD_PO = "Cabinet PO"
FIELD_ACTUAL = "Actual install"
FIELD_WORKFLOW = "Workflow status"
FIELD_STAGE = "Construction stage"
FIELD_PLAN = "Plan"
FIELD_MEASURE = "Measure date"
FIELD_DELIVERY = "Install / delivery"


# The tracker sheet fills empty cells with formula output rather than leaving
# them blank, so these arrive as text and would otherwise read as real values.
_EMPTY_TEXT = {"na", "n/a", "#n/a", "none", "-", "0", "00:00:00"}


def _show(value) -> str | None:
    d = as_date(value)
    if d:
        return d.isoformat()
    if value in (None, ""):
        return None
    text = str(getattr(value, "value", value)).strip()
    if text.lower() in _EMPTY_TEXT:
        return None
    return text or None


def _fields(job, tracker: dict | None, ss: dict, phase: tuple | None,
            portal: dict | None = None) -> list[dict]:
    """The compared rows for one house.

    Four sources, and not every field has all four. The verdict names which
    pair it is judging so a blank column is never mistaken for a disagreement.
    """
    tr = tracker or {}
    pt = portal or {}
    phase_code = phase[0] if phase else None

    def _iso(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    # The portal's own view of measure and install, lifted before the
    # comparisons because they now take part in them.
    pt_measure, pt_install = _iso(pt.get("measure")), _iso(pt.get("install"))

    ct_status = getattr(job, "status", None) if job else None
    verdict_wf, note_wf = _plain(ct_status, tr.get("CONST LVL"))

    stage_v, stage_note = C.compare_status(phase_code, ss.get("Job Status"))
    plan_v, plan_note = C.compare_plan(getattr(job, "plan", None), ss.get("Plan Name"))
    # Judge against the best counterpart available, not always Smartsheet. The
    # builder's portal IS the builder's system, so where it holds a date it is
    # the thing worth being wrong about -- and on Century it holds one 88% of
    # the time while Smartsheet holds one almost never. Comparing to Smartsheet
    # regardless returned "blank in Smartsheet" on a house whose CabinetTron
    # install sat 78 days off the portal's.
    meas_v, meas_off, meas_basis = _best(
        getattr(job, "measure_date", None), ss.get("Cabinet Measure Requested Date"),
        pt_measure, C.DATE_TOLERANCE_DAYS)
    del_v, del_off, del_basis = _best(
        getattr(job, "install_date", None), ss.get("Cabinet Delivery Requested Date"),
        pt_install, C.DELIVERY_TOLERANCE_DAYS)

    def days(off):
        return None if off is None else f"{off:+d}d"

    po_v, po_note = _plain(getattr(job, "builder_po", None), pt.get("po_number"))
    # The tracker's ACTUAL install date -- what really happened, as opposed to
    # the requested date the other columns carry. Judged against the portal
    # where it has one, since that is the builder's own record of the same day.
    act_v, act_off = C.compare_date(
        tr.get("Actual Install Date"), pt_install or ss.get("Cabinet Delivery Requested Date"),
        tolerance=C.DELIVERY_TOLERANCE_DAYS)

    return [
        {"label": FIELD_WORKFLOW, "basis": "CabinetTron vs tracker",
         "cabinettron": _show(ct_status), "tracker": _show(tr.get("CONST LVL")),
         "smartsheet": None, "portal": None,
         "verdict": verdict_wf, "note": note_wf},
        {"label": FIELD_STAGE, "basis": "phase vs Smartsheet",
         "cabinettron": _show(PHASE_LABELS.get(phase_code) if phase_code else None),
         "tracker": None, "smartsheet": _show(ss.get("Job Status")),
         "portal": _show(pt.get("po_status")),
         "verdict": stage_v, "note": stage_note},
        {"label": FIELD_PLAN, "basis": "CabinetTron vs Smartsheet",
         "cabinettron": _show(getattr(job, "plan", None)), "tracker": _show(tr.get("Plan")),
         "smartsheet": _show(ss.get("Plan Name")), "portal": None,
         "verdict": plan_v, "note": plan_note},
        {"label": FIELD_MEASURE, "basis": meas_basis,
         "cabinettron": _show(getattr(job, "measure_date", None)),
         "tracker": _show(tr.get("Req Measure Date")),
         "smartsheet": _show(ss.get("Cabinet Measure Requested Date")),
         "portal": _show(pt_measure),
         "verdict": meas_v, "note": days(meas_off)},
        {"label": FIELD_DELIVERY, "basis": del_basis,
         "cabinettron": _show(getattr(job, "install_date", None)),
         "tracker": _show(tr.get("Requested Install Date")),
         "smartsheet": _show(ss.get("Cabinet Delivery Requested Date")),
         "portal": _show(pt_install),
         "verdict": del_v, "note": days(del_off)},
        {"label": FIELD_ACTUAL, "basis": "tracker Actual Install Date",
         "cabinettron": _show(getattr(job, "install_date", None)),
         "tracker": _show(tr.get("Actual Install Date")),
         "smartsheet": _show(ss.get("Cabinet Delivery Requested Date")),
         "portal": _show(pt_install),
         "verdict": act_v, "note": days(act_off)},
        {"label": FIELD_PO, "basis": "CabinetTron vs portal",
         "cabinettron": _show(getattr(job, "builder_po", None)),
         "tracker": _show(tr.get("Cabinet PO#")),
         "smartsheet": _show(ss.get("Cabinet Invoice Number")),
         "portal": _show(pt.get("po_number")),
         "verdict": po_v, "note": po_note},
    ]


def _best(ours, smartsheet, portal, tolerance: int) -> tuple[str, int | None, str]:
    """Compare our date to the portal's when it has one, else to Smartsheet.

    Returns the verdict, the signed day difference and which pair was judged,
    so the row can say so rather than leaving the reader to guess.
    """
    if portal:
        v, off = C.compare_date(ours, portal, tolerance=tolerance)
        return v, off, "CabinetTron vs builder portal"
    v, off = C.compare_date(ours, smartsheet, tolerance=tolerance)
    return v, off, "CabinetTron vs Smartsheet"


def _plain(a, b) -> tuple[str, str | None]:
    """Like-for-like text compare, used where both sides share a vocabulary."""
    na = "".join(ch for ch in str(getattr(a, "value", a) or "").lower() if ch.isalnum())
    nb = "".join(ch for ch in str(getattr(b, "value", b) or "").lower() if ch.isalnum())
    if not na and not nb:
        return C.NO_DATA, None
    if not nb:
        return C.BLANK_SS, None
    if not na:
        return C.BLANK_CT, None
    return (C.AGREE, None) if na == nb else (C.DIFFER, None)


def build(smartsheet_rows: list[dict], jobs: list, tracker_rows: list[dict],
          *, phases: dict | None = None, today: dt.date | None = None,
          tracker_ok: bool = True, portal_rows: list[dict] | None = None,
          portal_meta: dict | None = None) -> dict:
    """One report: a row per house, plus the coverage figures that say how much
    of Smartsheet is actually filled in.

    `phases` maps job id -> (phase code, noted_at). Construction stage is the
    only sensible thing to compare against Smartsheet's Job Status, and it lives
    in phase_updates rather than on the job.

    `tracker_ok` is False when the .xlsm could not be read (it is routinely open
    in Excel). The tracker column then renders as unavailable rather than blank,
    so a locked file never masquerades as missing data.
    """
    today = today or dt.date.today()
    phases = phases or {}
    portal = M.index_by_key(portal_rows or [],
                            lambda r: r.get("subdivision"), lambda r: r.get("lot"))
    houses = [read_house(r) for r in smartsheet_rows]
    intervals = learn_intervals(houses)

    def expected(row: dict) -> bool:
        # Cabinets only. We install windows, doors, trim and framing too, but
        # CabinetTron does not track those -- flagging them as missing jobs
        # would be reporting a gap that is not one.
        return "cabinets" in read_house(row).scopes

    matches = M.join(smartsheet_rows, jobs, tracker_rows, expected=expected)

    rows = []
    for m in matches:
        ss = m.smartsheet or {}
        house = read_house(ss) if m.smartsheet else None
        pred = predict(house, intervals) if house else None
        # A row we hold but Smartsheet does not has no timeline to judge -- it
        # is not "no signal" (which means Smartsheet gave us nothing usable),
        # it is simply out of scope for the prediction.
        status, days_off = (assess(house, pred, today) if house
                            else (M.ONLY_CABINETTRON, None))
        # A house Smartsheet already calls Complete is done, whatever the
        # prediction says. Without this the flagged list fills with finished
        # 2025 houses -- 23 of the first 59 -- and the real ones drown.
        if C.stage_of_smartsheet(ss.get("Job Status")) == C.DONE_STAGE:
            status, days_off = DONE, None
        phase = phases.get(m.job.id) if m.job else None
        pt = (portal.get(m.key) or [None])[0]
        fields = _fields(m.job, m.tracker, ss, phase, pt)

        rows.append({
            # Builder comes from the sheet the row was read out of, stamped on
            # by the caller. The row's own Customer column carries stray values
            # (one row reads "@nath") and cannot be trusted for grouping.
            "builder": ss.get("_builder")
                       or (m.job.account.name if m.job and m.job.account else None),
            "subdivision": ss.get("Subdivision")
                           or (m.job.community.name if m.job and m.job.community else None),
            "lot": ss.get("Lot #") or (m.job.lot_number if m.job else None),
            "address": ss.get("Address - House # and Street")
                       or (m.job.address if m.job else None),
            "job_code": m.job.job_code if m.job else None,
            "job_id": m.job.id if m.job else None,
            "match": m.state,
            "scopes": house.scopes if house else {},
            "timeline": [
                {"scope": s.key, "label": s.label,
                 "date": house.dates[s.key].isoformat()}
                for s in SCOPES if house and s.key in house.dates
            ],
            "prediction": None if not pred else {
                "expected": pred.expected.isoformat(),
                "from": pred.anchor, "from_date": pred.anchor_date.isoformat(),
                "days": pred.days, "n": pred.n,
                "window": [pred.window[0].isoformat(), pred.window[1].isoformat()],
            },
            # Straight from the tracker's DATA table, shown as their own
            # columns rather than only inside the expanded detail -- these are
            # the two Brian reads first.
            "const_lvl": _show((m.tracker or {}).get("CONST LVL")),
            "actual_install": _show((m.tracker or {}).get("Actual Install Date")),
            "status": status,
            "days_off": days_off,
            "differences": sum(1 for f in fields if f["verdict"] == C.DIFFER),
            "fields": fields,
        })

    # Drop the closed jobs. Counted first so the report can say how many it is
    # holding back rather than silently showing a smaller number than the
    # tracker does.
    hidden_closed = sum(1 for r in rows if r.get("const_lvl") in DROPPED_CONST_LVLS)
    rows = [r for r in rows if r.get("const_lvl") not in DROPPED_CONST_LVLS]

    rows.sort(key=lambda r: (r["builder"] or "~", r["subdivision"] or "~",
                             str(r["lot"] or "")))
    return {
        "generated": today.isoformat(),
        "tracker_ok": tracker_ok,
        "hidden_closed": hidden_closed,
        "unjoined": unjoined_communities(tracker_rows, smartsheet_rows),
        "portal_files": portal_meta or {},
        "portal_coverage": portal_coverage(portal_rows or []),
        "intervals": {k: {"days": v.days, "n": v.n, "iqr": v.iqr, "usable": v.usable}
                      for k, v in intervals.items()},
        "coverage": coverage(smartsheet_rows),
        "totals": _totals(rows),
        "rows": rows,
    }


def _totals(rows: list[dict]) -> dict:
    """Counted into separate buckets on purpose. Status and match share value
    names ("not in Smartsheet" is both a match state and a status), so folding
    them into one dict silently doubles them."""
    by_status: dict[str, int] = {}
    by_match: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_match[r["match"]] = by_match.get(r["match"], 0) + 1
    return {
        "houses": len(rows),
        "with_differences": sum(1 for r in rows if r["differences"]),
        "by_status": by_status,
        "by_match": by_match,
    }


# Fields whose fill rate is the evidence about how maintained Smartsheet is.
COVERAGE_FIELDS = (
    "Cabinet Measure Requested Date", "Cabinet Delivery Requested Date",
    "Cabinet Delivery Planned Date", "Cabinet Invoice Number",
    "Initial Cabinet Punch", "Blue Tape Ready", "Homeowner Walk Date",
    "Home Closing Date", "Truss Delivery Date Request",
    "Framing Delivery Requested Date", "Foundation Delivery Requested Date",
    "Window and Door Delivery Date Request", "Interior Trim Delivery Request Date",
)


def coverage(smartsheet_rows: list[dict]) -> list[dict]:
    """How much of Smartsheet is filled, measured only over the cabinet houses.

    The denominator matters: 'Cabinet Measure is 7% filled' over every row on a
    framing-heavy sheet is not a fair claim. Over cabinet houses only, it is.
    """
    cab = [r for r in smartsheet_rows if "cabinets" in read_house(r).scopes]
    n = len(cab)
    out = []
    for field in COVERAGE_FIELDS:
        on_sheet = any(field in r for r in cab)
        filled = sum(1 for r in cab
                     if str(r.get(field) or "").strip() not in ("", "None"))
        out.append({
            "field": field,
            "filled": filled,
            "of": n,
            "pct": round(filled * 100 / n) if n else 0,
            "on_sheet": on_sheet,
        })
    return out


# How full the builder's own portal is, per source. Reported beside the
# Smartsheet coverage because the comparison only means something next to it:
# where the portal is empty too, nobody holds the date and Smartsheet cannot be
# blamed for not carrying it.
def portal_coverage(rows: list[dict]) -> list[dict]:
    out = []
    for source in sorted({r.get("source") for r in rows if r.get("source")}):
        sub = [r for r in rows if r.get("source") == source]
        n = len(sub)
        entry = {"source": source, "rows": n}
        for field in ("measure", "install", "punch", "po_number", "po_amount"):
            filled = sum(1 for r in sub if r.get(field))
            entry[field] = round(filled * 100 / n) if n else 0
        out.append(entry)
    return out


# Tracker communities that never find a Smartsheet counterpart. Reported rather
# than fuzzy-matched: difflib pairs "Colonial East TH" with "Colonial East SF",
# and townhomes are not single-family houses. Every entry here is a blind spot
# in the "cabinets not ticked" check -- those houses simply are not being
# compared -- so it needs to be visible, not inferred from a small total.
def unjoined_communities(tracker_rows: list[dict],
                         smartsheet_rows: list[dict]) -> list[dict]:
    from app.smartsheet.match import norm_sub

    known = {norm_sub(r.get("Subdivision")) for r in smartsheet_rows}
    known.discard("")
    counts: dict[str, dict] = {}
    for row in tracker_rows:
        if str(row.get("CONST LVL") or "").strip() in DROPPED_CONST_LVLS:
            continue
        raw = row.get("Community")
        key = norm_sub(raw)
        if not key or key in known:
            continue
        entry = counts.setdefault(key, {
            "community": str(raw), "builder": row.get("Full Builder"), "houses": 0})
        entry["houses"] += 1
    return sorted(counts.values(), key=lambda e: -e["houses"])
