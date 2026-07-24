from types import SimpleNamespace

from app.entry_optimizer import EntryOptimizer
from app.models import Signal


def settings():
    return SimpleNamespace(
        entry_optimizer_pullback_atr=0.25,
        entry_optimizer_zone_half_atr=0.12,
        entry_optimizer_skip_distance_atr=0.90,
        entry_optimizer_max_impulse_candles=4,
        entry_optimizer_chase_momentum_percent=1.80,
        entry_optimizer_max_vwap_distance_percent=1.20,
        entry_optimizer_invalidation_risk=70,
        entry_optimizer_ttl_candles=3,
    )


def make_signal(entry=100.25, trigger_confirmed=True):
    return Signal(
        symbol="BTC_USDT",
        side="LONG",
        score=88,
        entry=entry,
        stop_loss=98.5,
        tp1=102.0,
        tp2=104.0,
        atr=1.0,
        reasons=[],
        diagnostics={
            "primary_ema20": 99.8,
            "primary_breakout_level": 100.0,
            "primary_vwap_distance_percent": 0.2,
            "primary_momentum_percent": 0.7,
            "primary_impulse_candles": 1,
            "primary_relative_volume": 1.3,
        },
        entry_quality_score=88,
        entry_timing="GOOD",
        entry_allowed=True,
        prediction_score=84,
        prediction_state="READY",
        false_breakout_risk=25,
        trigger_score=86,
        trigger_state="TRIGGERED" if trigger_confirmed else "ARMED",
        trigger_confirmed=trigger_confirmed,
    )


def test_enter_now_inside_zone_with_confirmed_trigger():
    result = EntryOptimizer(settings()).evaluate(make_signal())
    assert result.action == "ENTER_NOW"
    assert result.allowed_now is True
    assert result.zone_low <= 100.25 <= result.zone_high


def test_wait_retest_without_confirmed_trigger():
    result = EntryOptimizer(settings()).evaluate(
        make_signal(trigger_confirmed=False)
    )
    assert result.action == "WAIT_RETEST"
    assert result.allowed_now is False
    assert result.ttl_candles == 3


def test_extended_price_is_skip_chase():
    item = make_signal(entry=101.4)
    item.entry_timing = "CHASE"
    item.entry_allowed = False
    result = EntryOptimizer(settings()).evaluate(item)
    assert result.action == "SKIP_CHASE"
    assert result.ttl_candles == 0


def test_high_false_breakout_risk_invalidates_setup():
    item = make_signal()
    item.false_breakout_risk = 80
    result = EntryOptimizer(settings()).evaluate(item)
    assert result.action == "INVALID"
    assert result.allowed_now is False
