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
    return [
        {header[i]: v for i, v in enumerate(r) if i < len(header) and header[i]}
        for r in rows[1:]
        if any(x is not None for x in r)
    ]


def rows_from_api(sheet_id: int, token: str) -> list[dict]:
    """Live pull. Read-only by construction: this module has no writer, and
    nothing may write to Smartsheet without Brian saying so per change."""
    import requests

    resp = requests.get(
        f"https://api.smartsheet.com/2.0/sheets/{sheet_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=90,
    )
    resp.raise_for_status()
    payload = resp.json()
    titles = {c["id"]: c["title"].strip() for c in payload.get("columns", [])}
    out = []
    for row in payload.get("rows", []):
        rec = {}
        for cell in row.get("cells", []):
            title = titles.get(cell.get("columnId"))
            if title:
                # displayValue keeps a picklist's text; value keeps real dates.
                rec[title] = cell.get("value", cell.get("displayValue"))
        if rec:
            out.append(rec)
    return out
