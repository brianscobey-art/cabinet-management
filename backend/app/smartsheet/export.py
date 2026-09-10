"""Excel export of the Smartsheet report.

Four kinds of tab: the summary, the coverage evidence, the houses that need
action, and one per builder. The coverage tab is the one that answers the
question this report was built for, so it sits second rather than buried.
"""

from __future__ import annotations

import datetime as dt
import io
import re

DATE_FMT = "m/d/yy"          # Brian's standing display format
MONEY_FMT = '$#,##0.00;[Red]-$#,##0.00'

CARTER_GREEN = "125952"
NEG = "C0392B"
WARN = "B7791F"
POS = "2F6F5E"
GREY = "666666"

# Statuses that mean somebody has to do something.
ACTION = {"overdue", "due now", "off plan"}


def _head(ws, row: int, labels: list[str]) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    for i, label in enumerate(labels, start=1):
        cell = ws.cell(row=row, column=i, value=label)
        cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=CARTER_GREEN)
        cell.alignment = Alignment(horizontal="center", vertical="center",
                                   wrap_text=True)


def _title(ws, text: str, subtitle: str | None = None) -> int:
    from openpyxl.styles import Font

    ws.cell(row=1, column=1, value=text).font = Font(
        name="Calibri", size=15, bold=True, color=CARTER_GREEN)
    if subtitle:
        ws.cell(row=2, column=1, value=subtitle).font = Font(
            name="Calibri", size=10, color=GREY)
        return 4
    return 3


def _widths(ws, widths: list[int]) -> None:
    from openpyxl.utils import get_column_letter

    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


HOUSE_COLS = ["Builder", "Subdivision", "Lot", "Job code", "CONST LVL",
              "Actual install", "Match", "Status", "Days off",
              "Expected cabinets", "Predicted from",
              "Portal measure", "Portal install", "Portal PO", "Scopes",
              "Disagreements"]
HOUSE_WIDTHS = [18, 24, 10, 14, 14, 14, 18, 14, 10, 18, 22, 15, 15, 18, 30, 13]
# 1-indexed columns holding a number or a date -- centred, per Brian 9/10/26.
HOUSE_CENTRED = {3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 16}

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _typed(value):
    """Write a date as a real date so Excel can format and sort it.

    Everything upstream carries dates as ISO strings because that is what the
    API returns; handing that straight to openpyxl stores TEXT, which sorts
    lexically and ignores the number format. Converting here keeps the API
    honest and the workbook usable.
    """
    if isinstance(value, str):
        m = _ISO.match(value)
        if m:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return value


def _write(ws, row: int, col: int, value, *, centre: bool = False):
    from openpyxl.styles import Alignment

    typed = _typed(value)
    cell = ws.cell(row=row, column=col, value=typed)
    if isinstance(typed, dt.date):
        cell.number_format = DATE_FMT
        centre = True
    if centre or isinstance(typed, (int, float)):
        cell.alignment = Alignment(horizontal="center")
    return cell


def _pretty_from(pred: dict) -> str:
    """'windows 8/12/26' -- the anchor scope and its date, in Brian's format."""
    raw = str(pred.get("from_date") or "")
    m = _ISO.match(raw)
    shown = f"{int(m.group(2))}/{int(m.group(3))}/{m.group(1)[2:]}" if m else raw
    return f"{pred.get('from')} {shown}".strip()


def _house_row(r: dict) -> list:
    pred = r.get("prediction") or {}
    scopes = ", ".join(sorted(r.get("scopes") or {}))
    return [
        r.get("builder"), r.get("subdivision"), _lot(r.get("lot")),
        r.get("job_code"), r.get("const_lvl"), r.get("actual_install"),
        r.get("match"), r.get("status"), r.get("days_off"),
        pred.get("expected"),
        _pretty_from(pred) if pred else None,
        _field(r, "Measure date", "portal"),
        _field(r, "Install / delivery", "portal"),
        _field(r, "Cabinet PO", "portal"),
        scopes, r.get("differences") or None,
    ]


def _lot(value) -> str:
    """Excel exports numeric cells as floats, so a lot arrives as "21.0". Show
    the number people use; leave A027 and 24B alone. Matches fmtLot in the web
    view so the workbook and the page never disagree about a lot number."""
    text = str(value or "").strip()
    m = re.fullmatch(r"(\d+)(?:\.0+)?", text)
    return str(int(m.group(1))) if m else text


def _field(row: dict, label: str, key: str):
    """One value out of a house's compared fields, by label."""
    return next((f.get(key) for f in row.get("fields", [])
                 if f.get("label") == label), None)


def _house_sheet(wb, name: str, rows: list[dict], *, heading: str,
                 subtitle: str, first: bool = False):
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    ws = wb.active if first else wb.create_sheet()
    safe = name[:31]
    for ch in (":", chr(92), "/", "?", "*", "[", "]"):
        safe = safe.replace(ch, "-")
    ws.title = safe
    r = _title(ws, heading, subtitle)
    _head(ws, r, HOUSE_COLS)
    for j, row in enumerate(rows, start=r + 1):
        for i, value in enumerate(_house_row(row), start=1):
            _write(ws, j, i, value, centre=i in HOUSE_CENTRED)
        state = row.get("status")
        if state in ACTION:
            ws.cell(row=j, column=8).font = Font(
                name="Calibri", size=11, bold=True,
                color=NEG if state == "overdue" else WARN)
    _widths(ws, HOUSE_WIDTHS)
    ws.freeze_panes = ws.cell(row=r + 1, column=1)
    if rows:
        ws.auto_filter.ref = (f"A{r}:{get_column_letter(len(HOUSE_COLS))}"
                              f"{r + len(rows)}")
    return ws


def to_xlsx(data: dict) -> io.BytesIO:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    rows = data["rows"]
    totals = data["totals"]
    stamp = (f"Smartsheet pulled {data.get('pulled_at') or 'never'}  |  "
             f"tracker {data.get('tracker_file') or 'unavailable'}  |  "
             f"generated {data['generated']}")

    wb = Workbook()

    # --- 1. Summary ---------------------------------------------------------
    ws = wb.active
    ws.title = "Summary"
    r = _title(ws, "Smartsheet vs CabinetTron", stamp)
    ws.cell(row=r, column=1, value="Houses").font = Font(bold=True)
    _write(ws, r, 2, totals["houses"], centre=True)
    r += 1
    ws.cell(row=r, column=1, value="With a real disagreement").font = Font(bold=True)
    _write(ws, r, 2, totals["with_differences"], centre=True)
    if data.get("hidden_closed"):
        r += 1
        ws.cell(row=r, column=1,
                value="Closed + void jobs excluded (CONST LVL 6.0-Clsd, 8.0-Void)").font = Font(
            name="Calibri", size=10, color=GREY)
        _write(ws, r, 2, data["hidden_closed"], centre=True)
    r += 2
    for heading, bucket in (("By timeline status", "by_status"),
                            ("By match", "by_match")):
        ws.cell(row=r, column=1, value=heading).font = Font(
            bold=True, color=CARTER_GREEN)
        r += 1
        for key, count in sorted(totals[bucket].items(), key=lambda kv: -kv[1]):
            ws.cell(row=r, column=1, value=key)
            _write(ws, r, 2, count, centre=True)
            if key in ACTION:
                ws.cell(row=r, column=1).font = Font(bold=True, color=NEG)
            r += 1
        r += 1
    ws.cell(row=r, column=1, value="Intervals learned (to cabinet delivery)").font = Font(
        bold=True, color=CARTER_GREEN)
    r += 1
    _head(ws, r, ["Anchor scope", "Median days", "Houses", "Spread (IQR)", "Used?"])
    r += 1
    for key, iv in data["intervals"].items():
        ws.cell(row=r, column=1, value=key)
        for col, val in ((2, iv["days"]), (3, iv["n"]), (4, iv["iqr"]),
                         (5, "yes" if iv["usable"] else "too loose")):
            _write(ws, r, col, val, centre=True)
        r += 1
    _widths(ws, [34, 14, 12, 14, 12])

    # --- 2. Coverage: the evidence -----------------------------------------
    ws = wb.create_sheet("Smartsheet coverage")
    r = _title(ws, "How much of Smartsheet is filled in",
               "Measured over cabinet houses only -- a fill rate across a "
               "framing-heavy sheet would not be a fair claim.")
    _head(ws, r, ["Field", "Filled", "Of", "%", "On every sheet?"])
    for j, c in enumerate(data["coverage"], start=r + 1):
        ws.cell(row=j, column=1, value=c["field"])
        _write(ws, j, 2, c["filled"], centre=True)
        _write(ws, j, 3, c["of"], centre=True)
        pct = _write(ws, j, 4, c["pct"] / 100, centre=True)
        pct.number_format = "0%"
        pct.font = Font(name="Calibri", size=11, bold=True,
                        color=NEG if c["pct"] < 25 else
                        WARN if c["pct"] < 60 else POS)
        _write(ws, j, 5, "yes" if c["on_sheet"] else "missing on some", centre=True)
    _widths(ws, [40, 10, 8, 8, 18])
    ws.freeze_panes = ws.cell(row=r + 1, column=1)

    # --- 2b. Where the check cannot see ------------------------------------
    if data.get("unjoined"):
        ws = wb.create_sheet("Not being checked")
        r = _title(ws, "Tracker communities Smartsheet does not name the same way",
                   "These houses are never compared, so a missing Cabinets tick "
                   "on any of them would not show up. Each needs its Smartsheet "
                   "name confirmed before it can be matched.")
        _head(ws, r, ["Tracker community", "Builder", "Houses"])
        for j, u in enumerate(data["unjoined"], start=r + 1):
            ws.cell(row=j, column=1, value=u["community"])
            ws.cell(row=j, column=2, value=u["builder"])
            _write(ws, j, 3, u["houses"], centre=True)
        _widths(ws, [38, 30, 10])
        ws.freeze_panes = ws.cell(row=r + 1, column=1)

    # --- 2c. What Smartsheet holds for the houses we have -------------------
    if data.get("audit"):
        from app.smartsheet import audit as A

        rows_a = data["audit"]
        summ = data.get("audit_summary") or {}
        ws = wb.create_sheet("Our houses in Smartsheet")
        sub = (f"{summ.get('houses', 0)} live DR Horton and Century houses from the "
               f"3.0 tracker  |  {summ.get('found', 0)} found in Smartsheet, "
               f"{summ.get('missing', 0)} not there at all  |  "
               f"{summ.get('no_dates', 0)} carry no Smartsheet dates  |  "
               f"average {summ.get('avg_filled', 0)} of {len(A.SCORED)} date fields")
        r = _title(ws, "Our houses, and what Smartsheet has for them", sub)
        _head(ws, r, A.COLUMNS)
        # Dates and counts centred; the identity columns stay left.
        centred = {A.COLUMNS.index(c) + 1 for c in A.COLUMNS
                   if c.startswith("SS ") or c in ("Lot", "BUID", "CONST LVL",
                                                   "Actual install", "In Smartsheet")}
        centred.discard(A.COLUMNS.index("SS scopes") + 1)
        for j, row in enumerate(rows_a, start=r + 1):
            for i, col in enumerate(A.COLUMNS, start=1):
                cell = _write(ws, j, i, row.get(col), centre=i in centred)
            # A house Smartsheet has never heard of is the strongest finding on
            # the sheet; colour it rather than leaving it to be scrolled past.
            if row.get("In Smartsheet") == "NO":
                ws.cell(row=j, column=A.COLUMNS.index("In Smartsheet") + 1).font = Font(
                    name="Calibri", size=11, bold=True, color=NEG)
        widths = []
        for c in A.COLUMNS:
            widths.append(30 if c == "SS scopes" else 22 if c == "Community"
                          else 20 if c in ("Builder", "Job code") else 15)
        _widths(ws, widths)
        ws.freeze_panes = ws.cell(row=r + 1, column=6)
        if rows_a:
            ws.auto_filter.ref = (f"A{r}:{get_column_letter(len(A.COLUMNS))}"
                                  f"{r + len(rows_a)}")

    # --- 3. Needs action ----------------------------------------------------
    action = [r_ for r_ in rows if r_.get("status") in ACTION
              or r_.get("differences")]
    _house_sheet(wb, "Needs action", action,
                 heading="Houses needing a look",
                 subtitle="Overdue, due now, off plan, or disagreeing with "
                          "CabinetTron on a compared field.")

    # --- 4. One tab per SMARTSHEET builder ---------------------------------
    # Grouped on the sheet a row came from, not on the CabinetTron account name.
    # Houses we hold but Smartsheet does not carry their own account names
    # ("Retail", "Homeowner", a one-off custom builder) and would otherwise
    # each open a tab of their own.
    from_smartsheet = [r_ for r_ in rows if r_["match"] != "not in Smartsheet"]
    for builder in sorted({r_["builder"] for r_ in from_smartsheet if r_["builder"]}):
        subset = [r_ for r_ in from_smartsheet if r_["builder"] == builder]
        flagged = sum(1 for r_ in subset if r_.get("status") in ACTION)
        _house_sheet(wb, builder, subset, heading=builder,
                     subtitle=f"{len(subset)} houses  |  {flagged} needing action")

    missing = [r_ for r_ in rows if r_["match"] == "not in Smartsheet"]
    if missing:
        _house_sheet(wb, "Not in Smartsheet", missing,
                     heading="In CabinetTron, not in Smartsheet",
                     subtitle="Only where Smartsheet already tracks the "
                              "subdivision -- a lot it is missing, not a job "
                              "it was never meant to hold.")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
