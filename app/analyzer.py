from dataclasses import dataclass

from app.indicators import (
    adx,
    atr,
    bollinger_width,
    ema,
    market_structure,
    rsi,
)
from app.models import Signal


@dataclass(slots=True)
class TimeframeAnalysis:
    timeframe: str
    side: str
    score: int
    regime: str
    structure: str
    ema20: float
    ema50: float
    ema200: float
    rsi: float
    atr_value: float
    atr_percent: float
    adx: float
    relative_volume: float
    momentum_percent: float
    bollinger_width_percent: float
    latest_close: float
    reasons: list[str]


def analyze_timeframe(
    timeframe: str,
    candles: list[dict],
    *,
    min_relative_volume: float,
    require_volume_confirmation: bool,
) -> TimeframeAnalysis | None:
    if len(candles) < 210:
        return None

    closes = [item["close"] for item in candles]
    volumes = [item["volume"] for item in candles]
    last = closes[-1]
    ema20_value = ema(closes, 20)
    ema50_value = ema(closes, 50)
    ema200_value = ema(closes, 200)
    rsi_value = rsi(closes)
    atr_value = atr(candles)
    atr_percent = atr_value / last * 100 if last else 0
    adx_value = adx(candles)
    width = bollinger_width(closes)
    structure = market_structure(candles)
    average_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
    relative_volume = volumes[-1] / average_volume if average_volume else 0
    momentum = (closes[-1] - closes[-5]) / closes[-5] * 100

    reasons: list[str] = []
    long_score = 0
    short_score = 0

    if last > ema20_value > ema50_value > ema200_value:
        long_score += 35
        reasons.append(f"{timeframe}: EMA выстроены вверх")
    elif last < ema20_value < ema50_value < ema200_value:
        short_score += 35
        reasons.append(f"{timeframe}: EMA выстроены вниз")
    else:
        if last > ema200_value:
            long_score += 12
        elif last < ema200_value:
            short_score += 12

    if structure == "BULLISH":
        long_score += 20
        reasons.append(f"{timeframe}: повышающиеся экстремумы")
    elif structure == "BEARISH":
        short_score += 20
        reasons.append(f"{timeframe}: понижающиеся экстремумы")

    if 42 <= rsi_value <= 68:
        long_score += 12
    if 32 <= rsi_value <= 58:
        short_score += 12

    if momentum > 0:
        long_score += 13
    elif momentum < 0:
        short_score += 13

    if adx_value >= 18:
        if long_score > short_score:
            long_score += 10
        elif short_score > long_score:
            short_score += 10

    if relative_volume >= min_relative_volume:
        if long_score > short_score:
            long_score += 10
        elif short_score > long_score:
            short_score += 10
        reasons.append(f"{timeframe}: объём {relative_volume:.2f}x среднего")
    elif require_volume_confirmation:
        return None

    side = "LONG" if long_score > short_score else "SHORT"
    score = max(long_score, short_score)

    if adx_value >= 22 and structure in {"BULLISH", "BEARISH"}:
        regime = "TREND"
    elif width <= 2.0:
        regime = "COMPRESSION"
    elif structure == "RANGE":
        regime = "RANGE"
    elif atr_percent >= 3:
        regime = "HIGH_VOLATILITY"
    else:
        regime = "MIXED"

    return TimeframeAnalysis(
        timeframe=timeframe,
        side=side,
        score=min(score, 100),
        regime=regime,
        structure=structure,
        ema20=ema20_value,
        ema50=ema50_value,
        ema200=ema200_value,
        rsi=rsi_value,
        atr_value=atr_value,
        atr_percent=atr_percent,
        adx=adx_value,
        relative_volume=relative_volume,
        momentum_percent=momentum,
        bollinger_width_percent=width,
        latest_close=last,
        reasons=reasons,
    )


def combine_timeframes(
    symbol: str,
    analyses: dict[str, TimeframeAnalysis],
    btc_context: str,
) -> Signal | None:
    if not analyses:
        return None

    weights = {
        "Min5": 0.15,
        "Min15": 0.35,
        "Min60": 0.30,
        "Hour4": 0.20,
    }
    long_total = 0.0
    short_total = 0.0
    timeframe_scores: dict[str, int] = {}
    reasons: list[str] = []

    for timeframe, result in analyses.items():
        weight = weights.get(timeframe, 0.25)
        timeframe_scores[timeframe] = result.score
        if result.side == "LONG":
            long_total += result.score * weight
        else:
            short_total += result.score * weight
        reasons.extend(result.reasons[:2])

    side = "LONG" if long_total > short_total else "SHORT"
    score = int(round(max(long_total, short_total)))

    agreement = sum(
        1 for result in analyses.values() if result.side == side
    )
    if agreement >= 3:
        score += 10
        reasons.append(f"{agreement} таймфрейма согласованы")
    elif agreement <= 1:
        return None

    if btc_context == "BULLISH":
        score += 5 if side == "LONG" else -10
    elif btc_context == "BEARISH":
        score += 5 if side == "SHORT" else -10
    elif btc_context == "UNSTABLE":
        score -= 15

    primary = analyses.get("Min15") or next(iter(analyses.values()))
    if primary.atr_value <= 0:
        return None

    entry = primary.latest_close
    risk_distance = max(primary.atr_value * 1.5, entry * 0.004)

    if side == "LONG":
        stop = entry - risk_distance
        tp1 = entry + risk_distance
        tp2 = entry + risk_distance * 2
    else:
        stop = entry + risk_distance
        tp1 = entry - risk_distance
        tp2 = entry - risk_distance * 2

    regimes = [result.regime for result in analyses.values()]
    market_regime = max(set(regimes), key=regimes.count)
    strategy = (
        "Confirmed Breakout"
        if market_regime == "COMPRESSION"
        else "Trend Pullback / Momentum"
    )

    diagnostics = {
        "long_total": round(long_total, 2),
        "short_total": round(short_total, 2),
        "agreement": agreement,
        "primary_rsi": round(primary.rsi, 2),
        "primary_adx": round(primary.adx, 2),
        "primary_atr_percent": round(primary.atr_percent, 3),
        "primary_relative_volume": round(primary.relative_volume, 2),
    }

    return Signal(
        symbol=symbol,
        side=side,
        score=max(0, min(score, 100)),
        entry=entry,
        stop_loss=stop,
        tp1=tp1,
        tp2=tp2,
        atr=primary.atr_value,
        reasons=list(dict.fromkeys(reasons))[:7],
        strategy=strategy,
        market_regime=market_regime,
        btc_context=btc_context,
        timeframe_scores=timeframe_scores,
        diagnostics=diagnostics,
    )


def analyze(symbol: str, candles: list[dict]) -> Signal | None:
    result = analyze_timeframe(
        "Min15",
        candles,
        min_relative_volume=0.8,
        require_volume_confirmation=False,
    )
    if result is None:
        return None
    return combine_timeframes(symbol, {"Min15": result}, "NEUTRAL")
