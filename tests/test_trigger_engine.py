from app.config import Settings
from app.models import Signal
from app.trigger_engine import TriggerEngine


def make_signal(**overrides) -> Signal:
    values = dict(
        symbol="SOL_USDT", side="LONG", score=82, entry=101.0,
        stop_loss=98.0, tp1=104.0, tp2=107.0, atr=1.0, reasons=[],
        opportunity_stage="CHARGED", opportunity_state="WATCH",
        prediction_score=82, breakout_readiness=84,
        false_breakout_risk=20, prediction_state="READY",
        entry_timing="GOOD",
        diagnostics={"primary_relative_volume": 1.10,
                     "primary_momentum_percent": 0.30,
                     "primary_breakout_level": 100.0},
    )
    values.update(overrides)
    return Signal(**values)


def test_first_ready_observation_is_armed_not_triggered():
    engine = TriggerEngine(Settings())
    signal = engine.attach(make_signal())
    assert signal.trigger_state == "ARMED"
    assert signal.trigger_confirmed is False


def test_second_accelerating_observation_can_trigger():
    engine = TriggerEngine(Settings())
    engine.attach(make_signal(entry=100.02, prediction_score=78, diagnostics={
        "primary_relative_volume": 0.95,
        "primary_momentum_percent": 0.20,
        "primary_breakout_level": 100.0,
    }))
    signal = engine.attach(make_signal())
    assert signal.trigger_state == "TRIGGERED"
    assert signal.trigger_confirmed is True
    assert signal.trigger_type in {"BREAKOUT", "MOMENTUM_RELEASE"}


def test_invalidated_prediction_never_triggers():
    engine = TriggerEngine(Settings())
    signal = engine.attach(make_signal(prediction_state="INVALIDATED"))
    assert signal.trigger_state == "INVALIDATED"
    assert signal.trigger_confirmed is False


def test_short_direction_uses_signed_momentum():
    engine = TriggerEngine(Settings())
    first = make_signal(symbol="ETH_USDT", side="SHORT", entry=99.98,
        prediction_score=78, diagnostics={
            "primary_relative_volume": 0.95,
            "primary_momentum_percent": -0.20,
            "primary_breakout_level": 100.0})
    second = make_signal(symbol="ETH_USDT", side="SHORT", entry=99.0,
        diagnostics={"primary_relative_volume": 1.15,
                     "primary_momentum_percent": -0.35,
                     "primary_breakout_level": 100.0})
    engine.attach(first)
    result = engine.attach(second)
    assert result.trigger_state == "TRIGGERED"
