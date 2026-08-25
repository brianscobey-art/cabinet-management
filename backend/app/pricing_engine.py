"""The DRH cabinet pricing calculation, lifted out of the workbook.

Pure functions, no database and no Excel — so it can be unit-tested against the
workbook's own numbers (see scripts/reconcile_pricing.py). Phase 1 proved this
chain reproduces all 174 priced plans exactly; everything added here for price
groups and stocking scenarios must keep that true, which the reconciler checks.

THREE THINGS THE WORKBOOK COULD NOT DO, added here:

1. Price group. Table2 lists each SKU five times, once per group (1-5), but the
   workbook looks up on SKU alone so XLOOKUP always lands on group 1 and the
   other four are unreachable. Here the group is an input. The spread is real:
   B36 is $815 at group 1 and $1,087 at group 5.

2. Scenarios. The workbook has one multiplier ($D$2 = 0.21). A Scenario carries
   a base and an optional better "stocked" rate, so the same plan can be priced
   two ways and the saving shown.

3. Per-SKU multipliers. Stocking only the high-volume SKUs means the rate varies
   line by line. Resolution order is override -> stocked -> base.

STOCKING IS SCOPED TO LEVEL 1 (Brian, 8/25/26). A group 2-5 line is special
order by definition, so it never gets the stocked rate even if the SKU is on the
stock list. That is why a group 3 plan shows no saving, and the UI should say so
rather than leave someone hunting for the missing discount.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

__all__ = [
    "Rates", "Scenario", "SkuInfo", "PlanLine", "LinePrice", "PlanPrice",
    "xround", "resolve_multiplier", "price_lines", "price_plan", "compare",
]

STOCKABLE_GROUPS = (1,)  # only level 1 is stocked for now


def xround(x, digits: int = 0) -> float:
    """Excel ROUND is half-away-from-zero; Python's round() is banker's rounding.

    Using the wrong one lands a penny out on every .5 and reads like a pricing
    bug rather than a rounding one. Phase 1 hit exactly this.
    """
    if x is None:
        return None
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Rates:
    """The sheet's rate card. Defaults are the workbook's own values, but Table6
    carries per-row rates (Install runs 25 / 27 / 27.5, Hardware 1 / 2) so a
    caller can override any of them per plan."""

    tax: float = 0.07              # $D$4
    freight_pct: float = 0.10      # $G$2  — on cabinet cost, not total
    delivery: float = 0.0          # $G$3  — typed as 50 on 13 rows
    assem_rate: float = 10.0       # $J$2
    install_rate: float = 25.0     # $J$3
    hardware_rate: float = 1.0     # $J$4
    handle_rate: float = 2.0       # $J$5
    shoe_rate: float = 25.0        # $J$6
    knob_cost: float = 1.25        # $E$5
    handle_cost: float = 2.60      # $E$6
    margin: float = 0.15           # $G$4 / Table6 col U


@dataclass(frozen=True)
class Scenario:
    """A way of buying. "Current" is base only; a stocking program adds a better
    rate that applies to stocked, level-1 SKUs."""

    name: str
    base_multiplier: float                       # special order / today's rate
    stocked_multiplier: float | None = None      # better rate when we stock it
    stocked_skus: frozenset[str] = frozenset()
    sku_overrides: dict[str, float] = field(default_factory=dict)

    def applies_to(self, sku: str, price_group: int) -> bool:
        return (
            self.stocked_multiplier is not None
            and price_group in STOCKABLE_GROUPS
            and sku in self.stocked_skus
        )


@dataclass(frozen=True)
class SkuInfo:
    """What the price tables know about one SKU. `prices` is keyed by price group."""

    sku: str
    prices: dict[int, float]
    install_group: str | None = None
    doors: float = 0.0
    drawers: float = 0.0

    def price(self, group: int) -> float | None:
        # Fall back to group 1 rather than raising: a SKU missing from a higher
        # group is a gap in the price table, and pricing at the known-good level
        # beats failing the whole plan. The caller sees it via LinePrice.fallback.
        return self.prices.get(group, self.prices.get(1))


@dataclass(frozen=True)
class PlanLine:
    qty: float
    sku: str
    area: str = "All"
    price_group: int | None = None   # None = use the plan's group


@dataclass(frozen=True)
class LinePrice:
    sku: str
    qty: float
    price_group: int
    unit_list: float
    multiplier: float
    multiplier_source: str      # "override" | "stocked" | "base"
    fallback: bool              # priced off group 1 because the group was missing

    @property
    def list_total(self) -> float:
        return self.unit_list * self.qty

    @property
    def cost_total(self) -> float:
        return self.list_total * self.multiplier


def resolve_multiplier(sku: str, price_group: int, scenario: Scenario) -> tuple[float, str]:
    """Override beats stocked beats base. Returns (multiplier, why) so the UI can
    explain a number instead of just showing it."""
    if sku in scenario.sku_overrides:
        return scenario.sku_overrides[sku], "override"
    if scenario.applies_to(sku, price_group):
        return scenario.stocked_multiplier, "stocked"
    return scenario.base_multiplier, "base"


def price_lines(lines, skus: dict, price_group: int, scenario: Scenario) -> list[LinePrice]:
    out = []
    for ln in lines:
        info = skus.get(ln.sku)
        if info is None:
            continue          # unknown SKU — reported by the caller, not priced
        group = ln.price_group or price_group
        unit = info.price(group)
        if unit is None:
            continue
        mult, why = resolve_multiplier(ln.sku, group, scenario)
        out.append(LinePrice(
            sku=ln.sku, qty=ln.qty, price_group=group, unit_list=unit,
            multiplier=mult, multiplier_source=why,
            fallback=group not in info.prices,
        ))
    return out


@dataclass
class PlanPrice:
    scenario: str
    price_group: int
    lines: list
    cabinet_list: float
    cabinet_cost: float
    hardware_cost: float
    total_materials: float
    tax: float
    freight: float
    materials_with_tax_freight: float
    assembly: float
    install: float
    hardware_labor: float
    total_labor: float
    delivery: float
    total_cogs: float
    margin: float
    sale_price: float
    profit: float

    @property
    def stocked_lines(self) -> int:
        return sum(1 for ln in self.lines if ln.multiplier_source == "stocked")


def price_plan(
    lines,
    skus: dict,
    *,
    price_group: int = 1,
    scenario: Scenario,
    rates: Rates = Rates(),
    counts: dict | None = None,
    hardware_count: float = 0.0,
    hardware_sel: str = "KNB",
) -> PlanPrice:
    """The Table6 chain, for one plan.

    `counts` is the per-plan install-group tally the workbook keeps in Table8
    (assembly / install / hardware). `hardware_count` is the knob-or-handle count.
    """
    counts = counts or {}
    priced = price_lines(lines, skus, price_group, scenario)

    cabinet_list = sum(ln.list_total for ln in priced)
    cabinet_cost = sum(ln.cost_total for ln in priced)

    unit_hard = rates.knob_cost if hardware_sel.upper() == "KNB" else rates.handle_cost
    hardware_cost = unit_hard * hardware_count

    total_materials = cabinet_cost + hardware_cost
    tax = total_materials * rates.tax
    freight = cabinet_cost * rates.freight_pct
    materials2 = total_materials + tax + freight

    assembly = counts.get("assembly", 0.0) * rates.assem_rate
    install = xround(counts.get("install", 0.0) * rates.install_rate, 0)
    hardware_labor = counts.get("hardware", 0.0) * rates.hardware_rate
    total_labor = assembly + install + hardware_labor

    total_cogs = materials2 + total_labor + rates.delivery
    sale = xround(total_cogs / (1 - rates.margin), 0) if rates.margin < 1 else 0.0

    return PlanPrice(
        scenario=scenario.name, price_group=price_group, lines=priced,
        cabinet_list=cabinet_list, cabinet_cost=cabinet_cost,
        hardware_cost=hardware_cost, total_materials=total_materials,
        tax=tax, freight=freight, materials_with_tax_freight=materials2,
        assembly=assembly, install=install, hardware_labor=hardware_labor,
        total_labor=total_labor, delivery=rates.delivery, total_cogs=total_cogs,
        margin=rates.margin, sale_price=sale, profit=sale - total_cogs,
    )


def compare(a: PlanPrice, b: PlanPrice) -> dict:
    """Two scenarios on one plan, for the savings view. `b` is the proposal."""
    def delta(x, y):
        return {"a": x, "b": y, "delta": y - x,
                "pct": ((y - x) / x * 100) if x else 0.0}

    return {
        "scenario_a": a.scenario,
        "scenario_b": b.scenario,
        "price_group": a.price_group,
        "stocked_lines": b.stocked_lines,
        "line_count": len(b.lines),
        # A group 2-5 plan cannot benefit — say so rather than showing a flat
        # zero and letting someone hunt for the missing discount.
        "stocking_applies": a.price_group in STOCKABLE_GROUPS,
        "cabinet_cost": delta(a.cabinet_cost, b.cabinet_cost),
        "total_cogs": delta(a.total_cogs, b.total_cogs),
        "sale_price": delta(a.sale_price, b.sale_price),
        "profit": delta(a.profit, b.profit),
    }
