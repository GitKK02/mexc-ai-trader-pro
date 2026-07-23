from app.config import Settings
from app.models import Signal
from app.opportunity_engine import HeatQueue, OpportunityEngine


def make_signal(**overrides) -> Signal:
    values = dict(
        symbol="SOL_USDT",
        side="LONG",
        score=78,
        entry=100.0,
        stop_loss=98.0,
        tp1=102.0,
        tp2=104.0,
        atr=1.0,
        reasons=[],
        entry_quality_score=76,
        confluence_score=82,
        market_intelligence_score=80,
        relative_strength_score=84,
        entry_timing="GOOD",
        diagnostics={
            "primary_atr_compression_ratio": 0.68,
            "primary_ema_compression_percent": 0.25,
            "primary_range_compression_ratio": 0.65,
            "primary_volume_building_ratio": 1.35,
            "primary_vwap_distance_percent": 0.15,
            "primary_momentum_percent": 0.65,
            "agreement": 4,
        },
    )
    values.update(overrides)
    return Signal(**values)


def test_charged_setup_becomes_watch_and_hot() -> None:
    engine = OpportunityEngine(Settings())
    signal = engine.attach(make_signal())
    assert signal.energy_score is not None and signal.energy_score >= 78
    assert signal.opportunity_state == "WATCH"
    assert signal.opportunity_stage == "CHARGED"
    assert signal.opportunity_heat == "HOT"
    assert engine.heat_queue.snapshot()[0].symbol == "SOL_USDT"


def test_released_impulse_is_not_watchlisted() -> None:
    engine = OpportunityEngine(Settings())
    signal = engine.attach(
        make_signal(
            entry_timing="LATE",
            diagnostics={
                **make_signal().diagnostics,
                "primary_momentum_percent": 2.2,
            },
        )
    )
    assert signal.opportunity_stage == "RELEASED"
    assert signal.opportunity_state == "RELEASED"
    assert signal.opportunity_heat == "COLD"
    assert engine.heat_queue.snapshot() == []


def test_heat_queue_is_bounded_and_sorted() -> None:
    queue = HeatQueue(max_items=2)
    engine = OpportunityEngine(Settings())
    for symbol, score in (("A_USDT", 70), ("B_USDT", 90), ("C_USDT", 80)):
        signal = make_signal(symbol=symbol, score=score)
        assessment = engine.evaluate(signal)
        assessment.opportunity_score = score
        assessment.energy_score = score
        assessment.heat = "HOT"
        queue.update(assessment, symbol)
    assert [item.symbol for item in queue.snapshot()] == ["B_USDT", "C_USDT"]


def test_cold_setup_removed_from_queue() -> None:
    queue = HeatQueue(max_items=5)
    engine = OpportunityEngine(Settings())
    assessment = engine.evaluate(make_signal())
    assessment.heat = "HOT"
    queue.update(assessment, "SOL_USDT")
    assessment.heat = "COLD"
    queue.update(assessment, "SOL_USDT")
    assert queue.snapshot() == []
