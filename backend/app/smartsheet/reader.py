"""Get Tract Builder Management rows in, from either source.

Two readers, one shape: a list of {column name: value} dicts. The API reader is
what runs nightly once SMARTSHEET_API_TOKEN is set; the workbook reader is what
runs today off a manual export, and stays useful for backfills and for testing
without touching the live sheets.
"""

from __future__ import annotations

import warnings
from pathlib import Path

# Smartsheet sheet ids, confirmed against the live workspace 9/10/26. Kept here
# rather than in code so adding Kolter or Toll Brothers is an edit, not a deploy.
SHEETS: dict[str, int] = {
    "DR Horton": 3019034829580164,
    "Century Homes": 8136534477721476,
    "Kolter Homes": 1542779139215236,
    "Captiva": 3019857516777348,
    "Toll Brothers": 3800471274737540,
    "Brock Built": 4856052969328516,
    "Truland": 8649548357756804,
    "Traton": 4274450543366020,
    "Fischer Homes": 4815028822691716,
    "Adams": 3182786631389060,
    "Bay County": 5799435326934916,
}

# The cabinet slice of DR + Century. A REPORT, not a sheet -- different API
# endpoint (/reports/{id}), and its columns follow whoever edits the report.
CABINET_REPORT_ID = 6103204382068612


def _informative(value) -> bool:
    """Whether a value should beat another for the same duplicated column.

    Ordering matters: True beats False beats nothing. Both sheets carry a
    column twice ("Cabinets" and "Cabinets "), and the two copies disagree --
    one holds the tick, the other holds an unticked box. Treating False as a
    real value let it block the True and reported two ticked Century houses as
    unticked; treating False as nothing loses the difference between "somebody
    said no" and "nobody said". Ranking them keeps both.
    """
    return value is not None and value is not False and value != ""


def rows_from_xlsx(path: str | Path) -> list[dict]:
    """First worksheet only. The second sheet in a Smartsheet export is the
    comment log, which is a different shape and not row data."""
    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    if not rows:
        return []
    header = [str(h or "").strip() for h in rows[0]]
    return [_row(header, r) for r in rows[1:] if any(x is not None for x in r)]


def _row(header: list[str], values) -> dict:
    """Zip a row against its header, first non-empty wins on a duplicate name.

    Both sheets carry a column twice -- Century has "Cabinets" and "Cabinets "
    (trailing space), DR has "Cabinet Delivery Request" twice. Stripping the
    whitespace makes them collide, and a plain dict comprehension lets the LAST
    one win, which is the empty decoy: Century's cabinet-house count silently
    fell from 46 to 14 that way. Keeping the first non-empty value is stable
    whichever order the duplicates appear in.
    """
    out: dict = {}
    for i, value in enumerate(values):
        if i >= len(header):
            break
        name = header[i]
        if not name:
            continue
        if name in out and _informative(out[name]):
            continue
        out[name] = value
    return out


def rows_from_api(sheet_id: int, token: str) -> list[dict]:
    """Live pull. Read-only by construction: this module has no writer, and
    nothing may write to Smartsheet without Brian saying so per change.

    httpx, not requests -- requests is not a dependency of this project and is
    not installed, so the first version of this would have failed with a
    missing module the moment a token was set. httpx is already here for the
    DOMO pulls.
    """
    import httpx

    resp = httpx.get(
        f"https://api.smartsheet.com/2.0/sheets/{sheet_id}",
        # These sheets are ~257 columns wide and mostly empty; asking for the
        # blank cells back would multiply the payload for nothing.
        params={"exclude": "nonexistentCells"},
        headers={"Authorization": f"Bearer {token}"},
        # A Master sheet is ~250 columns by ~500 rows; the default 5s is not
        # enough and a timeout here silently drops that builder for the night.
        timeout=120.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    payload = resp.json()
    titles = {c["id"]: c["title"].strip() for c in payload.get("columns", [])}
    out = []
    for row in payload.get("rows", []):
        rec = {}
        for cell in row.get("cells", []):
            title = titles.get(cell.get("columnId"))
            if not title:
                continue
            # displayValue keeps a picklist's text; value keeps real dates.
            value = cell.get("value", cell.get("displayValue"))
            # A CHECKBOX arrives as a real bool and BOTH values carry meaning:
            # False is somebody deciding no, an absent cell is nobody deciding.
            # Collapsing False into None loses that -- it reported a
            # deliberately unticked house as "(never set)". Kept as a bool;
            # every consumer already handles it (provides() sees "false" and
            # declines, _show()/_value() treat it as blank text).
            # Same duplicate-title trap as the workbook reader -- see _row.
            if title in rec and _informative(rec[title]):
                continue
            rec[title] = value
        if rec:
            out.append(rec)
    return out
