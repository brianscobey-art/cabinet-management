"""All pricing rules live here (spec §8) — multiplier, SKU exclusions, GM floor.

Change rules in this one module only; nothing else hardcodes pricing.
"""

from decimal import ROUND_HALF_UP, Decimal

# Dealer cost = list price x this multiplier (spec §4/§5.1).
DEALER_MULTIPLIER = Decimal("0.217")

# Brian's standing exclusions: appliance placeholders that appear on cabinet
# drawings but are never ordered from the cabinet supplier.
EXCLUDED_SKUS = {"RANGE1.30", "REF.2D.36", "DISHW24"}

# Gross-margin floor — not yet defined by the business; enforce once set.
GM_FLOOR: Decimal | None = None

_CENT = Decimal("0.01")


def money(value: Decimal | float | str) -> Decimal:
    """Round to cents, half up (matches how the paper forms are figured)."""
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def net_each(list_price: Decimal, multiplier: Decimal = DEALER_MULTIPLIER) -> Decimal:
    return money(list_price * multiplier)


def line_total(list_price: Decimal, qty: int, multiplier: Decimal = DEALER_MULTIPLIER) -> Decimal:
    return money(net_each(list_price, multiplier) * qty)


def is_excluded(sku: str) -> bool:
    """True for SKUs that must never go on a supplier order."""
    return sku.strip().upper() in EXCLUDED_SKUS
