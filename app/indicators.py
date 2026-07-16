from statistics import mean


def ema(values: list[float], period: int) -> float:
    if len(values) < period:
        raise ValueError("not enough values")
    multiplier = 2 / (period + 1)
    current = mean(values[:period])
    for value in values[period:]:
        current = (value - current) * multiplier + current
    return current


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        raise ValueError("not enough values")
    gains = []
    losses = []
    for previous, current in zip(values[-period-1:-1], values[-period:]):
        delta = current - previous
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = mean(gains)
    avg_loss = mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(candles: list[dict], period: int = 14) -> float:
    if len(candles) <= period:
        raise ValueError("not enough candles")
    ranges: list[float] = []
    previous_close = candles[-period-1]["close"]
    for candle in candles[-period:]:
        high = candle["high"]
        low = candle["low"]
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = candle["close"]
    return mean(ranges)
