"""All pricing rules for the CKB Pricing Platform live here.

Mirrors CabinetTron's conventions (backend/app/pricing.py in cabinet-management):
dealer cost = list price x multiplier, appliance placeholder SKUs are excluded
from supplier totals but stay visible on the drawing.
"""

from decimal import ROUND_HALF_UP, Decimal

# Default Everluxe multiplier when a job has no override: the retail tier
# (0.24 / 11.8% freight). DRH/Century jobs get 0.21/10% set explicitly.
DEFAULT_MULTIPLIER = Decimal("0.24")

# Default sell margin when a job prices by margin instead of a plan/bid price.
DEFAULT_MARGIN_PCT = Decimal("40")

# Appliance placeholders that appear on cabinet drawings but are never ordered.
EXCLUDED_SKUS = {"RANGE1.30", "REF.2D.36", "DISHW24"}

# --- DRH pricing-matrix rates (Pricing Sheet header constants, 021126 workbook).
# All overridable per-key in Settings; these are the workbook's values.
MATRIX_DEFAULTS = {
    "drh_multiplier": "0.21",     # $D$2 — cabinet cost = list x this (DRH + Century)
    "freight_pct": "0.10",        # $G$2 — freight = cabinet cost x this (DRH + Century)
    "retail_multiplier": "0.24",  # everyone else
    "retail_freight_pct": "0.118",  # everyone else
    "tax_pct": "0.07",            # $D$4 — sales tax on (cabinet cost + hardware material)
    "assem_rate": "10",           # $J$2 — assembly $ per unit
    "install_rate": "25",         # $J$3 — install $ per unit
    "knob_material": "1.25",      # $E$5 — KNB cost each
    "handle_material": "2.60",    # $E$6 — HNDL cost each
    "knob_labor": "1",            # $J$4 — knob install $ per piece
    "handle_labor": "2",          # $J$5 — handle install $ per piece
    "delivery": "0",              # $G$3
    "national_margin": "15",      # $G$4 — default margin for national builder pricing
    # Top Pricing Sheet rates (DR Horton tier; rate is per-plan overridable)
    "top_rate": "26",             # $/sqft charge rate — already the selling rate
    "top_k_sink": "60",           # kitchen sink each
    "top_v_sink": "25",           # vanity sink each
    "top_cutout": "40",           # sink cutout each (kitchen or vanity)
}

_CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def net_each(list_price: Decimal, multiplier: Decimal) -> Decimal:
    return money(list_price * multiplier)


def line_cost(list_price: Decimal, qty: int, multiplier: Decimal) -> Decimal:
    return money(net_each(list_price, multiplier) * qty)


def sell_from_margin(cost: Decimal, margin_pct: Decimal) -> Decimal:
    """Sell = cost / (1 - margin%). Margin is on sell, not markup on cost."""
    pct = Decimal(margin_pct) / Decimal("100")
    if pct >= 1:
        raise ValueError("margin_pct must be below 100")
    return money(Decimal(cost) / (Decimal("1") - pct))


def is_excluded(sku: str) -> bool:
    return sku.strip().upper() in EXCLUDED_SKUS
