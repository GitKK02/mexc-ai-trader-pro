from decimal import Decimal
from app.models import Signal
from app.volatility_guard import VolatilityLiquidityGuard

class Settings:
    volatility_guard_panic_atr_percent = 5.0
    volatility_guard_extreme_move_percent = 3.0
    volatility_guard_max_spread_percent = 0.15
    volatility_guard_min_relative_volume = 0.60
    volatility_guard_low_liquidity_turnover_usdt = 20_000_000
    volatility_guard_block_panic = True
    volatility_guard_block_low_liquidity = True
    volatility_guard_reduce_risk_high_vol_multiplier = 0.50
    volatility_guard_reduce_risk_wide_spread_multiplier = 0.60
    volatility_guard_reduce_risk_low_volume_multiplier = 0.70

def sig(atr=1.0, volume=1.0, momentum=0.5):
    return Signal(
        symbol="BTC_USDT", side="LONG", score=90,
        entry=100, stop_loss=99, tp1=101, tp2=102,
        atr=1, reasons=["test"],
        diagnostics={
            "primary_atr_percent": atr,
            "primary_relative_volume": volume,
            "primary_momentum_percent": momentum,
        },
    )

def test_normal_market_allowed():
    r = VolatilityLiquidityGuard(Settings()).evaluate(
        sig(), turnover_24h=Decimal("100000000"),
        spread_percent=Decimal("0.05"),
    )
    assert r.allowed is True
    assert r.risk_multiplier == Decimal("1")

def test_panic_blocked():
    r = VolatilityLiquidityGuard(Settings()).evaluate(
        sig(atr=6), turnover_24h=Decimal("100000000"),
        spread_percent=Decimal("0.05"),
    )
    assert r.allowed is False
    assert r.volatility_state == "PANIC"

def test_wide_spread_reduces():
    r = VolatilityLiquidityGuard(Settings()).evaluate(
        sig(), turnover_24h=Decimal("100000000"),
        spread_percent=Decimal("0.20"),
    )
    assert r.allowed is True
    assert r.risk_multiplier == Decimal("0.60")

def test_low_turnover_blocked():
    r = VolatilityLiquidityGuard(Settings()).evaluate(
        sig(), turnover_24h=Decimal("1000000"),
        spread_percent=Decimal("0.05"),
    )
    assert r.allowed is False
    assert r.liquidity_state == "LOW"
