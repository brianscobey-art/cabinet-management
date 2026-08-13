"""Sales Order Cover Sheet as a fillable .xlsx — same layout as the web form.

Built to the "make-excel-template" rules: one narrow base column (2.2), every
field a merged span, borders across whole merges, live formulas for the totals,
and print setup that fits one portrait letter page.

`build_cover_workbook(sheet)` returns BytesIO; pass None for a blank form.
"""

import io
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.page import PageMargins
from openpyxl.utils import get_column_letter

GREEN = "125952"
BAND_TXT = "FFFFFF"
LABEL_FILL = "EAF2F0"
THIN = Side(style="thin", color="7F918D")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
MONEY = '"$"#,##0.00;;""'          # blank instead of $0.00
MONEY_HARD = '"$"#,##0.00'
PCT = '0.0%;;""'
COLS = 34                            # 34 x 2.2 ≈ 7.5in of printable width


def _cell(ws, row, col, span, value=None, *, bold=False, fill=None, align="left",
          wrap=False, fmt=None, size=10, color=None, border=True):
    """One merged field; returns the next free column."""
    if span > 1:
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + span - 1)
    c = ws.cell(row=row, column=col, value=value)
    c.font = Font(name="Calibri", size=size, bold=bold,
                  color=color or (BAND_TXT if fill == GREEN else "000000"))
    c.alignment = Alignment(horizontal=align, vertical="center", wrap_text=wrap)
    if fill:
        c.fill = PatternFill("solid", fgColor=fill)
    if fmt:
        c.number_format = fmt
    if border:
        for cc in range(col, col + span):
            ws.cell(row=row, column=cc).border = BORDER
    return col + span


def _band(ws, row, text, col=1, span=COLS):
    _cell(ws, row, col, span, text, bold=True, fill=GREEN, align="center", size=10.5)
    ws.row_dimensions[row].height = 19


def _pair(ws, row, col, label, value, lab_span=7, val_span=10, fmt=None):
    """Label cell + fillable value cell."""
    nxt = _cell(ws, row, col, lab_span, label, bold=True, fill=LABEL_FILL, size=9.5)
    return _cell(ws, row, nxt, val_span, value, fmt=fmt, size=9.5)


def build_cover_workbook(s: dict | None = None) -> io.BytesIO:
    s = s or {}
    pos = s.get("pos", [])
    products = [p for p in pos if p.get("kind") != "labor"]
    labor = [p for p in pos if p.get("kind") == "labor"]
    PROD_ROWS, LAB_ROWS = 8, 4          # fillable blanks when the sheet is empty

    wb = Workbook()
    ws = wb.active
    ws.title = "Sales Order Cover Sheet"
    for c in range(1, COLS + 1):
        ws.column_dimensions[get_column_letter(c)].width = 2.2

    r = 1
    ws.row_dimensions[r].height = 24
    _cell(ws, r, 1, 22, "SALES ORDER COVER SHEET", bold=True, size=15,
          color=GREEN, border=False)
    _cell(ws, r, 23, 12, s.get("job_code") or "", bold=True, size=12, align="right",
          border=False)
    r += 1
    ws.row_dimensions[r].height = 15
    _cell(ws, r, 1, 22, "Carter Kitchen & Bath", size=9.5, color="555555", border=False)
    _cell(ws, r, 23, 12, f"Printed {date.today():%m/%d/%y}", size=9, align="right",
          color="555555", border=False)
    r += 2

    # ---- three header blocks: Sale | Job Information | Customer ----
    top = r
    _band(ws, r, "Sale", 1, 11)
    _band(ws, r, "Job Information", 12, 11)
    _band(ws, r, "Customer", 23, 12)
    r += 1
    sale_rows = [
        ("Sale Date", s.get("sale_date")), ("Plan Type", s.get("plan_type")),
        ("Ashely's Code", s.get("customer_account")), ("G-Code", s.get("job_number")),
        ("I-Code", s.get("install_code")), ("Cab Job Code", s.get("job_code")),
        ("Scope", s.get("scope")),
    ]
    job_rows = [
        ("Name", s.get("ji_name")), ("Contact", s.get("ji_contact")),
        ("Address", s.get("ji_address")), ("City", s.get("ji_city")),
        ("State", s.get("ji_state")), ("Zip", s.get("ji_zip")),
        ("Phone", s.get("ji_phone")), ("Email", s.get("ji_email")),
    ]
    cust_rows = [
        ("Company", s.get("cu_company")), ("Name", s.get("cu_name")),
        ("Address", s.get("cu_address")), ("City", s.get("cu_city")),
        ("State", s.get("cu_state")), ("Zip", s.get("cu_zip")),
        ("Phone", s.get("cu_phone")), ("Email", s.get("cu_email")),
    ]
    for i in range(max(len(sale_rows), len(job_rows), len(cust_rows))):
        ws.row_dimensions[r + i].height = 16
        if i < len(sale_rows):
            _pair(ws, r + i, 1, sale_rows[i][0], sale_rows[i][1], 5, 6)
        if i < len(job_rows):
            _pair(ws, r + i, 12, job_rows[i][0], job_rows[i][1], 4, 7)
        if i < len(cust_rows):
            _pair(ws, r + i, 23, cust_rows[i][0], cust_rows[i][1], 4, 8)
    r += 8

    # ---- superintendent ----
    _band(ws, r, "Superintendent")
    r += 1
    ws.row_dimensions[r].height = 16
    _cell(ws, r, 1, 5, "Name", bold=True, fill=LABEL_FILL, size=9.5)
    _cell(ws, r, 6, 10, s.get("super_name"))
    _cell(ws, r, 16, 4, "Phone", bold=True, fill=LABEL_FILL, size=9.5)
    _cell(ws, r, 20, 7, s.get("super_phone"))
    _cell(ws, r, 27, 3, "Email", bold=True, fill=LABEL_FILL, size=9.5)
    _cell(ws, r, 30, 5, s.get("super_email"))
    r += 2

    def po_table(start, title, rows, count, c1, c2):
        _band(ws, start, title)
        hr = start + 1
        ws.row_dimensions[hr].height = 16
        col = 1
        for label, span, align in (("Job / PO Number", 7, "left"), ("Vendor", 8, "left"),
                                   ("Vendor Code", 5, "left"), ("Type", 5, "left"),
                                   (c1, 3, "right"), (c2, 3, "right"), ("Total", 3, "right")):
            col = _cell(ws, hr, col, span, label, bold=True, fill=GREEN, align=align, size=9)
        first = hr + 1
        for i in range(count):
            rr = first + i
            ws.row_dimensions[rr].height = 15
            p = rows[i] if i < len(rows) else {}
            po_num = p.get("po_number") or ""
            _cell(ws, rr, 1, 7, po_num, size=9.5)
            _cell(ws, rr, 8, 8, p.get("vendor"), size=9.5)
            _cell(ws, rr, 16, 5, p.get("vendor_code"), size=9.5)
            _cell(ws, rr, 21, 5, p.get("po_type"), size=9.5)
            _cell(ws, rr, 26, 3, float(p["amount1"]) if p.get("amount1") else None,
                  align="right", fmt=MONEY, size=9.5)
            _cell(ws, rr, 29, 3, float(p["amount2"]) if p.get("amount2") else None,
                  align="right", fmt=MONEY, size=9.5)
            a1, a2 = get_column_letter(26), get_column_letter(29)
            _cell(ws, rr, 32, 3, f"={a1}{rr}+{a2}{rr}", align="right", fmt=MONEY, size=9.5)
        last = first + count - 1
        tr = last + 1
        ws.row_dimensions[tr].height = 16
        _cell(ws, tr, 1, 31, f"{title} total", bold=True, fill=LABEL_FILL, align="right", size=9.5)
        col_t = get_column_letter(32)
        _cell(ws, tr, 32, 3, f"=SUM({col_t}{first}:{col_t}{last})", bold=True,
              align="right", fmt=MONEY_HARD, size=10)
        return tr

    prod_total_row = po_table(r, "PO's Needed — Products", products,
                              max(PROD_ROWS, len(products)), "Cost", "Freight")
    r = prod_total_row + 2
    lab_total_row = po_table(r, "PO's Needed — Labor", labor,
                             max(LAB_ROWS, len(labor)), "Assemble", "Install")
    r = lab_total_row + 2

    # ---- summary: cost | contract | margin ----
    _band(ws, r, "Cost Summary", 1, 13)
    _band(ws, r, "Contract", 14, 12)
    _band(ws, r, "Margin", 26, 9)
    hdr = r
    r += 1
    T = get_column_letter(32)
    mat, lab = f"{T}{prod_total_row}", f"{T}{lab_total_row}"
    tax_pct = float(s.get("tax_pct") or 9)
    rows_cost = [
        ("Total Materials", f"={mat}"),
        ("Total Labor", f"={lab}"),
        ("Total Tax", None),          # written below so we can put the % beside it
        ("Total COGS", None),
    ]
    for i, (label, formula) in enumerate(rows_cost):
        rr = r + i
        ws.row_dimensions[rr].height = 16
        _cell(ws, rr, 1, 8, label, bold=(i == 3), fill=LABEL_FILL, size=9.5)
        _cell(ws, rr, 9, 5, formula, align="right", fmt=MONEY_HARD, bold=(i == 3), size=9.5)
    tax_cell = f"{get_column_letter(9)}{r + 2}"
    pct_cell = f"{get_column_letter(9)}{r + 4}"
    ws.cell(row=r + 2, column=9).value = f"={mat}*{pct_cell}"
    ws.cell(row=r + 3, column=9).value = (
        f"={get_column_letter(9)}{r}+{get_column_letter(9)}{r + 1}+{tax_cell}")
    # tax rate lives just under the cost block so it can be edited
    rr = r + 4
    ws.row_dimensions[rr].height = 16
    _cell(ws, rr, 1, 8, "Tax rate (on materials)", fill=LABEL_FILL, size=9)
    _cell(ws, rr, 9, 5, tax_pct / 100, align="right", fmt="0.0%", size=9.5)

    contract = [("Cabinets", s.get("sale_cabinets")), ("Countertops", s.get("sale_countertops")),
                ("Other", s.get("sale_other")), ("Total Sale", None)]
    for i, (label, val) in enumerate(contract):
        rr = r + i
        _cell(ws, rr, 14, 7, label, bold=(i == 3), fill=LABEL_FILL, size=9.5)
        if i < 3:
            v = float(val) if val not in (None, "", 0, "0") and float(val) else None
            _cell(ws, rr, 21, 5, v, align="right", fmt=MONEY, size=9.5)
        else:
            c21 = get_column_letter(21)
            _cell(ws, rr, 21, 5, f"=SUM({c21}{r}:{c21}{r + 2})", bold=True,
                  align="right", fmt=MONEY_HARD, size=9.5)
    sale_cell = f"{get_column_letter(21)}{r + 3}"
    cogs_cell = f"{get_column_letter(9)}{r + 3}"
    for i, label in enumerate(("Dollars", "Percent")):
        rr = r + i
        _cell(ws, rr, 26, 5, label, fill=LABEL_FILL, size=9.5)
        if i == 0:
            _cell(ws, rr, 31, 4, f"={sale_cell}-{cogs_cell}", align="right",
                  fmt=MONEY_HARD, bold=True, size=9.5)
        else:
            _cell(ws, rr, 31, 4, f"=IF({sale_cell}=0,\"\",({sale_cell}-{cogs_cell})/{sale_cell})",
                  align="right", fmt=PCT, bold=True, size=9.5)
    r += 5

    _band(ws, r, "Notes")
    r += 1
    ws.row_dimensions[r].height = 30
    _cell(ws, r, 1, COLS, s.get("notes"), wrap=True, align="left", size=9.5)
    last_row = r

    # ---- print setup: one portrait letter page ----
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_LETTER
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:{get_column_letter(COLS)}{last_row}"
    ws.page_margins = PageMargins(left=0.3, right=0.3, top=0.4, bottom=0.3)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
