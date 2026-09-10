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

FIELD_WORKFLOW = "Workflow status"
FIELD_STAGE = "Construction stage"
FIELD_PLAN = "Plan"
FIELD_MEASURE = "Measure date"
FIELD_DELIVERY = "Install / delivery"


def _show(value) -> str | None:
    d = as_date(value)
    if d:
        return d.isoformat()
    if value in (None, ""):
        return None
    text = str(getattr(value, "value", value)).strip()
    return text or None


def _fields(job, tracker: dict | None, ss: dict, phase: tuple | None) -> list[dict]:
    """The five compared rows for one house."""
    tr = tracker or {}
    phase_code = phase[0] if phase else None

    ct_status = getattr(job, "status", None) if job else None
    verdict_wf, note_wf = _plain(ct_status, tr.get("CONST LVL"))

    stage_v, stage_note = C.compare_status(phase_code, ss.get("Job Status"))
    plan_v, plan_note = C.compare_plan(getattr(job, "plan", None), ss.get("Plan Name"))
    meas_v, meas_off = C.compare_date(
        getattr(job, "measure_date", None), ss.get("Cabinet Measure Requested Date"),
        tolerance=C.DATE_TOLERANCE_DAYS)
    del_v, del_off = C.compare_date(
        getattr(job, "install_date", None), ss.get("Cabinet Delivery Requested Date"),
        tolerance=C.DELIVERY_TOLERANCE_DAYS)

    def days(off):
        return None if off is None else f"{off:+d}d"

    return [
        {"label": FIELD_WORKFLOW, "basis": "CabinetTron vs tracker",
         "cabinettron": _show(ct_status), "tracker": _show(tr.get("CONST LVL")),
         "smartsheet": None, "verdict": verdict_wf, "note": note_wf},
        {"label": FIELD_STAGE, "basis": "phase vs Smartsheet",
         "cabinettron": _show(PHASE_LABELS.get(phase_code) if phase_code else None),
         "tracker": None, "smartsheet": _show(ss.get("Job Status")),
         "verdict": stage_v, "note": stage_note},
        {"label": FIELD_PLAN, "basis": "CabinetTron vs Smartsheet",
         "cabinettron": _show(getattr(job, "plan", None)), "tracker": _show(tr.get("Plan")),
         "smartsheet": _show(ss.get("Plan Name")), "verdict": plan_v, "note": plan_note},
        {"label": FIELD_MEASURE, "basis": "CabinetTron vs Smartsheet",
         "cabinettron": _show(getattr(job, "measure_date", None)),
         "tracker": _show(tr.get("Req Measure Date")),
         "smartsheet": _show(ss.get("Cabinet Measure Requested Date")),
         "verdict": meas_v, "note": days(meas_off)},
        {"label": FIELD_DELIVERY, "basis": "install vs delivery request",
         "cabinettron": _show(getattr(job, "install_date", None)),
         "tracker": _show(tr.get("Requested Install Date")),
         "smartsheet": _show(ss.get("Cabinet Delivery Requested Date")),
         "verdict": del_v, "note": days(del_off)},
    ]


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
          tracker_ok: bool = True) -> dict:
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
        fields = _fields(m.job, m.tracker, ss, phase)

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
            "status": status,
            "days_off": days_off,
            "differences": sum(1 for f in fields if f["verdict"] == C.DIFFER),
            "fields": fields,
        })

    rows.sort(key=lambda r: (r["builder"] or "~", r["subdivision"] or "~",
                             str(r["lot"] or "")))
    return {
        "generated": today.isoformat(),
        "tracker_ok": tracker_ok,
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
