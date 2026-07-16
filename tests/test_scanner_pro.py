from app.analyzer import analyze_timeframe, combine_timeframes


def trend_candles(direction: int, count: int = 240):
    candles = []
    price = 100.0
    for index in range(count):
        price += direction * 0.25
        candles.append(
            {
                "open": price - direction * 0.10,
                "high": price + 0.30,
                "low": price - 0.30,
                "close": price,
                "volume": 100 + index,
            }
        )
    return candles


def test_bullish_multitimeframe_signal():
    analyses = {}
    for timeframe in ["Min5", "Min15", "Min60", "Hour4"]:
        result = analyze_timeframe(
            timeframe,
            trend_candles(1),
            min_relative_volume=0.5,
            require_volume_confirmation=False,
        )
        assert result is not None
        analyses[timeframe] = result

    signal = combine_timeframes(
        "BTC_USDT",
        analyses,
        "BULLISH",
    )
    assert signal is not None
    assert signal.side == "LONG"
    assert signal.score >= 70
    assert signal.atr > 0


def test_bearish_multitimeframe_signal():
    analyses = {}
    for timeframe in ["Min5", "Min15", "Min60", "Hour4"]:
        result = analyze_timeframe(
            timeframe,
            trend_candles(-1),
            min_relative_volume=0.5,
            require_volume_confirmation=False,
        )
        assert result is not None
        analyses[timeframe] = result

    signal = combine_timeframes(
        "ETH_USDT",
        analyses,
        "BEARISH",
    )
    assert signal is not None
    assert signal.side == "SHORT"
