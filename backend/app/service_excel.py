"""Blank Service Request Excel template + parser for round-tripping into the app.

A field/office person downloads the blank .xlsx, fills the Job Code plus the
Parts and Service tables, and uploads it back; parse_import() reads it into the
structured shape the service API creates a ServiceRequest from.
"""

import io
from datetime import date, datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Border, Font, PatternFill, Side

PARTS_MARKER = "PARTS NEEDED"
SERVICE_MARKER = "SERVICE NEEDED"
PART_ROWS = 15
SERVICE_ROWS = 15
# Parts table columns (must match the on-screen / print Parts Needed table)
PART_HEADERS = ["Item #", "Qty", "Part", "Cabinet", "Style", "Color", "Vendor",
                "Order #", "Order Date", "Due Date", "Notes"]
PART_WIDTHS = [8, 6, 24, 12, 14, 14, 16, 12, 12, 12, 24]
SERVICE_HEADERS = ["Part #", "Cabinet", "Description of Work", "Tech", "Date"]

_HEAD_FILL = PatternFill("solid", fgColor="4A4A4A")
_HEAD_FONT = Font(color="FFFFFF", bold=True)
_LABEL_FONT = Font(bold=True)
_thin = Side(style="thin", color="000000")
_BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def _section(ws, row: int, text: str, span: int):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    c = ws.cell(row=row, column=1, value=text)
    c.fill = _HEAD_FILL
    c.font = _HEAD_FONT


def _headers(ws, row: int, names: list[str]):
    for i, name in enumerate(names, start=1):
        c = ws.cell(row=row, column=i, value=name)
        c.font = _LABEL_FONT
        c.fill = PatternFill("solid", fgColor="EEEEEE")
        c.border = _BORDER


def build_blank_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Service Request"
    for i, w in enumerate(PART_WIDTHS, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    nparts = len(PART_HEADERS)

    ws.cell(row=1, column=1, value="SERVICE REQUEST").font = Font(size=15, bold=True)
    ws.cell(row=2, column=1,
            value="Fill in Job Code, then the Parts and Service tables. Save and send to import "
                  "into Carter Kitchen and Bath.").font = Font(italic=True, color="666666")

    ws.cell(row=3, column=1, value="Job Code").font = _LABEL_FONT
    ws.cell(row=4, column=1, value="Title").font = _LABEL_FONT
    for r in (3, 4):  # widen the fill-in blank across a few columns
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
        for col in range(2, 6):
            ws.cell(row=r, column=col).border = _BORDER

    # Parts section
    _section(ws, 6, PARTS_MARKER, nparts)
    _headers(ws, 7, PART_HEADERS)
    for i in range(PART_ROWS):  # blank rows (not pre-numbered — fill Item # by hand)
        row = 8 + i
        for col in range(1, nparts + 1):
            ws.cell(row=row, column=col).border = _BORDER

    # Service section
    svc_head = 8 + PART_ROWS + 1  # blank row between
    _section(ws, svc_head, SERVICE_MARKER, len(SERVICE_HEADERS))
    _headers(ws, svc_head + 1, SERVICE_HEADERS)
    for i in range(SERVICE_ROWS):
        row = svc_head + 2 + i
        for col in range(1, len(SERVICE_HEADERS) + 1):
            ws.cell(row=row, column=col).border = _BORDER

    ws.cell(row=svc_head + 2 + SERVICE_ROWS + 2, column=1,
            value="Part # in the Service table refers to the Item # in the Parts table above.").font = Font(
        italic=True, color="666666")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pdate(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _find_marker(ws, marker: str) -> int | None:
    for row in range(1, ws.max_row + 1):
        v = ws.cell(row=row, column=1).value
        if v and str(v).strip().upper() == marker:
            return row
    return None


def _cell(ws, row, col):
    v = ws.cell(row=row, column=col).value
    return str(v).strip() if v is not None and str(v).strip() != "" else None


def parse_import(data: bytes) -> dict:
    """Read a filled template into {job_code, title, parts[], lines[]}."""
    wb = load_workbook(io.BytesIO(data), data_only=True)
    ws = wb.active

    job_code = title = None
    for row in range(1, min(ws.max_row, 12) + 1):
        label = (str(ws.cell(row=row, column=1).value or "")).strip().lower()
        if label == "job code":
            job_code = _cell(ws, row, 2)
        elif label == "title":
            title = _cell(ws, row, 2)

    parts_head = _find_marker(ws, PARTS_MARKER)
    service_head = _find_marker(ws, SERVICE_MARKER)
    if parts_head is None or service_head is None:
        raise ValueError("This does not look like a Service Request template (missing section headers).")

    parts = []
    for row in range(parts_head + 2, service_head):  # skip section + header row
        part = _cell(ws, row, 3)
        if not part:
            continue
        item_num = _cell(ws, row, 1)
        qty = _cell(ws, row, 2)
        parts.append({
            "item_num": int(float(item_num)) if item_num and item_num.replace(".", "").isdigit() else None,
            "qty": int(float(qty)) if qty and qty.replace(".", "").isdigit() else 1,
            "part": part,
            "cabinet": _cell(ws, row, 4),
            "style": _cell(ws, row, 5),
            "color": _cell(ws, row, 6),
            "vendor": _cell(ws, row, 7),
            "order_number": _cell(ws, row, 8),
            "order_date": _pdate(ws.cell(row=row, column=9).value),
            "due_date": _pdate(ws.cell(row=row, column=10).value),
            "notes": _cell(ws, row, 11),
        })

    lines = []
    for row in range(service_head + 2, ws.max_row + 1):
        desc = _cell(ws, row, 3)
        if not desc:
            continue
        pnum = _cell(ws, row, 1)
        lines.append({
            "part_num": int(float(pnum)) if pnum and pnum.replace(".", "").isdigit() else None,
            "instruction": desc,
        })

    return {"job_code": job_code, "title": title, "parts": parts, "lines": lines}
