"""Branded Service Request Excel template (matches the app's service report) plus a
parser for round-tripping a filled sheet back into the app.

One landscape page: Carter logo + "Carter Kitchen and Bath", a condensed
PROJECT/ADDRESS/LOT + JOB CODE/DATE/STATUS block, a combined Cabinet
Specifications & Hardware block, then Parts Needed and Service Needed (3 lines
each) and a one-line signature row. Only the Job Code and the Parts / Service
tables are read on import.
"""

import io
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.properties import PageSetupProperties

PARTS_MARKER = "PARTS NEEDED"
SERVICE_MARKER = "SERVICE NEEDED"
PART_ROWS = 3
SERVICE_ROWS = 3
SPEC_ROWS = 3

CARTER_GREEN = "125952"
NCOLS = 11
# balanced so the Parts row AND the side-by-side Cabinet/Hardware read well
COL_WIDTHS = [12, 12, 16, 12, 12, 12, 13, 12, 13, 13, 14]

PART_HEADERS = ["Item #", "Qty", "Part", "Cabinet", "Style", "Color", "Vendor",
                "Order #", "Order Date", "Due Date", "Notes"]
# combined block: cabinet (cols 1-6) beside hardware (cols 7-11)
COMBO_HEADERS = ["Room / Zone", "Vendor", "Series", "Door Style", "Color", "Species",
                 "Room", "Hardware Type", "Vendor", "Item", "Qty"]
SERVICE_SPEC = [("Part #", 1), ("Cabinet", 1), ("Description of Work", 7), ("Date", 1), ("Tech", 1)]

_thin = Side(style="thin", color="000000")
_BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
_LABEL_FONT = Font(bold=True, size=9)
_SECTION_FILL = PatternFill("solid", fgColor=CARTER_GREEN)
_HEADER_FILL = PatternFill("solid", fgColor="E4EFEC")
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_LEFT = Alignment(horizontal="left", vertical="center")


def _box(ws, row, col, span=1, value=None, *, kind="cell", center=False):
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
    elif center:
        cell.alignment = _CENTER
    return cell


def build_blank_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Service Request"
    ws.sheet_view.showGridLines = False
    for i, w in enumerate(COL_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # --- title (left) + logo & brand (upper right) ------------------------
    ws.merge_cells("A1:D2")
    t = ws.cell(row=1, column=1, value="SERVICE REQUEST")
    t.font = Font(size=17, bold=True, color=CARTER_GREEN)
    t.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 20
    ws.row_dimensions[2].height = 20
    logo = Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "carter-logo.png"
    if logo.exists():
        img = XLImage(str(logo))
        img.height = 40
        img.width = int(40 * 946 / 228)
        ws.add_image(img, "H1")
    ws.merge_cells("G3:K3")
    b = ws.cell(row=3, column=7, value="Carter Kitchen and Bath")
    b.font = Font(size=11, bold=True, color=CARTER_GREEN)
    b.alignment = Alignment(horizontal="right", vertical="center")

    # --- condensed info: 2 rows, left aligned ----------------------------
    def info_row(r, trips):
        col = 1
        for label, span in trips:
            lc = _box(ws, r, col, 1, label)
            lc.font = Font(bold=True, size=9, color=CARTER_GREEN)
            _box(ws, r, col + 1, span)
            col += 1 + span
    info_row(5, [("PROJECT", 3), ("ADDRESS", 3), ("LOT", 2)])   # 4+4+3 = 11
    info_row(6, [("JOB CODE", 3), ("DATE", 3), ("STATUS", 2)])

    r = 8

    def bar(title):
        nonlocal r
        _box(ws, r, 1, NCOLS, title, kind="section")
        r += 1

    def headers(labels):
        nonlocal r
        for i, h in enumerate(labels, start=1):
            _box(ws, r, i, 1, h, kind="header")
        r += 1

    def blank_rows(n, *, center_cols=(), date_cols=()):
        nonlocal r
        for _ in range(n):
            for i in range(1, NCOLS + 1):
                cell = _box(ws, r, i, center=i in center_cols)
                if i in date_cols:
                    cell.number_format = "m/d/yy"
            r += 1

    # combined Cabinet Specifications & Hardware
    bar("CABINET SPECIFICATIONS & HARDWARE")
    headers(COMBO_HEADERS)
    blank_rows(SPEC_ROWS, center_cols={11})

    # parts (3 lines) — center Item#/Qty/Order#/dates, m/d/yy on the dates
    bar(PARTS_MARKER)
    headers(PART_HEADERS)
    blank_rows(PART_ROWS, center_cols={1, 2, 8, 9, 10}, date_cols={9, 10})

    # service (3 lines) — Part# / Cabinet / Description / Date / Tech
    bar(SERVICE_MARKER)
    col = 1
    for label, span in SERVICE_SPEC:
        _box(ws, r, col, span, label, kind="header")
        col += span
    r += 1
    for _ in range(SERVICE_ROWS):
        col = 1
        for _lbl, span in SERVICE_SPEC:
            cell = _box(ws, r, col, span, center=col in (1, 10))
            if col == 10:
                cell.number_format = "m/d/yy"
            col += span
        r += 1

    # --- signatures: all on one line -------------------------------------
    r += 1
    sig_specs = [("Service Tech — Signature", 3), ("Date", 2),
                 ("Customer — Signature", 4), ("Date", 2)]
    col = 1
    for _lbl, span in sig_specs:
        ws.merge_cells(start_row=r, start_column=col, end_row=r, end_column=col + span - 1)
        for c in range(col, col + span):
            ws.cell(row=r, column=c).border = Border(bottom=_thin)
        col += span
    r += 1
    col = 1
    for lbl, span in sig_specs:
        c = ws.cell(row=r, column=col, value=lbl)
        c.font = Font(size=8, color="555555")
        col += span
    r += 2
    ws.cell(row=r, column=1,
            value="Fill in the Job Code and the Parts / Service tables, save, and import into "
                  "Carter Kitchen and Bath. Part # in Service refers to the Item # in Parts.").font = Font(
        italic=True, size=8, color="888888")

    # print landscape, one page wide, narrow margins
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_margins = PageMargins(left=0.25, right=0.25, top=0.3, bottom=0.3, header=0.15, footer=0.15)
    ws.print_area = f"A1:{get_column_letter(NCOLS)}{r}"

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


def _cell(ws, row, col):
    v = ws.cell(row=row, column=col).value
    return str(v).strip() if v is not None and str(v).strip() != "" else None


def _label_value(ws, label: str):
    for row in range(1, min(ws.max_row, 15) + 1):
        for col in range(1, min(ws.max_column, NCOLS) + 1):
            v = ws.cell(row=row, column=col).value
            if v and str(v).strip().lower() == label:
                return _cell(ws, row, col + 1)
    return None


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
    for row in range(parts_head + 2, service_head):
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
