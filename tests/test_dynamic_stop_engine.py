from types import SimpleNamespace

from app.dynamic_stop_engine import DynamicStopEngine
from app.models import Signal


def settings(**overrides):
    values = dict(
        dynamic_stop_structure_buffer_atr=0.18,
        dynamic_stop_atr_multiplier=1.20,
        dynamic_stop_ema_buffer_atr=0.15,
        dynamic_stop_vwap_buffer_atr=0.12,
        dynamic_stop_min_distance_atr=0.55,
        dynamic_stop_max_distance_atr=2.20,
        dynamic_stop_min_rr_tp1=0.70,
        dynamic_stop_enforced=True,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def signal(side="LONG"):
    entry = 100.0
    return Signal(
        symbol="TEST_USDT", side=side, score=90, entry=entry,
        stop_loss=98.5 if side == "LONG" else 101.5,
        tp1=102.0 if side == "LONG" else 98.0,
        tp2=104.0 if side == "LONG" else 96.0,
        atr=1.0, reasons=[],
        diagnostics={
            "primary_breakout_level": 99.4 if side == "LONG" else 100.6,
            "primary_ema20": 99.2 if side == "LONG" else 100.8,
            "primary_ema50": 98.8 if side == "LONG" else 101.2,
            "primary_vwap_distance_percent": 0.5 if side == "LONG" else -0.5,
        },
    )


def test_long_stop_is_below_entry_and_explainable():
    result = DynamicStopEngine(settings()).assess(signal("LONG"))
    assert result.price < 100
    assert result.strategy in {"STRUCTURE", "ATR", "EMA", "VWAP"}
    assert result.distance_atr >= 0.55
    assert result.allowed is True


def test_short_stop_is_above_entry():
    result = DynamicStopEngine(settings()).assess(signal("SHORT"))
    assert result.price > 100
    assert result.distance_atr >= 0.55


def test_low_reward_blocks_recommendation():
    item = signal("LONG")
    item.tp1 = 100.1
    result = DynamicStopEngine(settings()).assess(item)
    assert result.allowed is False
    assert any("RR" in reason for reason in result.reasons)


def test_attach_updates_signal_stop_when_allowed():
    item = signal("LONG")
    original = item.stop_loss
    attached = DynamicStopEngine(settings()).attach(item)
    assert attached.dynamic_stop_score is not None
    assert attached.stop_loss != original
    assert attached.dynamic_stop_candidates
