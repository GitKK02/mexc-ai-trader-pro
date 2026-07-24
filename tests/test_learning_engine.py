from pathlib import Path

from app.learning_engine import LearningEngine
from app.models import PaperPosition, Signal


def signal() -> Signal:
    return Signal(
        symbol="SOL_USDT", side="LONG", score=84, entry=100.0,
        stop_loss=98.0, tp1=102.0, tp2=104.0, atr=1.0,
        reasons=["test"], prediction_score=82, prediction_state="READY",
        trigger_score=80, trigger_state="TRIGGERED", trigger_confirmed=True,
        market_opportunity_score=90, market_opportunity_rank=1,
        decision_score=86, decision_action="CONFIRM",
    )


def position(position_id: int = 1, pnl: float = 5.0, fees: float = 1.0) -> PaperPosition:
    return PaperPosition(
        id=position_id, symbol="SOL_USDT", side="LONG", status="CLOSED",
        entry_price=100.0, current_price=104.0, initial_quantity=1.0,
        remaining_quantity=0.0, stop_loss=98.0, initial_stop_loss=98.0,
        tp1=102.0, tp2=104.0, atr=1.0, leverage=3, risk_amount=2.0,
        realized_pnl=pnl, fees=fees, tp1_done=True, tp2_done=True,
        highest_price=104.0, lowest_price=99.0, opened_at="2026-01-01T00:00:00+00:00",
        closed_at="2026-01-01T01:00:00+00:00", close_reason="TP2",
    )


def test_records_links_and_syncs_outcome(tmp_path: Path):
    engine = LearningEngine(str(tmp_path / "learning.db"))
    item = signal()
    engine.record_signal(item)
    closed = position()
    engine.attach_paper_position(item, closed)
    assert engine.sync_closed_positions([closed]) == 1
    summary = engine.summary()
    assert summary.total_samples == 1
    assert summary.closed_samples == 1
    assert summary.wins == 1
    assert summary.average_pnl == 4.0


def test_disabled_engine_is_noop(tmp_path: Path):
    engine = LearningEngine(str(tmp_path / "learning.db"), enabled=False)
    assert engine.record_signal(signal()) is None
    assert engine.summary().total_samples == 0


def test_best_setup_needs_three_samples(tmp_path: Path):
    engine = LearningEngine(str(tmp_path / "learning.db"))
    for idx in range(1, 4):
        item = signal()
        engine.record_signal(item)
        closed = position(idx)
        engine.attach_paper_position(item, closed)
        engine.sync_closed_positions([closed])
    assert "READY→TRIGGERED" in engine.summary().best_setup
