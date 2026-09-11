"""Push CabinetTron's job list into a Smartsheet the rest of the company can see.

Everything else in this package READS Smartsheet. This is the one place that
writes, and it writes to exactly one sheet -- the job tracker it creates and
owns. It must never touch the eleven Tract Builder Management Masters: Brian
wants write-back to those eventually, and that will be a separate, deliberate
piece of work with its own permission (his words, 9/11/26: "not yet").

Rows are recognised on each push by BUID where there is one, falling back to
Job Code. BUID is the identifier every system shares -- the tracker calls it
Builder Job Code, Smartsheet calls it Lot ID, VendorSuite calls it Job Number
-- so carrying it is what will make the eventual write-back a lookup rather
than a name-matching exercise. But it is blank on 76 of the 360 live jobs
(custom builders, one-offs), and keying on it alone would re-add those as new
rows every night.
"""

from __future__ import annotations

import datetime as dt

import httpx

from scripts.import_tracker import is_real_job_code

API = "https://api.smartsheet.com/2.0"

# The sheet's shape, in Brian's reading order: (column title, tracker column,
# Smartsheet column type).
#
# Job Code is first and primary, not BUID. Brian listed BUID first, but a
# Smartsheet primary column should not be blank and BUID is empty on 76 of the
# 360 live jobs -- every custom builder and one-off. Worse, the nightly push
# matches on it, so those 76 would be re-added as new rows every single night.
# Job Code is filled on all 360. BUID sits immediately beside it and is still
# what the eventual write-back will key on.
COLUMNS: list[tuple[str, str | None, str]] = [
    ("Job Code", "Job Code", "TEXT_NUMBER"),
    ("BUID", "Builder Job Code", "TEXT_NUMBER"),
    ("Ashley's Code", "Ashley's  Code", "TEXT_NUMBER"),   # two spaces in DATA
    ("G-Code", "G-Code", "TEXT_NUMBER"),
    ("I-Code", "I-Code", "TEXT_NUMBER"),
    ("Builder", "Full Builder", "TEXT_NUMBER"),
    ("Lot #", "Lot #", "TEXT_NUMBER"),
    ("Address", "Address", "TEXT_NUMBER"),
    ("City", "City", "TEXT_NUMBER"),
    ("State", "State", "TEXT_NUMBER"),
    ("Super", "Super", "TEXT_NUMBER"),
    ("House Plan", "House Plan", "TEXT_NUMBER"),
    ("CONST LVL", "CONST LVL", "TEXT_NUMBER"),
    ("Requested Install", "Requested Install Date", "DATE"),
    ("Actual Install", "Actual Install Date", "DATE"),
    ("Install Week", "Install Week", "TEXT_NUMBER"),
    ("Installer", "Installer", "TEXT_NUMBER"),
    ("Install Payment", "Labor Total", "TEXT_NUMBER"),
    # Not from the tracker -- stamped by the push so nobody has to guess how
    # old the sheet is. A Smartsheet row carries no "when did this arrive".
    ("Updated", None, "DATE"),
]

PRIMARY = "Job Code"

# CONST LVL values that take a job off the sheet: finished or cancelled.
DROPPED_CONST_LVLS = {"6.0-Clsd", "8.0-Void"}

# Tracker cells arrive as formula output rather than blanks. None of these are
# values; writing them would put "#N/A" in front of the whole company.
EMPTY_TEXT = {"", "na", "n/a", "#n/a", "none", "nan", "0", "00:00:00", "-", "false"}


def _clean(raw, kind: str):
    """One tracker cell, ready for the API, or None if it is not really there."""
    if raw is None:
        return None
    if kind == "DATE":
        if isinstance(raw, dt.datetime):
            return raw.date().isoformat()
        if isinstance(raw, dt.date):
            return raw.isoformat()
        text = str(raw).strip()
        if len(text) >= 10 and text[4:5] == "-":
            try:
                return dt.datetime.fromisoformat(text[:19]).date().isoformat()
            except ValueError:
                return None
        return None
    text = str(raw).strip()
    if text.lower() in EMPTY_TEXT:
        return None
    # Excel hands integers back as floats: a lot is 1189, not 1189.0.
    if text.endswith(".0") and text[:-2].replace("-", "").isdigit():
        text = text[:-2]
    return text


def shape(tracker_rows: list[dict], *, today: dt.date | None = None) -> list[dict]:
    """Live jobs, every builder, as {column title: value}."""
    stamp = (today or dt.date.today()).isoformat()
    out = []
    for row in tracker_rows:
        if str(row.get("CONST LVL") or "").strip() in DROPPED_CONST_LVLS:
            continue
        rec = {}
        for title, source, kind in COLUMNS:
            rec[title] = stamp if source is None else _clean(row.get(source), kind)
        # The DATA table ends with formula-driven template rows whose code
        # computes to "-0000". scripts.import_tracker already owns that rule --
        # a real code contains at least one letter -- and it was validated
        # against the live sheet, so reuse it rather than inventing a second.
        if not is_real_job_code(rec.get("Job Code")):
            continue
        out.append(rec)
    out.sort(key=lambda r: (r.get("Builder") or "~", r.get("Address") or ""))
    return out


# ------------------------------------------------------------------ API ----
def _client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=API,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        timeout=120.0,
    )


def create_sheet(token: str, name: str, workspace_id: int) -> dict:
    """Create the sheet. Called once; after that the id is configuration."""
    body = {
        "name": name,
        "columns": [
            {"title": t, "type": k, "primary": t == PRIMARY}
            if t == PRIMARY else {"title": t, "type": k}
            for t, _, k in COLUMNS
        ],
    }
    with _client(token) as c:
        r = c.post(f"/workspaces/{workspace_id}/sheets", json=body)
        r.raise_for_status()
        return r.json()["result"]


def fetch_existing(token: str, sheet_id: int) -> tuple[dict, dict]:
    """(column title -> id, row key -> row id) for what is already on the sheet."""
    with _client(token) as c:
        r = c.get(f"/sheets/{sheet_id}", params={"exclude": "nonexistentCells"})
        r.raise_for_status()
        payload = r.json()
    cols = {col["title"].strip(): col["id"] for col in payload.get("columns", [])}
    index = {}
    for row in payload.get("rows", []):
        by_id = {c.get("columnId"): c.get("value") for c in row.get("cells", [])}
        key = row_key({"BUID": by_id.get(cols.get("BUID")),
                       "Job Code": by_id.get(cols.get("Job Code"))})
        if key:
            index[key] = row["id"]
    return cols, index


def row_key(rec: dict) -> str | None:
    """How a row on the sheet is recognised on the next push.

    BUID first because it is the cross-system identifier, Job Code as the
    fallback for the 76 live jobs that have no BUID. Using either alone breaks:
    BUID alone re-adds those 76 every night, Job Code alone collides on the two
    codes the tracker carries twice.
    """
    for field in ("BUID", "Job Code"):
        raw = rec.get(field)
        if raw is None or str(raw).strip() == "":
            continue
        text = str(raw).strip()
        if text.endswith(".0") and text[:-2].replace("-", "").isdigit():
            text = text[:-2]
        return f"{field}:{text}"
    return None


def _cells(rec: dict, cols: dict[str, int]) -> list[dict]:
    out = []
    for title, _, _kind in COLUMNS:
        cid = cols.get(title)
        if cid is None:
            continue
        value = rec.get(title)
        # An explicit empty string clears a cell that used to hold something;
        # omitting it would leave stale data behind on an update.
        out.append({"columnId": cid, "value": value if value is not None else ""})
    return out


def push(token: str, sheet_id: int, records: list[dict], *,
         chunk: int = 200) -> dict:
    """Update rows we already have, add the rest. Nothing is deleted.

    Deliberately not a wipe-and-reload: people will add comments, attachments
    and their own columns to this sheet, and replacing rows would throw all of
    that away every night. Matching on BUID keeps a row's identity stable.
    """
    cols, existing = fetch_existing(token, sheet_id)
    missing = [t for t, _, _k in COLUMNS if t not in cols]
    if missing:
        return {"error": f"sheet is missing columns: {missing}"}

    to_add, to_update = [], []
    seen: set[str] = set()
    collisions = []
    for rec in records:
        key = row_key(rec)
        if key is None:
            continue
        if key in seen:
            # Two live rows claiming one identity. Reported, not silently
            # merged -- the tracker really does carry a job code twice.
            collisions.append(key)
            continue
        seen.add(key)
        row_id = existing.get(key)
        if row_id:
            to_update.append({"id": row_id, "cells": _cells(rec, cols)})
        else:
            to_add.append({"toBottom": True, "cells": _cells(rec, cols)})

    added = updated = 0
    with _client(token) as c:
        for i in range(0, len(to_update), chunk):
            r = c.put(f"/sheets/{sheet_id}/rows", json=to_update[i:i + chunk])
            r.raise_for_status()
            updated += len(r.json().get("result", []))
        for i in range(0, len(to_add), chunk):
            r = c.post(f"/sheets/{sheet_id}/rows", json=to_add[i:i + chunk])
            r.raise_for_status()
            added += len(r.json().get("result", []))
    return {"added": added, "updated": updated,
            "on_sheet": len(existing) + added, "duplicate_keys": collisions}
