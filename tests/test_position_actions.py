from decimal import Decimal

import pytest

from app.position_actions import floor_step


def test_floor_step():
    assert floor_step(
        Decimal("100.037"),
        Decimal("0.01"),
    ) == Decimal("100.03")


def test_long_breakeven_math():
    entry = Decimal("100")
    buffer_fraction = Decimal("0.03") / Decimal("100")
    proposed = floor_step(
        entry * (Decimal("1") + buffer_fraction),
        Decimal("0.01"),
    )
    assert proposed == Decimal("100.03")


def test_short_breakeven_math():
    entry = Decimal("100")
    buffer_fraction = Decimal("0.03") / Decimal("100")
    proposed = floor_step(
        entry * (Decimal("1") - buffer_fraction),
        Decimal("0.01"),
    )
    assert proposed == Decimal("99.97")
