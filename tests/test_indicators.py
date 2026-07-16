from app.indicators import atr, ema, rsi


def test_ema_returns_number():
    values = [float(i) for i in range(1, 80)]
    assert ema(values, 20) > 0


def test_rsi_uptrend_is_high():
    values = [float(i) for i in range(1, 40)]
    assert rsi(values) > 70


def test_atr_returns_positive():
    candles = [
        {"high": float(i + 2), "low": float(i), "close": float(i + 1)}
        for i in range(1, 40)
    ]
    assert atr(candles) > 0
