from types import SimpleNamespace

from app.entry_intelligence import EntryIntelligence
from app.models import Signal


def settings():
    return SimpleNamespace(
        entry_max_impulse_candles=3,
        entry_high_momentum_percent=1.5,
        entry_min_remaining_tp1_r=0.7,
        entry_max_distance_atr=0.9,
        entry_max_distance_percent=1.2,
        entry_late_distance_atr=0.6,
        entry_chase_guard_enabled=True,
    )


def make_signal(entry=100.2, breakout=100.0, atr=1.0, tp1=101.5):
    return Signal(
        symbol="BTC_USDT",
        side="LONG",
        score=90,
        entry=entry,
        stop_loss=99.0,
        tp1=tp1,
        tp2=103.0,
        atr=atr,
        reasons=[],
        diagnostics={
            "primary_ema20": 99.8,
            "primary_breakout_level": breakout,
            "primary_momentum_percent": 0.7,
            "primary_impulse_candles": 1,
            "primary_relative_volume": 1.3,
        },
    )


def test_good_entry_near_breakout_is_allowed():
    result = EntryIntelligence(settings()).evaluate(make_signal())
    assert result.timing == "GOOD"
    assert result.allowed is True
    assert result.score >= 60


def test_extended_entry_is_blocked_as_chase():
    result = EntryIntelligence(settings()).evaluate(
        make_signal(entry=101.2, breakout=100.0, atr=1.0, tp1=101.5)
    )
    assert result.timing == "CHASE"
    assert result.allowed is False


def test_pullback_can_be_early_not_chase():
    result = EntryIntelligence(settings()).evaluate(
        make_signal(entry=99.7, breakout=100.0, atr=1.0, tp1=101.5)
    )
    assert result.timing == "EARLY"
    assert result.allowed is True
