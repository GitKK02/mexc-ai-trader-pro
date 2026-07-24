from dataclasses import dataclass


@dataclass(slots=True)
class StopRecommendation:
    price: float
    strategy: str
    score: int
    distance_atr: float
    distance_percent: float
    risk_reward_tp1: float
    allowed: bool
    reasons: list[str]
    candidates: dict[str, float]


class DynamicStopEngine:
    """Builds an explainable invalidation stop from structure and volatility.

    The engine only moves the initial stop to a bounded, directionally valid
    level. Position sizing remains controlled by SmartRiskEngine.
    """

    def __init__(self, settings) -> None:
        self.settings = settings

    @staticmethod
    def _positive(value, fallback: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return fallback
        return parsed if parsed > 0 else fallback

    def assess(self, signal) -> StopRecommendation:
        entry = float(signal.entry)
        atr = self._positive(signal.atr, entry * 0.004)
        diagnostics = signal.diagnostics or {}
        side = signal.side
        direction = -1.0 if side == "LONG" else 1.0
        buffer_atr = float(self.settings.dynamic_stop_structure_buffer_atr)

        breakout = self._positive(
            diagnostics.get("primary_breakout_level"), entry
        )
        ema20 = self._positive(diagnostics.get("primary_ema20"), entry)
        ema50 = self._positive(diagnostics.get("primary_ema50"), entry)
        vwap_distance = float(diagnostics.get("primary_vwap_distance_percent", 0) or 0)
        vwap = entry / (1 + vwap_distance / 100) if 1 + vwap_distance / 100 > 0 else entry

        if side == "LONG":
            structure_anchor = min(entry, breakout)
            ema_anchor = min(ema20, ema50)
            candidates = {
                "STRUCTURE": structure_anchor - atr * buffer_atr,
                "ATR": entry - atr * float(self.settings.dynamic_stop_atr_multiplier),
                "EMA": ema_anchor - atr * float(self.settings.dynamic_stop_ema_buffer_atr),
                "VWAP": vwap - atr * float(self.settings.dynamic_stop_vwap_buffer_atr),
            }
        else:
            structure_anchor = max(entry, breakout)
            ema_anchor = max(ema20, ema50)
            candidates = {
                "STRUCTURE": structure_anchor + atr * buffer_atr,
                "ATR": entry + atr * float(self.settings.dynamic_stop_atr_multiplier),
                "EMA": ema_anchor + atr * float(self.settings.dynamic_stop_ema_buffer_atr),
                "VWAP": vwap + atr * float(self.settings.dynamic_stop_vwap_buffer_atr),
            }

        min_atr = float(self.settings.dynamic_stop_min_distance_atr)
        max_atr = float(self.settings.dynamic_stop_max_distance_atr)
        valid: dict[str, tuple[float, float]] = {}
        for name, price in candidates.items():
            directional = price < entry if side == "LONG" else price > entry
            distance_atr = abs(entry - price) / atr
            if directional and min_atr <= distance_atr <= max_atr:
                valid[name] = (price, distance_atr)

        reasons: list[str] = []
        preferred = "STRUCTURE" if "STRUCTURE" in valid else "ATR"
        if preferred not in valid and valid:
            preferred = min(valid, key=lambda name: abs(valid[name][1] - 1.0))

        allowed = bool(valid)
        if not valid:
            fallback_distance = min(max(1.0, min_atr), max_atr)
            price = entry + direction * atr * fallback_distance
            strategy = "FALLBACK_ATR"
            distance_atr = fallback_distance
            score = 35
            reasons.append("Структурные кандидаты вне безопасного диапазона; применён ATR fallback")
        else:
            price, distance_atr = valid[preferred]
            strategy = preferred
            score = 78
            if strategy == "STRUCTURE":
                score += 10
                reasons.append("Стоп расположен за уровнем пробоя/структурной инвалидации")
            elif strategy == "EMA":
                reasons.append("Стоп расположен за трендовой EMA-структурой")
            elif strategy == "VWAP":
                reasons.append("Стоп расположен за VWAP с защитным буфером")
            else:
                reasons.append("Стоп нормализован по текущему ATR")

        tp1_distance = abs(float(signal.tp1) - entry)
        stop_distance = abs(entry - price)
        rr = tp1_distance / stop_distance if stop_distance else 0.0
        min_rr = float(self.settings.dynamic_stop_min_rr_tp1)
        if rr < min_rr:
            allowed = False
            score -= 25
            reasons.append(f"RR до TP1 слишком низкий: {rr:.2f} < {min_rr:.2f}")
        if distance_atr <= min_atr + 0.05:
            reasons.append("Стоп близок к рыночному шуму")
            score -= 8
        if distance_atr >= max_atr - 0.10:
            reasons.append("Стоп близок к максимальной разрешённой дистанции")
            score -= 8

        distance_percent = abs(entry - price) / entry * 100 if entry else 0.0
        return StopRecommendation(
            price=price,
            strategy=strategy,
            score=max(0, min(100, round(score))),
            distance_atr=round(distance_atr, 3),
            distance_percent=round(distance_percent, 3),
            risk_reward_tp1=round(rr, 3),
            allowed=allowed,
            reasons=list(dict.fromkeys(reasons)),
            candidates={name: round(value, 10) for name, value in candidates.items()},
        )

    def attach(self, signal):
        recommendation = self.assess(signal)
        signal.dynamic_stop_price = recommendation.price
        signal.dynamic_stop_strategy = recommendation.strategy
        signal.dynamic_stop_score = recommendation.score
        signal.dynamic_stop_distance_atr = recommendation.distance_atr
        signal.dynamic_stop_distance_percent = recommendation.distance_percent
        signal.dynamic_stop_rr_tp1 = recommendation.risk_reward_tp1
        signal.dynamic_stop_allowed = recommendation.allowed
        signal.dynamic_stop_reasons = recommendation.reasons
        signal.dynamic_stop_candidates = recommendation.candidates
        if recommendation.allowed or not self.settings.dynamic_stop_enforced:
            signal.stop_loss = recommendation.price
        return signal
