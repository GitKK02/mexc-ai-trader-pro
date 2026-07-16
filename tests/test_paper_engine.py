from pathlib import Path

from app.database import Database
from app.models import Signal
from app.paper_engine import PaperEngine


class FakeSettings:
    paper_initial_balance_usdt = 10000.0
    risk_per_trade_percent = 0.5
    max_positions = 2
    paper_slippage_percent = 0.0
    paper_taker_fee_percent = 0.0
    max_leverage = 3
    tp1_close_percent = 35.0
    tp2_close_percent = 35.0
    breakeven_buffer_percent = 0.03
    trailing_atr_multiplier = 1.8


def signal() -> Signal:
    return Signal("BTC_USDT", "LONG", 80, 100.0, 98.0, 102.0, 104.0, 1.0, ["test"])


def test_open_position_risks_half_percent(tmp_path: Path):
    db = Database(str(tmp_path / "test.db"))
    engine = PaperEngine(FakeSettings(), db)
    position = engine.open_from_signal(signal())
    assert round(position.risk_amount, 2) == 50.0
    assert round(position.initial_quantity, 2) == 25.0


def test_tp1_moves_stop_to_breakeven(tmp_path: Path):
    db = Database(str(tmp_path / "test.db"))
    engine = PaperEngine(FakeSettings(), db)
    position = engine.open_from_signal(signal())
    events = engine.update_price(position, 102.0)
    updated = db.position(position.id)
    assert events[0].kind == "TP1"
    assert updated is not None and updated.tp1_done
    assert updated.stop_loss > updated.entry_price


def test_stop_closes_position(tmp_path: Path):
    db = Database(str(tmp_path / "test.db"))
    engine = PaperEngine(FakeSettings(), db)
    position = engine.open_from_signal(signal())
    events = engine.update_price(position, 97.0)
    updated = db.position(position.id)
    assert events[0].kind == "CLOSED"
    assert updated is not None and updated.status == "CLOSED"
