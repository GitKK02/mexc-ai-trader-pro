from decimal import Decimal

from app.position_intelligence import DynamicPositionManager


class Settings:
    position_intelligence_tp1_r = 1.0
    position_intelligence_breakeven_r = 1.0
    position_intelligence_trail_start_r = 1.5
    position_intelligence_exit_r = -1.0


def long_position():
    return {
        "positionId": 1,
        "symbol": "BTC_USDT",
        "positionType": 1,
        "holdAvgPrice": "100",
    }


def protection():
    return [
        {
            "positionId": 1,
            "stopLossPrice": "98",
            "takeProfitPrice": "104",
        }
    ]


def test_long_half_r_is_hold():
    plan = DynamicPositionManager(Settings()).evaluate(
        long_position(),
        Decimal("101"),
        protection(),
    )
    assert plan.action == "HOLD"
    assert plan.current_r == Decimal("0.5")


def test_long_one_r_is_breakeven_review():
    plan = DynamicPositionManager(Settings()).evaluate(
        long_position(),
        Decimal("102"),
        protection(),
    )
    assert plan.action == "BREAKEVEN_REVIEW"
    assert plan.current_r == Decimal("1")


def test_long_two_r_is_trail_review():
    plan = DynamicPositionManager(Settings()).evaluate(
        long_position(),
        Decimal("104"),
        protection(),
    )
    assert plan.action == "TRAIL_REVIEW"
    assert plan.current_r == Decimal("2")


def test_missing_protection_is_critical():
    plan = DynamicPositionManager(Settings()).evaluate(
        long_position(),
        Decimal("101"),
        [],
    )
    assert plan.action == "PROTECTION_MISSING"
    assert plan.confidence == "HIGH"


def test_short_r_calculation():
    position = {
        "positionId": 2,
        "symbol": "ETH_USDT",
        "positionType": 2,
        "holdAvgPrice": "100",
    }
    orders = [
        {
            "positionId": 2,
            "stopLossPrice": "102",
            "takeProfitPrice": "96",
        }
    ]
    plan = DynamicPositionManager(Settings()).evaluate(
        position,
        Decimal("98"),
        orders,
    )
    assert plan.current_r == Decimal("1")
    assert plan.action == "BREAKEVEN_REVIEW"
