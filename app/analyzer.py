from app.indicators import atr, ema, rsi
from app.models import Signal


def analyze(symbol: str, candles: list[dict]) -> Signal | None:
    if len(candles) < 60:
        return None

    closes = [item["close"] for item in candles]
    volumes = [item["volume"] for item in candles]
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    current_rsi = rsi(closes)
    current_atr = atr(candles)
    last = closes[-1]
    average_volume = sum(volumes[-21:-1]) / 20
    relative_volume = volumes[-1] / average_volume if average_volume else 0

    reasons: list[str] = []
    score = 0
    side = ""
    if last > ema20 > ema50:
        side = "LONG"
        score += 40
        reasons.append("цена и EMA подтверждают восходящее направление")
    elif last < ema20 < ema50:
        side = "SHORT"
        score += 40
        reasons.append("цена и EMA подтверждают нисходящее направление")
    else:
        return None

    if 38 <= current_rsi <= 68:
        score += 20
        reasons.append("RSI без экстремальной перегретости")
    if relative_volume >= 1.1:
        score += 20
        reasons.append("объём выше среднего")

    momentum = (closes[-1] - closes[-5]) / closes[-5] * 100
    if (side == "LONG" and momentum > 0) or (side == "SHORT" and momentum < 0):
        score += 20
        reasons.append("краткосрочный импульс совпадает с направлением")

    stop_distance = max(current_atr * 1.5, last * 0.004)
    if side == "LONG":
        stop = last - stop_distance
        tp1 = last + stop_distance
        tp2 = last + stop_distance * 2
    else:
        stop = last + stop_distance
        tp1 = last - stop_distance
        tp2 = last - stop_distance * 2

    return Signal(symbol, side, min(score, 100), last, stop, tp1, tp2, current_atr, reasons)
