"""Join a Smartsheet house to a CabinetTron job and a tracker row.

There is no shared id. Smartsheet has no Job Code and CabinetTron has no
Smartsheet row id, so the join is Subdivision + Lot #, normalised. That works
because both systems name communities the same way -- they were set up from the
same source -- but the lot values are written differently in each:

    Smartsheet   42.0      (a number, exported with a decimal)
    CabinetTron  05        (text, zero padded)
    Tracker      Lot 03    (text, sometimes prefixed)

so both sides get squeezed to a bare comparable token before matching. A lot
that is genuinely alphanumeric (A027, 24B, 8211023-1189) keeps its letters --
those distinguish real houses and must not be stripped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# "Lot 03", "lot#3", "LOT-3" -> the part that identifies the lot.
_LOT_PREFIX = re.compile(r"^\s*lot\s*[#\-.]?\s*", re.I)
_TRAILING_ZEROS = re.compile(r"\.0+$")


def norm_sub(value) -> str:
    """Community name down to letters and digits: 'Hodges Bayou Ph 2 50s' and
    'Hodges Bayou PH 2 50s' must land on the same key."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def norm_lot(value) -> str:
    """A lot token both systems can agree on.

    Numbers lose their export decimal and leading zeros so 42.0 == 42 == 042.
    Anything carrying letters is left alone apart from case and separators,
    because A027 and A28 are different houses and 24B is not 24.
    """
    raw = _LOT_PREFIX.sub("", str(value or "").strip())
    raw = _TRAILING_ZEROS.sub("", raw)
    if not raw:
        return ""
    if raw.replace("-", "").isdigit():
        # Purely numeric (possibly hyphenated like 8211023-1189): drop padding
        # on each part so 0004 == 4.
        return "-".join(p.lstrip("0") or "0" for p in raw.split("-"))
    return re.sub(r"[^a-z0-9-]", "", raw.lower())


def key_of(subdivision, lot) -> tuple[str, str]:
    return (norm_sub(subdivision), norm_lot(lot))


MATCHED = "matched"
ONLY_SMARTSHEET = "not in CabinetTron"
ONLY_CABINETTRON = "not in Smartsheet"


@dataclass
class Match:
    key: tuple[str, str]
    state: str
    smartsheet: dict | None = None
    job: object | None = None          # the CabinetTron Job row
    tracker: dict | None = None        # the 3.0 tracker DATA row
    duplicates: list = field(default_factory=list)


def index_by_key(items, sub_of, lot_of) -> dict[tuple[str, str], list]:
    """Group anything by its normalised key. Returns lists, not single values:
    two houses can legitimately share a subdivision+lot in the sheets (a split
    job, a re-plat), and silently keeping the last one would lose a house."""
    out: dict[tuple[str, str], list] = {}
    for item in items:
        k = key_of(sub_of(item), lot_of(item))
        if k == ("", "") or not k[0]:
            continue
        out.setdefault(k, []).append(item)
    return out


def join(smartsheet_rows: list[dict], jobs: list, tracker_rows: list[dict],
         *, expected) -> list[Match]:
    """Three-way join on subdivision + lot.

    `expected` decides which unmatched Smartsheet rows count as a gap: a house
    where we do framing but not cabinets was never CabinetTron's to hold, so it
    must not be reported as missing. Everything else is simply left out.
    """
    ss = index_by_key(smartsheet_rows,
                      lambda r: r.get("Subdivision"), lambda r: r.get("Lot #"))
    ct = index_by_key(jobs,
                      lambda j: j.community.name if j.community else None,
                      lambda j: j.lot_number)
    tr = index_by_key(tracker_rows,
                      lambda r: r.get("Subdivision"), lambda r: r.get("Lot #"))

    out: list[Match] = []
    for k, rows in ss.items():
        row = rows[0]
        if not expected(row):
            continue
        jobs_here = ct.get(k, [])
        out.append(Match(
            key=k,
            state=MATCHED if jobs_here else ONLY_SMARTSHEET,
            smartsheet=row,
            job=jobs_here[0] if jobs_here else None,
            tracker=(tr.get(k) or [None])[0],
            duplicates=rows[1:] + jobs_here[1:],
        ))
    # Cabinet jobs we hold that Smartsheet has no row for at all.
    for k, jobs_here in ct.items():
        if k in ss:
            continue
        out.append(Match(key=k, state=ONLY_CABINETTRON, job=jobs_here[0],
                         tracker=(tr.get(k) or [None])[0],
                         duplicates=jobs_here[1:]))
    return out
