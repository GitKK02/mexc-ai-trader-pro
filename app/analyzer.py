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
    atr_compression_ratio: float
    ema_compression_percent: float
    range_compression_ratio: float
    volume_building_ratio: float
    vwap_distance_percent: float
    latest_close: float
    breakout_level: float
    impulse_candles: int
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
    previous_atr = atr(candles[:-5]) if len(candles) > 215 else atr_value
    atr_compression_ratio = atr_value / previous_atr if previous_atr else 1.0
    ema_compression_percent = (
        abs(ema20_value - ema50_value) / last * 100 if last else 0.0
    )
    recent_high = max(float(item["high"]) for item in candles[-8:])
    recent_low = min(float(item["low"]) for item in candles[-8:])
    baseline_high = max(float(item["high"]) for item in candles[-28:-8])
    baseline_low = min(float(item["low"]) for item in candles[-28:-8])
    recent_range = recent_high - recent_low
    baseline_range = baseline_high - baseline_low
    range_compression_ratio = recent_range / baseline_range if baseline_range else 1.0
    recent_volume = sum(volumes[-5:]) / 5
    baseline_volume = sum(volumes[-25:-5]) / 20
    volume_building_ratio = recent_volume / baseline_volume if baseline_volume else 1.0
    typical_prices = [
        (float(item["high"]) + float(item["low"]) + float(item["close"])) / 3
        for item in candles[-20:]
    ]
    vwap_volume = sum(volumes[-20:])
    vwap_value = (
        sum(price * volume for price, volume in zip(typical_prices, volumes[-20:]))
        / vwap_volume
        if vwap_volume
        else last
    )
    vwap_distance_percent = (last - vwap_value) / vwap_value * 100 if vwap_value else 0.0
    prior_high = max(float(item["high"]) for item in candles[-21:-1])
    prior_low = min(float(item["low"]) for item in candles[-21:-1])
    impulse_candles = 0
    for index in range(len(candles) - 1, max(len(candles) - 7, 0), -1):
        candle = candles[index]
        bullish = float(candle["close"]) > float(candle["open"])
        bearish = float(candle["close"]) < float(candle["open"])
        if bullish:
            impulse_candles += 1
        else:
            break
    bearish_impulse_candles = 0
    for index in range(len(candles) - 1, max(len(candles) - 7, 0), -1):
        candle = candles[index]
        bearish = float(candle["close"]) < float(candle["open"])
        if bearish:
            bearish_impulse_candles += 1
        else:
            break

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
        atr_compression_ratio=atr_compression_ratio,
        ema_compression_percent=ema_compression_percent,
        range_compression_ratio=range_compression_ratio,
        volume_building_ratio=volume_building_ratio,
        vwap_distance_percent=vwap_distance_percent,
        latest_close=last,
        breakout_level=prior_high if side == "LONG" else prior_low,
        impulse_candles=(
            impulse_candles if side == "LONG" else bearish_impulse_candles
        ),
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
        "primary_momentum_percent": round(primary.momentum_percent, 3),
        "primary_ema20": round(primary.ema20, 8),
        "primary_ema50": round(primary.ema50, 8),
        "primary_breakout_level": round(primary.breakout_level, 8),
        "primary_impulse_candles": primary.impulse_candles,
        "primary_bollinger_width_percent": round(
            primary.bollinger_width_percent, 3
        ),
        "primary_atr_compression_ratio": round(primary.atr_compression_ratio, 3),
        "primary_ema_compression_percent": round(primary.ema_compression_percent, 3),
        "primary_range_compression_ratio": round(primary.range_compression_ratio, 3),
        "primary_volume_building_ratio": round(primary.volume_building_ratio, 3),
        "primary_vwap_distance_percent": round(primary.vwap_distance_percent, 3),
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
