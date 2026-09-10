"""The builder's own portal — DR Horton's VendorSuite and Century's SupplyPro.

Why this is a separate source and not already covered. Both feeds are imported
into CabinetTron already, but deliberately do NOT overwrite scheduling on an
existing job: app.feeds keeps install_date app-managed and only fills
measure_date when the app has none. The builder's own schedule survives as
prose inside a "VS:" note. So the portal's view of when cabinets are measured,
delivered and punched is not available structurally anywhere -- which is
exactly what a report about disagreeing dates needs.

It is also the most authoritative of the four: VendorSuite IS DR Horton's
system and SupplyPro IS Century's. Where Smartsheet is somebody's transcription
of a builder date, this is the builder date.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

from app.smartsheet.scopes import as_date

# "27 / - / 3B" -> lot 27. The block and phase segments are not part of the lot
# and vary in whether they are filled at all.
_PLAT_LOT = re.compile(r"^\s*([A-Za-z0-9-]+)")


def _open(path: Path):
    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(path, read_only=True, data_only=True)


def _table(ws, header_row: int) -> list[dict]:
    rows = ws.iter_rows(min_row=header_row, values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows, ())]
    out = []
    for values in rows:
        if not any(v is not None for v in values):
            continue
        out.append({h: values[i] for i, h in enumerate(header)
                    if h and i < len(values)})
    return out


def newest(folder: str | Path, pattern: str) -> Path | None:
    """Newest matching export, by the date in the NAME where there is one.

    Same reasoning as the Smartsheet reader: these files also travel over R2 and
    arrive stamped with their download time, so mtime alone can prefer an older
    export. Revision suffixes (".R.1", ".R2") sort after the plain file for the
    same date, which is what we want -- a revision supersedes it.
    """
    folder = Path(folder)
    if not folder.is_dir():
        return None
    dated = re.compile(r"(\d{2})(\d{2})(\d{2})")

    def key(p: Path):
        m = dated.search(p.name)
        stamp = f"20{m.group(3)}{m.group(1)}{m.group(2)}" if m else ""
        return (stamp, p.name, p.stat().st_mtime)

    files = [f for f in folder.glob(pattern) if not f.name.startswith("~")]
    return max(files, key=key) if files else None


def read_vendorsuite(path: Path) -> list[dict]:
    """DR Horton cabinet jobs: subdivision, lot, PO and the three cabinet dates."""
    wb = _open(path)
    try:
        tab = next((n for n in wb.sheetnames
                    if n.startswith("DRH Cabinets Combined")), None)
        if tab is None:
            return []
        rows = _table(wb[tab], 2)
    finally:
        wb.close()

    out = []
    for r in rows:
        plat = _PLAT_LOT.match(str(r.get("Plat (Lot/Block/Phase)") or ""))
        out.append({
            "source": "VendorSuite",
            "subdivision": r.get("Project"),
            "lot": plat.group(1) if plat else None,
            "po_number": r.get("PO Number"),
            "po_amount": r.get("PO Amount"),
            "po_status": r.get("PO Status"),
            "measure": as_date(r.get("Cabinet Measure/Order")),
            "install": as_date(r.get("Cabinet Install")),
            "punch": as_date(r.get("Cabinet Trim/Punch")),
        })
    return out


def read_supplypro(path: Path) -> list[dict]:
    """Century cabinet jobs. Two sheets carry dates and the PO sheet wins:
    "Cabinet POs" is per purchase order and carries the committed dates, while
    "Cabinet Jobs" holds the earlier request dates. Job rows fill the gaps."""
    wb = _open(path)
    try:
        pos = _table(wb["Cabinet POs"], 2) if "Cabinet POs" in wb.sheetnames else []
        jobs = _table(wb["Cabinet Jobs"], 2) if "Cabinet Jobs" in wb.sheetnames else []
    finally:
        wb.close()

    merged: dict[tuple, dict] = {}
    for r in jobs:
        key = (str(r.get("Subdivision") or ""), str(r.get("Lot") or ""))
        merged[key] = {
            "source": "SupplyPro",
            "subdivision": r.get("Subdivision"),
            "lot": r.get("Lot"),
            "po_number": None, "po_amount": None, "po_status": None,
            "measure": as_date(r.get("Measure Cabinets")),
            "install": as_date(r.get("Deliver Cabinets")),
            "punch": None,
        }
    for r in pos:
        key = (str(r.get("Subdivision") or ""), str(r.get("Lot") or ""))
        rec = merged.setdefault(key, {
            "source": "SupplyPro", "subdivision": r.get("Subdivision"),
            "lot": r.get("Lot"), "measure": None, "install": None, "punch": None,
        })
        rec.update({
            "po_number": r.get("PO Number"),
            "po_amount": r.get("Total PO Amount"),
            "po_status": r.get("Order Status"),
            "measure": as_date(r.get("Measure Date")) or rec.get("measure"),
            "install": as_date(r.get("Deliver / Install Date")) or rec.get("install"),
        })
    return list(merged.values())


def _name_stamp(path: Path) -> tuple:
    """Sortable key from the MMDDYY in a filename, name as the tiebreak so a
    revision (".R.1") sorts after the plain file for the same date."""
    m = re.search(r"(\d{2})(\d{2})(\d{2})", path.name)
    return (f"20{m.group(3)}{m.group(1)}{m.group(2)}" if m else "", path.name)


def load(vendorsuite_dir, *century_dirs) -> tuple[list[dict], dict]:
    """Both portals, plus a note of which files were read (shown on the report,
    so nobody has to guess how current the portal column is)."""
    meta: dict[str, str | None] = {}
    rows: list[dict] = []

    vs = newest(vendorsuite_dir, "DRH_Cabinets_Combined_*.xlsx")
    meta["vendorsuite"] = vs.name if vs else None
    if vs:
        try:
            rows += read_vendorsuite(vs)
        except (PermissionError, OSError, KeyError) as exc:
            meta["vendorsuite"] = f"{vs.name} (unreadable: {type(exc).__name__})"

    # Brian keeps SupplyPro exports in two folders. Take whichever holds the
    # newest export rather than assuming they stay in step -- they hold the same
    # file today, and that is exactly the kind of thing that quietly stops being
    # true.
    found = [f for d in century_dirs
             if (f := newest(d, "Century Cabinet Jobs - SupplyPro*.xlsx"))]
    cc = max(found, key=_name_stamp) if found else None
    meta["supplypro"] = cc.name if cc else None
    if cc:
        try:
            rows += read_supplypro(cc)
        except (PermissionError, OSError, KeyError) as exc:
            meta["supplypro"] = f"{cc.name} (unreadable: {type(exc).__name__})"

    return rows, meta
