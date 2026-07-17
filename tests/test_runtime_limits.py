from app.live_database import LiveDatabase


def test_trade_limit_defaults_to_config(tmp_path):
    db = LiveDatabase(str(tmp_path / "trades.db"))
    assert db.effective_trade_limit(4) == 4


def test_zero_trade_limit_means_unlimited(tmp_path):
    db = LiveDatabase(str(tmp_path / "trades.db"))
    db.set_control("live_max_trades_per_day", "0")
    assert db.effective_trade_limit(4) == 0


def test_runtime_trade_limit_persists(tmp_path):
    path = str(tmp_path / "trades.db")
    first = LiveDatabase(path)
    first.set_control("live_max_trades_per_day", "12")
    second = LiveDatabase(path)
    assert second.effective_trade_limit(4) == 12


def test_runtime_daily_loss_limit(tmp_path):
    db = LiveDatabase(str(tmp_path / "trades.db"))
    db.set_control("live_daily_loss_limit_usdt", "25.5")
    assert db.effective_daily_loss_limit(10) == 25.5


def test_invalid_runtime_value_falls_back(tmp_path):
    db = LiveDatabase(str(tmp_path / "trades.db"))
    db.set_control("live_max_trades_per_day", "invalid")
    assert db.effective_trade_limit(7) == 7
