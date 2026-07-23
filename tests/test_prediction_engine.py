from app.config import Settings
from app.models import Signal
from app.prediction_engine import PredictionEngine


def signal(**changes) -> Signal:
    base = dict(
        symbol="SOL_USDT",
        side="LONG",
        score=82,
        entry=100.0,
        stop_loss=98.0,
        tp1=102.0,
        tp2=104.0,
        atr=1.0,
        reasons=[],
        entry_quality_score=80,
        entry_timing="GOOD",
        confluence_score=85,
        relative_strength_score=84,
        market_intelligence_score=82,
        energy_score=88,
        opportunity_score=86,
        opportunity_stage="CHARGED",
        opportunity_state="WATCH",
        diagnostics={
            "primary_momentum_percent": 0.55,
            "primary_relative_volume": 1.25,
            "primary_volume_building_ratio": 1.30,
            "primary_atr_compression_ratio": 0.68,
            "primary_range_compression_ratio": 0.66,
            "primary_ema_compression_percent": 0.15,
            "primary_vwap_distance_percent": 0.18,
            "primary_impulse_candles": 1,
            "primary_adx": 24,
            "agreement": 4,
        },
    )
    base.update(changes)
    return Signal(**base)


def test_charged_watch_setup_becomes_ready() -> None:
    item = PredictionEngine(Settings()).attach(signal())
    assert item.prediction_state == "READY"
    assert item.prediction_score >= 76
    assert item.breakout_readiness >= 72
    assert item.false_breakout_risk <= 42


def test_released_setup_is_invalidated() -> None:
    item = PredictionEngine(Settings()).attach(
        signal(
            opportunity_stage="RELEASED",
            opportunity_state="RELEASED",
            entry_timing="CHASE",
            diagnostics={
                **signal().diagnostics,
                "primary_momentum_percent": 2.6,
                "primary_impulse_candles": 4,
            },
        )
    )
    assert item.prediction_state == "INVALIDATED"
    assert item.false_breakout_risk >= 68


def test_opposite_pressure_increases_false_breakout_risk() -> None:
    engine = PredictionEngine(Settings())
    aligned = engine.evaluate(signal())
    opposed = engine.evaluate(
        signal(
            diagnostics={
                **signal().diagnostics,
                "primary_momentum_percent": -0.8,
                "primary_vwap_distance_percent": -0.6,
            }
        )
    )
    assert opposed.false_breakout_risk > aligned.false_breakout_risk


def test_prediction_is_execution_neutral() -> None:
    item = PredictionEngine(Settings()).attach(signal())
    assert item.prediction_state == "READY"
    assert item.decision_action == "WAIT"
