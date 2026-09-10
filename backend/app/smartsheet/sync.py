"""Pull the Tract Builder Management sheets into CabinetTron, once a night.

Two sources, same destination. When SMARTSHEET_API_TOKEN is set the sheets come
straight off the API; without one it reads .xlsx exports from a watched folder,
so the report works today and switches over with no code change.

Read-only in both directions. There is no writer here and there must not be:
nothing goes back to Smartsheet without Brian saying so per change.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import SmartsheetHistory, SmartsheetRow
from app.smartsheet.match import norm_lot, norm_sub
from app.smartsheet.reader import SHEETS, rows_from_api, rows_from_xlsx
from app.smartsheet.scopes import read_house

# Fields whose history we keep. Everything else is stored in the row JSON but
# not tracked over time -- 250 columns x 3,000 houses of history would be a lot
# of writes to answer questions nobody asks.
TRACKED_FIELDS = (
    "Job Status", "Cabinet Measure Requested Date", "Cabinet Delivery Requested Date",
    "Cabinet Delivery Planned Date", "Cabinet Invoice Number", "Initial Cabinet Punch",
    "Blue Tape Ready", "Homeowner Walk Date", "Home Closing Date",
    "Truss Delivery Date Request", "Framing Delivery Requested Date",
    "Window and Door Delivery Date Request", "Interior Trim Delivery Request Date",
)


def _value(raw) -> str | None:
    """Text for storage. An unticked checkbox is not the word "False"."""
    if raw is None or raw is False:
        return None
    text = str(raw).strip()
    return text or None


def _sheet_rows(builder: str, sheet_id: int, token: str | None,
                folder: Path | None) -> list[dict]:
    """One builder's rows, from whichever source is available."""
    if token:
        return rows_from_api(sheet_id, token)
    if not folder or not folder.is_dir():
        return []
    # Newest export for this builder. Exports are named
    # "<Builder> - Tract Builder Management Master MMDDYY.xlsx".
    stem = builder.split()[0]
    files = sorted(folder.glob(f"{stem}*Tract Builder Management Master*.xlsx"),
                   key=_export_age, reverse=True)
    for f in files[:3]:
        try:
            return rows_from_xlsx(f)
        except (PermissionError, OSError):
            continue
    return []


_DATED = re.compile(r"(\d{2})(\d{2})(\d{2})(?=\.[^.]+$)")


def _export_age(path: Path) -> tuple:
    """Sort key: the MMDDYY in the filename first, mtime only as a tiebreak.

    mtime is not trustworthy here. In the cloud these files arrive over R2 and
    are stamped with the object's upload time, so a batch uploaded together all
    look the same age -- and an export from two days ago could beat today's.
    The date in the name is what the file is FOR, which is the thing that
    matters. (Same reasoning as scripts/archive_combined_reports.year_of.)
    """
    m = _DATED.search(path.name)
    dated = (f"20{m.group(3)}{m.group(1)}{m.group(2)}" if m else "")
    return (dated, path.stat().st_mtime)


def _record_history(db: Session, key: tuple[str, str], row: dict,
                    today: dt.date) -> int:
    """Extend or open a span for each tracked field.

    A field holding the same value just moves last_seen; a change closes the old
    span and opens a new one. That is what lets the report answer "how long has
    this been blank" without a row per field per day.
    """
    sub, lot = key
    changed = 0
    # Only the OPEN span per field matters. Ordered by id so the last write into
    # the dict is the highest id -- without the order_by the "newest" span is
    # whatever the database happened to return last, which silently reopens old
    # spans and destroys the staleness numbers this table exists to provide.
    existing = {
        h.field: h
        for h in db.query(SmartsheetHistory)
        .filter(SmartsheetHistory.key_sub == sub, SmartsheetHistory.key_lot == lot)
        .order_by(SmartsheetHistory.id)
        .all()
    }
    for field in TRACKED_FIELDS:
        if field not in row:
            continue                       # column absent on this builder's sheet
        value = _value(row.get(field))
        prior = existing.get(field)
        if prior is not None and prior.value == value:
            if prior.last_seen < today:
                prior.last_seen = today
                prior.days_held = (today - prior.first_seen).days + 1
            continue
        db.add(SmartsheetHistory(key_sub=sub, key_lot=lot, field=field, value=value,
                                 first_seen=today, last_seen=today, days_held=1))
        changed += 1
    return changed


def sync(db: Session, *, token: str | None = None, folder: str | Path | None = None,
         today: dt.date | None = None) -> dict:
    """Refresh every configured sheet. Returns a per-builder summary."""
    today = today or dt.date.today()
    folder = Path(folder) if folder else None
    result: dict[str, object] = {"source": "api" if token else "files", "sheets": {}}
    total_changes = 0

    # In the cloud there are no local exports -- the PC uploads them to R2 and
    # the server pulls them down first, the same bridge the tracker and Vendor
    # Suite feeds use. No-op on the source PC, where the files are already here.
    if not token:
        try:
            from app.config import get_settings
            from app.storage import hydrate_feeds

            if get_settings().r2_pull_enabled:
                result["hydrated"] = hydrate_feeds()
        except Exception as exc:  # noqa: BLE001 — a pull failure must not stop a
            result["hydrated"] = {"error": str(exc)}   # sync of whatever is here

    for builder, sheet_id in SHEETS.items():
        try:
            rows = _sheet_rows(builder, sheet_id, token, folder)
        except Exception as exc:  # noqa: BLE001 — one bad sheet must not stop the rest
            result["sheets"][builder] = {"error": str(exc)}
            continue
        if not rows:
            result["sheets"][builder] = {"rows": 0, "note": "no source found"}
            continue

        # Replace this builder's rows wholesale: a house deleted from the sheet
        # must disappear here too, and there is no delete feed to tell us.
        db.query(SmartsheetRow).filter(SmartsheetRow.sheet == builder).delete()
        cabinets = unjoinable = 0
        for row in rows:
            key = (norm_sub(row.get("Subdivision")), norm_lot(row.get("Lot #")))
            has_cab = "cabinets" in read_house(row).scopes
            if not key[0]:
                # A house with no Subdivision cannot be matched to anything.
                # Store it anyway and count it: five DR cabinet houses sit in
                # Onboarding with the field blank, and dropping them here would
                # hide a gap that is worth someone filling in.
                if has_cab:
                    unjoinable += 1
            cabinets += bool(has_cab)
            db.add(SmartsheetRow(
                sheet=builder, sheet_id=str(sheet_id),
                key_sub=key[0], key_lot=key[1],
                subdivision=_value(row.get("Subdivision")),
                lot=_value(row.get("Lot #")),
                has_cabinets=has_cab,
                data=json.dumps(row, default=str),
                pulled_at=dt.datetime.now(dt.timezone.utc),
            ))
            if has_cab:
                total_changes += _record_history(db, key, row, today)
        result["sheets"][builder] = {"rows": len(rows), "cabinet_houses": cabinets,
                                     "unjoinable": unjoinable}
    db.commit()
    result["history_changes"] = total_changes
    return result


def stored_rows(db: Session, *, cabinets_only: bool = False) -> list[dict]:
    """Every stored house as the plain dict the report expects, with the builder
    stamped on from the sheet it came from -- the row's own Customer column
    carries stray values and cannot be trusted for grouping."""
    q = db.query(SmartsheetRow)
    if cabinets_only:
        q = q.filter(SmartsheetRow.has_cabinets.is_(True))
    out = []
    for r in q.all():
        row = json.loads(r.data)
        row["_builder"] = r.sheet
        out.append(row)
    return out


def staleness(db: Session, key: tuple[str, str], field: str,
              today: dt.date | None = None) -> int | None:
    """How many days this field has held its current value. None when unknown."""
    today = today or dt.date.today()
    h = (db.query(SmartsheetHistory)
         .filter(SmartsheetHistory.key_sub == key[0],
                 SmartsheetHistory.key_lot == key[1],
                 SmartsheetHistory.field == field)
         .order_by(SmartsheetHistory.id.desc())
         .first())
    return None if h is None else (today - h.first_seen).days + 1
