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
    for previous, current in zip(values[-period - 1 : -1], values[-period:]):
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
    previous_close = candles[-period - 1]["close"]
    for candle in candles[-period:]:
        high = candle["high"]
        low = candle["low"]
        ranges.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )
        previous_close = candle["close"]
    return mean(ranges)


def adx(candles: list[dict], period: int = 14) -> float:
    if len(candles) <= period * 2:
        raise ValueError("not enough candles")
    plus_dm = []
    minus_dm = []
    true_ranges = []
    for previous, current in zip(candles[:-1], candles[1:]):
        up_move = current["high"] - previous["high"]
        down_move = previous["low"] - current["low"]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        true_ranges.append(
            max(
                current["high"] - current["low"],
                abs(current["high"] - previous["close"]),
                abs(current["low"] - previous["close"]),
            )
        )

    tr = sum(true_ranges[-period:])
    if tr == 0:
        return 0.0
    plus_di = 100 * sum(plus_dm[-period:]) / tr
    minus_di = 100 * sum(minus_dm[-period:]) / tr
    denominator = plus_di + minus_di
    if denominator == 0:
        return 0.0
    return 100 * abs(plus_di - minus_di) / denominator


def bollinger_width(values: list[float], period: int = 20) -> float:
    if len(values) < period:
        raise ValueError("not enough values")
    window = values[-period:]
    center = mean(window)
    variance = sum((value - center) ** 2 for value in window) / period
    deviation = variance ** 0.5
    if center == 0:
        return 0.0
    return ((4 * deviation) / center) * 100


def market_structure(candles: list[dict], lookback: int = 12) -> str:
    if len(candles) < lookback + 2:
        return "UNKNOWN"
    recent = candles[-lookback:]
    midpoint = lookback // 2
    first = recent[:midpoint]
    second = recent[midpoint:]
    first_high = max(item["high"] for item in first)
    first_low = min(item["low"] for item in first)
    second_high = max(item["high"] for item in second)
    second_low = min(item["low"] for item in second)

    if second_high > first_high and second_low > first_low:
        return "BULLISH"
    if second_high < first_high and second_low < first_low:
        return "BEARISH"
    return "RANGE"
