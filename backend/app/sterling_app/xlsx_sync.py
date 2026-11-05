"""Two-way link between Sterling's database and its Excel workbook (shared mode).

Brian 11/5/26: move Sterling's pricing into the shared database, "but link both
ways". The database is the source of truth; the workbook stays a working copy
that can be edited in Excel:

* App -> workbook: every committed change rewrites the workbook (xlsx_store),
  and `remember()` records what each row looked like when it was written.
* Workbook -> app: `merge()` reads the workbook and compares each row three
  ways (workbook, database, last sync):
    - only Excel changed it   -> Excel's version goes into the database
    - only the app changed it -> the app's version stays (next save writes it)
    - both changed it         -> the app's version stays and the row is listed
                                 as a conflict, with Excel's values, to fix by hand
  New and deleted rows follow the same rule.
* `verify()` checks the database against the workbook line by line, the double
  check run after the first move and before the shared database goes live.
"""

import enum
import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from openpyxl import load_workbook

from app.sterling_app.models import Setting, SyncRow


def _norm(v):
    """One spelling for a value whether it came from the database or the workbook."""
    if v is None:
        return None
    if isinstance(v, enum.Enum):
        v = v.value
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (Decimal, float, int)):
        d = Decimal(str(v)).normalize()
        return format(d, "f")
    if isinstance(v, datetime):
        if v.tzinfo:
            v = v.astimezone(UTC).replace(tzinfo=None)
        if (v.hour, v.minute, v.second, v.microsecond) == (0, 0, 0, 0):
            return v.date().isoformat()
        return v.replace(microsecond=0).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return str(v)


def _key_attr(model) -> str:
    return "key" if model is Setting else "id"


def _digest(values: dict) -> str:
    return hashlib.sha1(json.dumps(values, sort_keys=True).encode()).hexdigest()


def _db_values(obj, cols) -> dict:
    return {attr: _norm(getattr(obj, attr)) for _, attr in cols}


def _sheets():
    from app.sterling_app.xlsx_store import SHEETS

    return SHEETS


def remember(db, workbook) -> int:
    """Record every row exactly as it was written to `workbook` (the in-memory
    Workbook just saved), so the record matches the file even if someone
    commits a change while the save is running. Caller commits."""
    from app.sterling_app.xlsx_store import _parse

    db.query(SyncRow).delete()
    n = 0
    for sheet, _, model, cols in _sheets():
        if sheet not in workbook.sheetnames:
            continue
        rows = workbook[sheet].iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            continue
        by_header = {h: attr for h, attr in cols}
        attrs = [by_header.get(h) for h in header]
        key = _key_attr(model)
        for row in rows:
            data = {a: _parse(a, v) for a, v in zip(attrs, row) if a is not None}
            if data.get(key) in (None, ""):
                continue
            db.add(SyncRow(sheet=sheet, row_key=str(data[key]), digest=_digest(_wb_values(data, cols))))
            n += 1
    return n


def _read_workbook(path) -> dict[str, dict[str, dict]]:
    """{sheet: {row key: {attr: parsed value}}} from the workbook."""
    from app.sterling_app.xlsx_store import _parse

    wb = load_workbook(path, read_only=True, data_only=True)
    out: dict[str, dict[str, dict]] = {}
    try:
        for sheet, _, model, cols in _sheets():
            if sheet not in wb.sheetnames:
                continue  # a missing tab tells us nothing; never read it as "delete all"
            rows = wb[sheet].iter_rows(values_only=True)
            header = next(rows, None)
            if header is None:
                continue
            rows_out: dict[str, dict] = {}
            out[sheet] = rows_out
            by_header = {h: attr for h, attr in cols}
            attrs = [by_header.get(str(h).strip() if h else "") for h in header]
            key = _key_attr(model)
            for row in rows:
                data = {}
                for attr, v in zip(attrs, row):
                    if attr is not None:
                        data[attr] = _parse(attr, v)
                if data.get(key) in (None, ""):
                    continue
                rows_out[str(data[key])] = data
    finally:
        wb.close()
    return out


def _wb_values(data: dict, cols) -> dict:
    return {attr: _norm(data.get(attr)) for _, attr in cols}


def _apply(obj, data: dict, model) -> None:
    for attr, value in data.items():
        col = model.__table__.columns.get(attr)
        if value is None and col is not None and not col.nullable:
            continue  # leave a required field alone rather than blank it
        setattr(obj, attr, value)


def merge(db, path) -> dict:
    """Pull workbook edits into the database (see module doc). Caller commits."""
    wb = _read_workbook(path)
    base = {(r.sheet, r.row_key): r.digest for r in db.query(SyncRow).all()}
    result = {"from_excel": 0, "added_from_excel": 0, "deleted_from_excel": 0, "kept_app": 0,
              "conflicts": [], "skipped_sheets": []}
    deletes = []
    for sheet, _, model, cols in _sheets():
        key = _key_attr(model)
        in_db = {str(getattr(o, key)): o for o in db.query(model).all()}
        if sheet not in wb:
            if in_db:
                result["skipped_sheets"].append(sheet)  # tab missing: leave the table alone
            continue
        in_wb = wb[sheet]
        if not in_wb and in_db:
            result["skipped_sheets"].append(sheet)  # emptied tab: too big to apply blind
            continue
        for k in sorted(set(in_db) | set(in_wb) | {rk for (s, rk) in base if s == sheet}):
            obj, data, was = in_db.get(k), in_wb.get(k), base.get((sheet, k))
            dh = _digest(_db_values(obj, cols)) if obj is not None else None
            wh = _digest(_wb_values(data, cols)) if data is not None else None
            if dh == wh:
                continue
            excel_changed, app_changed = wh != was, dh != was
            if excel_changed and not app_changed:
                if data is None:
                    deletes.append((model, obj))
                elif obj is None:
                    clean = {a: v for a, v in data.items() if v is not None}
                    db.add(model(**clean))
                    result["added_from_excel"] += 1
                else:
                    _apply(obj, data, model)
                    result["from_excel"] += 1
            elif app_changed and not excel_changed:
                result["kept_app"] += 1
            else:
                result["conflicts"].append({
                    "sheet": sheet, "row": k,
                    "excel": None if data is None else {a: _norm(v) for a, v in data.items()},
                    "app": None if obj is None else _db_values(obj, cols),
                })
        db.flush()
    # Children before parents, the reverse of the sheet order.
    order = {m: i for i, (_, _, m, _) in enumerate(_sheets())}
    for model, obj in sorted(deletes, key=lambda t: -order[t[0]]):
        db.delete(obj)
        result["deleted_from_excel"] += 1
    db.flush()
    return result


def verify(db, path) -> dict:
    """Line-by-line check that the database and the workbook hold the same rows."""
    wb = _read_workbook(path)
    diffs = []
    checked = 0
    for sheet, _, model, cols in _sheets():
        key = _key_attr(model)
        in_db = {str(getattr(o, key)): o for o in db.query(model).all()}
        if sheet not in wb:
            if in_db:
                diffs.append({"sheet": sheet, "missing_tab": True})
            continue
        in_wb = wb[sheet]
        for k in sorted(set(in_db) | set(in_wb)):
            checked += 1
            obj, data = in_db.get(k), in_wb.get(k)
            if obj is None or data is None:
                diffs.append({"sheet": sheet, "row": k, "only_in": "workbook" if obj is None else "database"})
                continue
            a, b = _db_values(obj, cols), _wb_values(data, cols)
            fields = [f for f in a if a[f] != b[f]]
            if fields:
                diffs.append({"sheet": sheet, "row": k, "fields": {f: {"database": a[f], "workbook": b[f]} for f in fields}})
    return {"rows_checked": checked, "differences": diffs, "match": not diffs}
