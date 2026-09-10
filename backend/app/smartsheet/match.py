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
    """Community name down to letters and digits, then through the alias map:
    'Hodges Bayou Ph 2 50s' and 'Hodges Bayou PH 2 50s' must land on the same
    key, and so must the tracker's name for a community and Smartsheet's."""
    flat = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    return COMMUNITY_ALIASES.get(flat, flat)


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


# The tracker and Smartsheet name the same community differently, which is why
# only 14 of 51 tracker communities joined. Fuzzy matching is NOT safe here:
# difflib pairs "Colonial East TH" with "Colonial East SF", and townhomes and
# single-family are different houses on different lots. So the mapping is
# explicit and only holds pairs that are unambiguous -- an abbreviation, a
# spelling, or a phase written two ways. Anything needing a judgement call is
# left unmatched and reported instead, for Brian to confirm.
#
# Keys and values are already normalised (see norm_sub).
COMMUNITY_ALIASES: dict[str, str] = {
    "colonialeastth": "colonialeasttownhomes",
    "gardenvillaths": "gardenvillastownhomes",
    "ashetonvillage": "ashtonvillage",
    "hodgesbayouph250s": "hodgesbayouphaseii50s",
    "hodgesbayouph3horton": "hodgesbayouphaseiii",
}


def key_of(subdivision, lot) -> tuple[str, str]:
    return (norm_sub(subdivision), norm_lot(lot))


def norm_buid(value) -> str | None:
    """The builder job code, however a sheet stored it.

    Every system carries this same 9-digit number under a different heading --
    the tracker calls it "Builder Job Code", Smartsheet calls it "Lot ID",
    VendorSuite calls it "Job Number" -- and unlike a community name nobody
    retypes it, so it joins where names do not: 202 houses against 108 on
    community+lot. Excel hands some of them back as floats, hence the split.
    """
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value).split(".")[0])
    return digits if len(digits) == 9 else None


MATCHED = "matched"
ONLY_SMARTSHEET = "not in CabinetTron"
ONLY_CABINETTRON = "not in Smartsheet"
# The 3.0 tracker carries the house as a cabinet job, but its Smartsheet row
# does not have the Cabinets box ticked. Smartsheet is the sheet that decides
# whether we supply cabinets, so one of the two is wrong and somebody has to
# say which. Brian asked for these by name 9/10/26.
NOT_TICKED = "cabinets not ticked in Smartsheet"


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


def index_by_buid(items, buid_of) -> dict[str, list]:
    out: dict[str, list] = {}
    for item in items:
        b = norm_buid(buid_of(item))
        if b:
            out.setdefault(b, []).append(item)
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
    # The 3.0 tracker's DATA table calls it "Community", not "Subdivision".
    # Keying on the wrong name is silent -- .get returns None, every row keys to
    # ("", ...) and gets dropped, so the tracker column simply reads blank on
    # every house and looks like missing data rather than a broken join. It sat
    # at 0 of 608 rows that way. Both names are accepted so a rename in either
    # direction cannot bring it back.
    tr = index_by_key(tracker_rows,
                      lambda r: r.get("Community") or r.get("Subdivision"),
                      lambda r: r.get("Lot #"))

    # The strong key. Community names get retyped and abbreviated; a builder
    # job code does not, so it is tried first and the name-based key is only
    # the fallback for rows that have no BUID on one side or the other.
    ss_b = index_by_buid(smartsheet_rows, lambda r: r.get("Lot ID"))
    tr_b = index_by_buid(tracker_rows, lambda r: r.get("Builder Job Code"))

    def tracker_for(row: dict, k: tuple[str, str]):
        b = norm_buid(row.get("Lot ID"))
        if b and b in tr_b:
            return tr_b[b][0]
        return (tr.get(k) or [None])[0]

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
            tracker=tracker_for(row, k),
            duplicates=rows[1:] + jobs_here[1:],
        ))
    # Houses the tracker treats as cabinet jobs whose Smartsheet row is not
    # ticked for cabinets. Every row in the tracker's DATA table IS a cabinet
    # job -- that is what the tracker is for -- so a Smartsheet row sitting
    # beside it unticked is a contradiction worth surfacing, not a filter to
    # apply quietly.
    seen = {id(m.smartsheet) for m in out if m.smartsheet is not None}
    for trow in tracker_rows:
        k = key_of(trow.get("Community") or trow.get("Subdivision"),
                   trow.get("Lot #"))
        b = norm_buid(trow.get("Builder Job Code"))
        ss_here = (ss_b.get(b) if b else None) or ss.get(k)
        if not ss_here:
            continue
        row = ss_here[0]
        if expected(row) or id(row) in seen:
            continue
        seen.add(id(row))
        jobs_here = ct.get(k, [])
        out.append(Match(key=k, state=NOT_TICKED, smartsheet=row,
                         job=jobs_here[0] if jobs_here else None,
                         tracker=trow, duplicates=jobs_here[1:]))

    # Cabinet jobs we hold that Smartsheet has no row for.
    #
    # Only within a subdivision Smartsheet already tracks. Without that guard
    # this reports every retail counter sale, homeowner job and one-off custom
    # builder as "missing from Smartsheet" -- 381 rows across 30 accounts that
    # were never going to appear in a tract builder sheet. A lot missing from a
    # subdivision Smartsheet DOES track is a real gap; the rest is not.
    known_subdivisions = {k[0] for k in ss}
    for k, jobs_here in ct.items():
        if k in ss or k[0] not in known_subdivisions:
            continue
        out.append(Match(key=k, state=ONLY_CABINETTRON, job=jobs_here[0],
                         tracker=(tr.get(k) or [None])[0],
                         duplicates=jobs_here[1:]))
    return out
