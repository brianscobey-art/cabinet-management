"""Import a 2020 Design quote export (.xls) into a priced job.

The 2020 export is a legacy BIFF .xls print layout: item rows carry
line # (col 0, "*" = non-plan item, "n.m" = accessory sub-line), qty (col 3),
SKU (col 4), and EXTENDED list price (col 27). Sections are labeled rows
("Cabinets", "Charges", "Accessories"); subtotal/net rows are skipped.
List each = extended / qty. Pricing (multiplier, freight, tax, margin) is
applied by the platform's cost engine, not taken from the file.
"""

import re
from decimal import Decimal, InvalidOperation

import xlrd

SECTION_NAMES = {"Cabinets", "Charges", "Accessories", "Mouldings"}
SKIP_PREFIXES = (
    "print date", "quote summary", "catalog", "#", "qty",
)
TOTAL_MARKERS = ("subtotal", "net total", "total:", "premiums total", "charges total")


def _dec(v) -> Decimal | None:
    s = str(v).strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_2020_xls(data: bytes) -> dict:
    wb = xlrd.open_workbook(file_contents=data)
    ws = wb.sheet_by_index(0)

    items: list[dict] = []
    net_total = None
    file_name = None
    section = "Cabinets"

    for r in range(ws.nrows):
        cells = [str(ws.cell_value(r, c)).strip() for c in range(ws.ncols)]
        first = cells[0]

        # design file name (DESIGN DETAILS block) — spans a few rows, take the first
        if "File name:" in cells[2:4] and file_name is None:
            joined = next((c for c in cells[4:] if c), "")
            file_name = joined

        if first in SECTION_NAMES:
            section = first
            continue

        # totals — capture the quote net, skip the rest
        line_text = " ".join(cells).lower()
        if any(m in line_text for m in TOTAL_MARKERS):
            if "quote net total" in line_text or "quote total" in line_text:
                for c in reversed(cells):
                    if val := _dec(c):
                        net_total = val
                        break
            continue

        # item rows: col0 like "12", "*67", "12.1"; qty col3; sku col4; ext price col27
        m = re.fullmatch(r"\*?\d+(\.\d+)?", first)
        if not m:
            continue
        qty = _dec(cells[3])
        sku = cells[4]
        ext = _dec(cells[27]) if ws.ncols > 27 else None
        if not sku or qty is None or qty <= 0 or ext is None:
            continue
        items.append({
            "line_no": first,
            "section": section,
            "sku": sku,
            "qty": int(qty),
            "ext_list": ext,
            "list_each": (ext / int(qty)).quantize(Decimal("0.01")) if qty else ext,
            "non_plan": first.startswith("*"),
            "sub_item": "." in first,
        })

    return {
        "items": items,
        "net_total": net_total,
        "file_name": file_name,
        "list_sum": sum((i["ext_list"] for i in items), Decimal("0")),
    }


# Item row in the 2020 quote PDF print: "12 1 W3036 <desc...> 647.00"
# (line #, qty, SKU, optional description, extended list price at end).
_PDF_ITEM = re.compile(
    r"^(?P<line>\*?\d+(?:\.\d+)?)\s+(?P<qty>\d+)\s+(?P<sku>[A-Za-z0-9][\w./-]*)"
    r"(?:\s+.*?)?\s+(?P<price>[\d,]+\.\d{2})\s*$"
)


def parse_2020_pdf(data: bytes) -> dict:
    """Same quote report as the .xls export, printed to PDF."""
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    items: list[dict] = []
    net_total = None
    section = "Cabinets"

    for page in reader.pages:
        for raw in (page.extract_text() or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if line in SECTION_NAMES:
                section = line
                continue
            low = line.lower()
            if any(m in low for m in TOTAL_MARKERS):
                if "quote net total" in low or "quote total" in low:
                    nums = re.findall(r"[\d,]+\.\d{2}", line)
                    if nums:
                        net_total = _dec(nums[-1])
                continue
            m = _PDF_ITEM.match(line)
            if not m:
                continue
            qty = int(m.group("qty"))
            ext = _dec(m.group("price"))
            if qty <= 0 or ext is None:
                continue
            first = m.group("line")
            items.append({
                "line_no": first,
                "section": section,
                "sku": m.group("sku"),
                "qty": qty,
                "ext_list": ext,
                "list_each": (ext / qty).quantize(Decimal("0.01")),
                "non_plan": first.startswith("*"),
                "sub_item": "." in first,
            })

    return {
        "items": items,
        "net_total": net_total,
        "file_name": None,
        "list_sum": sum((i["ext_list"] for i in items), Decimal("0")),
    }


def combine_items(items: list[dict]) -> list[dict]:
    """Merge like items (same section + SKU + list each) into one row, qty summed."""
    merged: dict[tuple, dict] = {}
    for it in items:
        key = (it["section"], it["sku"].upper(), it["list_each"])
        hit = merged.get(key)
        if hit:
            hit["qty"] += it["qty"]
            hit["ext_list"] += it["ext_list"]
        else:
            merged[key] = {**it}
    return list(merged.values())
