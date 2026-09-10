"""What Carter supplies on a house, and the dates each scope produces.

The Tract Builder Management sheets carry one row per house and ~250 columns
covering every scope we might sell into it — foundation, framing, trusses,
windows and doors, interior trim, locksets, form package, cabinets. We do not
do all scopes on all houses, so before any date means anything you have to know
which scopes that house is actually ours.

Two different shapes record that, and mixing them up silently returns zero:

  * checkbox scopes (Cabinets, Framing Supply, LockSet Supply) hold True/x
  * choice scopes  (Windows Supply & Install, Ext Doors Supply & Install) hold
    "Material and Labor" / "Material Only" / "No"

A choice scope reading "Material Only" means we sold it and somebody else hung
it, so it is ours for delivery dates but not for install dates.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

TRUE_TOKENS = {"true", "yes", "x", "1"}


@dataclass(frozen=True)
class Scope:
    key: str
    label: str
    # Column(s) that say we provide this scope. First one found on the sheet wins:
    # the two builders name a few of these differently.
    provide_cols: tuple[str, ...]
    # "check" -> truthy test; "choice" -> Material and Labor / Material Only / No
    provide_kind: str
    # Date columns this scope produces, most-trusted first. The report shows the
    # first one present; the timeline uses it as this scope's anchor.
    date_cols: tuple[str, ...] = ()
    # Roughly where it falls in the build. Only used for ordering the display.
    order: int = 0


# Build order. Foundation goes in first, cabinets and trim near the end.
SCOPES: tuple[Scope, ...] = (
    Scope("foundation", "Foundation", ("Foundation Supply",), "check",
          ("Foundation Delivery Requested Date",), 10),
    Scope("framing", "Framing", ("Framing Supply",), "check",
          ("Framing Delivery Requested Date", "Framing Delivery Audit Date (auto)"), 20),
    Scope("framing_labor", "Framing labor", ("Framing Labor",), "check", (), 25),
    Scope("trusses", "Trusses", ("Trusses Supply",), "check",
          ("Truss Delivery Date Request", "Truss Delivery Planned Date"), 30),
    Scope("windows", "Windows", ("Windows Supply & Install",), "choice",
          ("Window and Door Delivery Date Request",
           "Window and Door Actual Delivery Date"), 40),
    Scope("ext_doors", "Ext doors", ("Ext Doors Supply & Install",), "choice",
          ("Window and Door Delivery Date Request",), 45),
    Scope("form_package", "Form package", ("Form Package Supply",), "check",
          ("Form Package Delivery audit Date",), 50),
    Scope("locksets", "Locksets", ("LockSet Supply",), "check", (), 55),
    Scope("int_trim", "Interior trim",
          ("Interior Trim Supply", "Int Trim Supply Labor",
           "Interior Trim Supply Labor"), "check",
          ("Interior Trim Delivery Request Date",
           "Interior trim Delivery audit Date"), 60),
    Scope("cabinets", "Cabinets", ("Cabinets", "Cabinet"), "check",
          ("Cabinet Delivery Requested Date", "Cabinet Delivery Planned Date"), 70),
)

SCOPES_BY_KEY = {s.key: s for s in SCOPES}

# The cabinet fields we care about beyond the delivery date. Kept separate from
# Scope.date_cols because these are what we COMPARE, not what we anchor on.
CABINET_FIELDS: tuple[str, ...] = (
    "Cabinet Measure Requested Date",
    "Cabinet Delivery Requested Date",
    "Cabinet Delivery Planned Date",
    "Cabinet Invoice Number",
    "Initial Cabinet Punch",
    "Blue Tape Ready",
    "Homeowner Walk Date",
    "Home Closing Date",
)


def as_date(value) -> dt.date | None:
    """Smartsheet hands dates back as datetimes from the API and as ISO strings
    from an .xlsx export. Anything else (a stray 'PP', a '#UNPARSEABLE') is not
    a date and must not become one."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and len(value) >= 10 and value[4:5] == "-":
        try:
            return dt.datetime.fromisoformat(value[:19]).date()
        except ValueError:
            return None
    return None


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def provides(row: dict, scope: Scope) -> str | None:
    """'labor', 'material', or None. A checkbox scope that is ticked counts as
    labor: on those lines we only tick it when the work is ours."""
    for col in scope.provide_cols:
        if col not in row:
            continue
        raw = _text(row[col])
        if not raw:
            continue
        if scope.provide_kind == "check":
            return "labor" if raw.lower() in TRUE_TOKENS else None
        low = raw.lower()
        if "labor" in low:
            return "labor"
        if "material" in low:
            return "material"
        return None
    return None


def scope_matrix(row: dict) -> dict[str, str]:
    """Every scope this house is ours for, keyed by scope -> labor|material."""
    out = {}
    for scope in SCOPES:
        got = provides(row, scope)
        if got:
            out[scope.key] = got
    return out


def anchor_date(row: dict, scope: Scope) -> dt.date | None:
    """This scope's date on this house, taking the most-trusted column present."""
    for col in scope.date_cols:
        got = as_date(row.get(col))
        if got:
            return got
    return None


@dataclass
class HouseTimeline:
    """One house: what we supply, when each scope landed, and what that implies
    for cabinets."""
    scopes: dict[str, str] = field(default_factory=dict)
    dates: dict[str, dt.date] = field(default_factory=dict)

    @property
    def has_cabinets(self) -> bool:
        return "cabinets" in self.scopes


def read_house(row: dict) -> HouseTimeline:
    house = HouseTimeline(scopes=scope_matrix(row))
    for scope in SCOPES:
        got = anchor_date(row, scope)
        if got:
            house.dates[scope.key] = got
    return house
