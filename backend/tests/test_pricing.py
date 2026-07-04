from decimal import Decimal

from app.pricing import DEALER_MULTIPLIER, is_excluded, line_total, money, net_each


def test_multiplier_value():
    assert DEALER_MULTIPLIER == Decimal("0.217")


def test_net_each_rounds_half_up():
    # 100.00 * 0.217 = 21.70 exactly
    assert net_each(Decimal("100.00")) == Decimal("21.70")
    # 461.75 * 0.217 = 100.19975 -> 100.20
    assert net_each(Decimal("461.75")) == Decimal("100.20")


def test_line_total_uses_rounded_each():
    # each = 21.7, x3 = 65.10 (rounding happens per-each like the paper form)
    assert line_total(Decimal("100.00"), 3) == Decimal("65.10")


def test_excluded_skus():
    assert is_excluded("RANGE1.30")
    assert is_excluded(" dishw24 ")  # case/whitespace insensitive
    assert is_excluded("REF.2D.36")
    assert not is_excluded("B18")


def test_money_rounding():
    assert money("2.005") == Decimal("2.01")
    assert money("2.004") == Decimal("2.00")
