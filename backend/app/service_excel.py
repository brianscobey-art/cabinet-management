"""Branded Service Request Excel template (matches the app's printed form) plus a
parser for round-tripping a filled sheet back into the app.

The layout mirrors the on-screen / printed service report: Carter logo + title,
a PROJECT / ADDRESS / LOT / JOB CODE info grid, then Cabinet Specifications,
Hardware, Parts Needed, Service Needed sections and signature lines. Only the
Job Code and the Parts / Service tables are read on import.
"""

import io
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

PARTS_MARKER = "PARTS NEEDED"
SERVICE_MARKER = "SERVICE NEEDED"
PART_ROWS = 15
SERVICE_ROWS = 12

# Parts table columns (must match the on-screen / print Parts Needed table)
PART_HEADERS = ["Item #", "Qty", "Part", "Cabinet", "Style", "Color", "Vendor",
                "Order #", "Order Date", "Due Date", "Notes"]
PART_WIDTHS = [7, 5, 20, 12, 13, 13, 15, 11, 12, 12, 22]
NCOLS = len(PART_HEADERS)  # 11 — the grid every section spans

# (label, span) header specs for the narrower sections, summing to NCOLS
CABINET_SPEC = [("Room / Zone", 2), ("Vendor", 2), ("Series", 2), ("Door Style", 2),
                ("Color", 2), ("Species", 1)]
HARDWARE_SPEC = [("Room", 3), ("Type", 2), ("Vendor", 2), ("Item", 3), ("Qty", 1)]
SERVICE_SPEC = [("Part #", 1), ("Cabinet", 1), ("Description of Work", 7), ("Tech", 1), ("Date", 1)]

_thin = Side(style="thin", color="000000")
_BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
_LABEL_FONT = Font(bold=True, size=9)
_SECTION_FILL = PatternFill("solid", fgColor="4A4A4A")
_HEADER_FILL = PatternFill("solid", fgColor="EEEEEE")
_LABEL_FILL = PatternFill("solid", fgColor="EEEEEE")
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_LEFT = Alignment(horizontal="left", vertical="center")


def _box(ws, row, col, span=1, value=None, *, kind="cell", center=False):
    """Write a (possibly merged) bordered cell. kind: cell|header|section|label."""
    if span > 1:
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + span - 1)
    cell = ws.cell(row=row, column=col, value=value)
    for c in range(col, col + span):
        ws.cell(row=row, column=c).border = _BORDER
    if kind == "section":
        cell.fill = _SECTION_FILL
        cell.font = Font(color="FFFFFF", bold=True, size=10)
        cell.alignment = _LEFT
    elif kind == "header":
        cell.fill = _HEADER_FILL
        cell.font = _LABEL_FONT
        cell.alignment = _CENTER
    elif kind == "label":
        cell.fill = _LABEL_FILL
        cell.font = _LABEL_FONT
        cell.alignment = _LEFT
    elif center:
        cell.alignment = _CENTER
    return cell


def _spec_headers(ws, row, spec):
    col = 1
    for label, span in spec:
        _box(ws, row, col, span, label, kind="header")
        col += span


def _spec_blanks(ws, start, n, spec):
    for i in range(n):
        row = start + i
        col = 1
        for _, span in spec:
            _box(ws, row, col, span)
            col += span


def build_blank_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Service Request"
    ws.sheet_view.showGridLines = False
    for i, w in enumerate(PART_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # --- title + logo -----------------------------------------------------
    ws.merge_cells("A1:D2")
    t = ws.cell(row=1, column=1, value="SERVICE REQUEST")
    t.font = Font(size=18, bold=True)
    t.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 22
    logo = Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "carter-logo.png"
    if logo.exists():
        img = XLImage(str(logo))
        img.height = 46
        img.width = int(46 * 946 / 228)  # keep aspect (logo is 946x228)
        ws.add_image(img, f"{get_column_letter(NCOLS - 2)}1")

    # --- info grid: label | value(4) | label | value(5) -------------------
    info = [("PROJECT", "DATE"), ("ADDRESS", "JOB CODE"), ("LOT", "STATUS")]
    r = 4
    for left, right in info:
        _box(ws, r, 1, 1, left, kind="label")
        _box(ws, r, 2, 4)  # left value
        _box(ws, r, 6, 1, right, kind="label")
        _box(ws, r, 7, 5)  # right value
        r += 1

    def section(title, spec, blanks, *, marker=False):
        nonlocal r
        r += 1
        _box(ws, r, 1, NCOLS, title, kind="section")
        r += 1
        if spec == "PARTS":
            for i, h in enumerate(PART_HEADERS, start=1):
                _box(ws, r, i, 1, h, kind="header")
            r += 1
            for _ in range(blanks):
                for i in range(1, NCOLS + 1):
                    _box(ws, r, i)
                r += 1
        else:
            _spec_headers(ws, r, spec)
            r += 1
            _spec_blanks(ws, r, blanks, spec)
            r += blanks

    section("CABINET SPECIFICATIONS", CABINET_SPEC, 3)
    section("HARDWARE", HARDWARE_SPEC, 3)
    section(PARTS_MARKER, "PARTS", PART_ROWS)
    section(SERVICE_MARKER, SERVICE_SPEC, SERVICE_ROWS)

    # --- signatures -------------------------------------------------------
    r += 1
    for who in ("SERVICE TECH — SIGNATURE", "CUSTOMER — SIGNATURE (WORK COMPLETED)"):
        sig = ws.cell(row=r, column=1)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
        for c in range(1, 9):
            ws.cell(row=r, column=c).border = Border(bottom=_thin)
        ws.merge_cells(start_row=r, start_column=9, end_row=r, end_column=NCOLS)
        for c in range(9, NCOLS + 1):
            ws.cell(row=r, column=c).border = Border(bottom=_thin)
        r += 1
        ws.cell(row=r, column=1, value=who).font = Font(size=8, color="555555")
        ws.cell(row=r, column=9, value="DATE").font = Font(size=8, color="555555")
        r += 2

    ws.cell(row=r + 1, column=1,
            value="Fill in the Job Code and the Parts / Service tables, save, and import into "
                  "Carter Kitchen and Bath. Part # in Service refers to the Item # in Parts.").font = Font(
        italic=True, size=8, color="888888")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

def _find_marker(ws, marker: str) -> int | None:
    for row in range(1, ws.max_row + 1):
        v = ws.cell(row=row, column=1).value
        if v and str(v).strip().upper() == marker:
            return row
    return None


def _label_value(ws, label: str):
    """Find a cell whose text == label (any column, near the top) and read its right neighbour."""
    for row in range(1, min(ws.max_row, 15) + 1):
        for col in range(1, min(ws.max_column, NCOLS) + 1):
            v = ws.cell(row=row, column=col).value
            if v and str(v).strip().lower() == label:
                return _cell(ws, row, col + 1)
    return None


def _cell(ws, row, col):
    v = ws.cell(row=row, column=col).value
    return str(v).strip() if v is not None and str(v).strip() != "" else None


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


def _int(s, default=None):
    return int(float(s)) if s and str(s).replace(".", "").isdigit() else default


def parse_import(data: bytes) -> dict:
    """Read a filled template into {job_code, title, parts[], lines[]}."""
    wb = load_workbook(io.BytesIO(data), data_only=True)
    ws = wb.active

    job_code = _label_value(ws, "job code")
    title = _label_value(ws, "title")

    parts_head = _find_marker(ws, PARTS_MARKER)
    service_head = _find_marker(ws, SERVICE_MARKER)
    if parts_head is None or service_head is None:
        raise ValueError("This does not look like a Service Request template (missing section headers).")

    parts = []
    for row in range(parts_head + 2, service_head):  # skip section + header row
        part = _cell(ws, row, 3)
        if not part:
            continue
        parts.append({
            "item_num": _int(_cell(ws, row, 1)),
            "qty": _int(_cell(ws, row, 2), 1) or 1,
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
        lines.append({"part_num": _int(_cell(ws, row, 1)), "instruction": desc})

    return {"job_code": job_code, "title": title, "parts": parts, "lines": lines}
