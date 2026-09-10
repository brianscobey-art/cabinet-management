"""Field-by-field comparison that knows what each field actually means.

The first cut of this compared raw values and reported a disagreement on 109 of
109 matched houses, which is the signature of a broken comparison rather than a
broken dataset. Three of the four fields were not like-for-like:

  Status  CabinetTron tracks a CABINET workflow state (2.0-Ord, 4.0-Punch).
          Smartsheet tracks a CONSTRUCTION stage (Framing, Interior trim).
          Different vocabularies -- so both get mapped onto one coarse ladder
          and only a gap of two or more stages counts.

  Plan    'EX2 Willow STD' and 'will' are the same house. CabinetTron carries a
          series prefix and a swing suffix, Smartsheet carries an elevation.
          Both get stripped back to the plan name.

  Install CabinetTron holds the cabinet INSTALL date; Smartsheet holds the
          DELIVERY REQUESTED date. Delivery lands a few days ahead of install,
          so an exact-match test reports every correct house as wrong.
"""

from __future__ import annotations

import datetime as dt
import re

from app.smartsheet.scopes import as_date

AGREE = "agree"
DIFFER = "differ"
BLANK_SS = "blank in Smartsheet"
BLANK_CT = "blank in CabinetTron"
NO_DATA = "blank everywhere"
UNKNOWN = "not comparable"

# --------------------------------------------------------------- status -----
# One coarse construction ladder both systems can be placed on. The numbers are
# only used for distance, so the gaps between them carry no meaning.
_SS_STAGE = {
    "onboarding": 0, "preconstruction": 0, "pre-construction": 0,
    "released to construction": 0, "released": 0,
    "foundation": 1, "framing": 2, "rough in": 4, "roughin": 4,
    "drywall": 5, "interior trim": 6, "int trim": 6, "trim": 6,
    "screens": 7, "locksets": 7, "lockset": 7, "paint": 7,
    "flatwork (driveway)": 7, "flatwork": 7,
    "cabinet": 8, "cabinets": 8, "complete": 9,
}

# The stage that means the house is finished. A finished house cannot be
# "overdue" for cabinets that went in months ago.
DONE_STAGE = 9

# CabinetTron phase code -> the same ladder.
_PHASE_STAGE = {
    "0": 0, "1": 1, "2": 1, "3": 2, "4": 2, "4.1": 3, "4.2": 3,
    "4.3": 4, "4.4": 4, "4.5": 4, "5": 5, "6": 5, "7": 5, "8": 5,
    "9": 6, "10": 7, "11": 8, "12": 9,
}

# A gap of one stage is ordinary lag between two systems updated by different
# people on different days. Two or more is a real disagreement.
STAGE_TOLERANCE = 1

# Delivery precedes install. Anything inside this is the two systems agreeing.
DELIVERY_TOLERANCE_DAYS = 7
# Measure dates are the same field in both systems, so only rounding slack.
DATE_TOLERANCE_DAYS = 1

# Leading series token -- an EXPLICIT list, not "any short word". Matching any
# 1-4 letter first word ate the plan names themselves: "ALAB 46" became "46"
# and "Madi A" became "A".
_SERIES = re.compile(r"^(?:drh|ex|dr|ch|cc|c)\d{0,2}\s+(?=\S)", re.I)
# A trailing elevation, in any of the shapes the two systems use: "A1", "B1",
# "C13", a bare number ("ALAB 46"), or a lone letter ("Madi A").
_ELEVATION = re.compile(r"\s+(?:[A-Za-z]{1,2}\d{1,3}|\d{1,3}|[A-Za-z])\s*$")
_SUFFIX = re.compile(r"\s+(std|standard|[lr]|left|right)\s*$", re.I)
# "roanoake" vs "roanoka" scores exactly 0.80; the three genuine mismatches in
# the live data (Rhett/Victoria, Destin/Hawthorne, Beau/Ozark) all score under
# 0.30, so there is a wide margin between typo and wrong house.
PLAN_SIMILARITY = 0.80
# Size variants -- "Roanoake 30in" and "Roanoake" are the same plan to a builder.
_SIZE = re.compile(r"\s*\d+\s*(?:in|inch|\")\s*", re.I)


def plan_name(value) -> str:
    """Strip a plan back to the bit both systems agree on."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = _SERIES.sub("", text)
    text = _SIZE.sub(" ", text)
    # Suffixes and elevations stack: "Oxford STD R", "Madison STD A".
    for _ in range(4):
        stripped = _ELEVATION.sub("", _SUFFIX.sub("", text)).strip()
        if stripped == text or not stripped:
            break
        text = stripped
    # Anything after a comma is an option list ('Beau, B1DRWS'), not the plan.
    text = text.split(",")[0]
    return re.sub(r"[^a-z0-9]", "", text.lower())


def plans_agree(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    # Smartsheet is hand-typed and gets truncated ('will' for 'willow'), and
    # CabinetTron prefixes plan variants ('4EBF Cali' for 'Cali'). Containment
    # of four or more characters is the same plan; below that the risk of two
    # genuinely different plans colliding outweighs the false alarm it saves.
    short, long = sorted((a, b), key=len)
    if len(short) >= 4 and short in long:
        return True
    # One system spells it "Roanoake", the other "Roanoke". A near match on the
    # plan name is a typo, not two different houses. The threshold is set to
    # keep the real ones apart: Rhett/Victoria, Destin/Hawthorne and Beau/Ozark
    # all score far below it, and those are exactly the mismatches worth having.
    from difflib import SequenceMatcher

    return (len(short) >= 4
            and SequenceMatcher(None, a, b).ratio() >= PLAN_SIMILARITY)


def stage_of_smartsheet(value) -> int | None:
    return _SS_STAGE.get(str(value or "").strip().lower())


def stage_of_phase(code) -> int | None:
    return _PHASE_STAGE.get(str(code or "").strip())


def compare_status(phase_code, ss_status) -> tuple[str, str | None]:
    a, b = stage_of_phase(phase_code), stage_of_smartsheet(ss_status)
    if a is None and b is None:
        return NO_DATA, None
    if b is None:
        return BLANK_SS, None
    if a is None:
        return BLANK_CT, None
    gap = b - a
    if abs(gap) <= STAGE_TOLERANCE:
        return AGREE, None
    return DIFFER, ("Smartsheet ahead" if gap > 0 else "Smartsheet behind")


def compare_date(ct_value, ss_value, *, tolerance: int) -> tuple[str, int | None]:
    a, b = as_date(ct_value), as_date(ss_value)
    if a is None and b is None:
        return NO_DATA, None
    if b is None:
        return BLANK_SS, None
    if a is None:
        return BLANK_CT, None
    off = (b - a).days
    return (AGREE if abs(off) <= tolerance else DIFFER), off


def compare_plan(ct_value, ss_value) -> tuple[str, str | None]:
    a, b = plan_name(ct_value), plan_name(ss_value)
    if not a and not b:
        return NO_DATA, None
    if not b:
        return BLANK_SS, None
    if not a:
        return BLANK_CT, None
    return (AGREE, None) if plans_agree(a, b) else (DIFFER, f"{a} / {b}")


def as_of(value) -> dt.date | None:
    return as_date(value)
