"""Predict cabinet timing from the scopes that run ahead of it.

Why this exists: on the 263 DR cabinet houses, Smartsheet's own cabinet
scheduling fields are 1-10% filled, while the upstream scopes it shares a row
with run 21-84%. The dates we need are missing; the dates that predict them are
not. So we learn the real spacing between scopes from the houses that carry
both, and use it to say when cabinets are due on the houses that carry only the
upstream half.

The intervals are measured off REQUESTED dates, which is what the sheets keep.
That makes a prediction a statement about the house's own plan, not about
physical reality -- a flag here means "this house has drifted from its own
schedule", which is the useful thing anyway.
"""

from __future__ import annotations

import datetime as dt
import statistics as st
from dataclasses import dataclass

from app.smartsheet.scopes import HouseTimeline

# Anchors we will predict cabinets from, closest-first. Interior trim sits
# within days of cabinets so it is the tightest signal; foundation is six weeks
# out and only used when nothing better exists.
ANCHOR_PREFERENCE: tuple[str, ...] = (
    "int_trim", "windows", "ext_doors", "framing", "trusses", "foundation",
)

# Below this many observed pairs we do not trust an interval enough to predict.
MIN_OBSERVATIONS = 8
# An interval whose middle 50% is wider than this is too loose to flag on.
MAX_IQR_DAYS = 45


@dataclass(frozen=True)
class Interval:
    """Observed spacing from one scope to cabinet delivery."""
    anchor: str
    days: int
    n: int
    iqr: int

    @property
    def usable(self) -> bool:
        return self.n >= MIN_OBSERVATIONS and self.iqr <= MAX_IQR_DAYS


def learn_intervals(houses: list[HouseTimeline]) -> dict[str, Interval]:
    """Median days from each upstream scope to cabinet delivery, off the houses
    that actually carry both dates. Outliers beyond a year are dropped as data
    entry rather than schedule."""
    out: dict[str, Interval] = {}
    for anchor in ANCHOR_PREFERENCE:
        gaps = [
            (h.dates["cabinets"] - h.dates[anchor]).days
            for h in houses
            if anchor in h.dates and "cabinets" in h.dates
        ]
        gaps = sorted(g for g in gaps if -200 < g < 400)
        if not gaps:
            continue
        q1, q3 = gaps[len(gaps) // 4], gaps[(3 * len(gaps)) // 4]
        out[anchor] = Interval(anchor, round(st.median(gaps)), len(gaps), q3 - q1)
    return out


@dataclass
class Prediction:
    expected: dt.date
    anchor: str          # which scope it was derived from
    anchor_date: dt.date
    days: int            # the interval used
    n: int               # how many houses that interval was learned from
    spread: int          # IQR in days -- how wide to draw the window

    @property
    def window(self) -> tuple[dt.date, dt.date]:
        half = max(self.spread // 2, 3)
        return (self.expected - dt.timedelta(days=half),
                self.expected + dt.timedelta(days=half))


def predict(house: HouseTimeline, intervals: dict[str, Interval]) -> Prediction | None:
    """Expected cabinet delivery, from the closest usable upstream anchor this
    house actually has. Returns None when the house gives us nothing to go on --
    which is itself worth reporting, so never fake it."""
    for anchor in ANCHOR_PREFERENCE:
        iv = intervals.get(anchor)
        if not iv or not iv.usable or anchor not in house.dates:
            continue
        base = house.dates[anchor]
        return Prediction(base + dt.timedelta(days=iv.days), anchor, base,
                          iv.days, iv.n, iv.iqr)
    return None


# Status the report shows per house.
NO_SIGNAL = "no signal"       # no prediction possible AND no cabinet date
NOT_DUE = "not due yet"       # predicted, window still ahead of us -- nothing wrong
ON_PLAN = "on plan"           # cabinet date recorded and near the prediction
EARLY = "ahead of plan"
DRIFTED = "off plan"          # recorded, but well away from the prediction
DUE = "due now"               # no cabinet date, prediction window is open
OVERDUE = "overdue"           # no cabinet date, prediction window has passed


def assess(house: HouseTimeline, pred: Prediction | None,
           today: dt.date | None = None) -> tuple[str, int | None]:
    """(status, days off) for one house. Days off is signed: positive means
    later than expected."""
    today = today or dt.date.today()
    actual = house.dates.get("cabinets")
    if pred is None:
        return (ON_PLAN if actual else NO_SIGNAL), None
    lo, hi = pred.window
    if actual:
        off = (actual - pred.expected).days
        if lo <= actual <= hi:
            return ON_PLAN, off
        return (EARLY if actual < lo else DRIFTED), off
    if today > hi:
        return OVERDUE, (today - pred.expected).days
    if today >= lo:
        return DUE, (today - pred.expected).days
    # Predicted, and the window has not opened. That is a healthy house with
    # nothing to do yet -- not the same as one we cannot see, so do not file it
    # under NO_SIGNAL where it would hide 100-odd houses that are simply early.
    return NOT_DUE, (today - pred.expected).days
