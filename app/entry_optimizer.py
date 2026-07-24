from dataclasses import dataclass

from app.models import Signal


@dataclass(slots=True)
class EntryOptimization:
    score: int
    action: str
    recommended_entry: float
    zone_low: float
    zone_high: float
    wait_distance_atr: float
    wait_distance_percent: float
    ttl_candles: int
    allowed_now: bool
    reasons: list[str]


class EntryOptimizer:
    """Converts entry diagnostics into an actionable timing recommendation.

    Entry Intelligence rates the current price. Entry Optimizer goes one step
    further: it chooses whether to enter now, wait for a pullback/retest, or
    skip an overextended move, and publishes a concrete entry zone.
    """

    def __init__(self, settings) -> None:
        self.settings = settings

    @staticmethod
    def _number(diagnostics: dict, key: str, default: float = 0.0) -> float:
        try:
            return float(diagnostics.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp(value: float) -> int:
        return max(0, min(round(value), 100))

    def evaluate(self, signal: Signal) -> EntryOptimization:
        diagnostics = signal.diagnostics or {}
        entry = float(signal.entry)
        atr = max(float(signal.atr), 1e-12)
        ema20 = self._number(diagnostics, "primary_ema20", entry)
        breakout = self._number(diagnostics, "primary_breakout_level", ema20)
        vwap_distance = self._number(diagnostics, "primary_vwap_distance_percent")
        momentum = abs(self._number(diagnostics, "primary_momentum_percent"))
        impulse_candles = int(self._number(diagnostics, "primary_impulse_candles"))
        relative_volume = self._number(diagnostics, "primary_relative_volume")

        anchor = breakout if breakout > 0 else ema20
        pullback_atr = max(0.0, float(getattr(self.settings, "entry_optimizer_pullback_atr", 0.25)))
        zone_half_atr = max(0.05, float(getattr(self.settings, "entry_optimizer_zone_half_atr", 0.12)))

        if signal.side == "LONG":
            recommended = min(entry, anchor + atr * pullback_atr)
        else:
            recommended = max(entry, anchor - atr * pullback_atr)

        zone_low = recommended - atr * zone_half_atr
        zone_high = recommended + atr * zone_half_atr
        wait_distance = abs(entry - recommended)
        wait_distance_atr = wait_distance / atr
        wait_distance_percent = wait_distance / entry * 100 if entry else 0.0

        quality = signal.entry_quality_score if signal.entry_quality_score is not None else signal.score
        prediction = signal.prediction_score if signal.prediction_score is not None else signal.score
        trigger = signal.trigger_score if signal.trigger_score is not None else signal.score
        false_breakout = signal.false_breakout_risk if signal.false_breakout_risk is not None else 50

        score = (
            quality * 0.35
            + prediction * 0.20
            + trigger * 0.25
            + max(0, 100 - false_breakout) * 0.20
        )
        reasons: list[str] = []

        if zone_low <= entry <= zone_high:
            score += 8
            reasons.append("Текущая цена находится внутри оптимальной зоны")
        elif wait_distance_atr > 0.45:
            score -= 12
            reasons.append(f"До оптимальной зоны {wait_distance_atr:.2f} ATR")

        if signal.trigger_confirmed:
            score += 8
            reasons.append("Trigger Engine подтвердил активацию")
        elif signal.trigger_state in {"ARMED", "WATCH"}:
            score -= 4
            reasons.append("Триггер ещё не подтверждён")

        if signal.prediction_state == "READY":
            score += 5
        elif signal.prediction_state == "INVALIDATED":
            score -= 30
            reasons.append("Prediction Engine инвалидировал сетап")

        if impulse_candles >= int(getattr(self.settings, "entry_optimizer_max_impulse_candles", 4)):
            score -= 12
            reasons.append(f"Импульс продолжается {impulse_candles} свечей")
        if momentum >= float(getattr(self.settings, "entry_optimizer_chase_momentum_percent", 1.8)):
            score -= 10
            reasons.append("Импульс слишком растянут для входа по рынку")
        if abs(vwap_distance) > float(getattr(self.settings, "entry_optimizer_max_vwap_distance_percent", 1.2)):
            score -= 8
            reasons.append("Цена далеко отклонилась от VWAP")
        if relative_volume >= 1.15 and wait_distance_atr <= 0.25:
            score += 4
            reasons.append("Объём поддерживает вход рядом с зоной")

        score = self._clamp(score)
        skip_chase = (
            signal.entry_timing == "CHASE"
            or signal.entry_allowed is False
            or wait_distance_atr >= float(getattr(self.settings, "entry_optimizer_skip_distance_atr", 0.90))
        )

        if signal.prediction_state == "INVALIDATED" or false_breakout >= int(getattr(self.settings, "entry_optimizer_invalidation_risk", 70)):
            action = "INVALID"
        elif skip_chase:
            action = "SKIP_CHASE"
        elif zone_low <= entry <= zone_high and signal.trigger_confirmed:
            action = "ENTER_NOW"
        elif signal.trigger_state in {"TRIGGERED", "ARMED"} or signal.prediction_state == "READY":
            action = "WAIT_RETEST"
        else:
            action = "WAIT_PULLBACK"

        allowed_now = action == "ENTER_NOW"
        if action == "WAIT_RETEST":
            reasons.append("Дождаться подтверждённого ретеста рабочей зоны")
        elif action == "WAIT_PULLBACK":
            reasons.append("Дождаться отката к рассчитанной зоне")
        elif action == "SKIP_CHASE":
            reasons.append("Не догонять уже ушедшее движение")
        elif action == "INVALID":
            reasons.append("Сетап больше не подходит для нового входа")

        ttl = int(getattr(self.settings, "entry_optimizer_ttl_candles", 3))
        if action in {"SKIP_CHASE", "INVALID"}:
            ttl = 0

        return EntryOptimization(
            score=score,
            action=action,
            recommended_entry=round(recommended, 8),
            zone_low=round(zone_low, 8),
            zone_high=round(zone_high, 8),
            wait_distance_atr=round(wait_distance_atr, 3),
            wait_distance_percent=round(wait_distance_percent, 3),
            ttl_candles=max(0, ttl),
            allowed_now=allowed_now,
            reasons=list(dict.fromkeys(reasons))[:6],
        )

    def attach(self, signal: Signal) -> Signal:
        result = self.evaluate(signal)
        signal.entry_optimizer_score = result.score
        signal.entry_optimizer_action = result.action
        signal.entry_optimizer_recommended_price = result.recommended_entry
        signal.entry_optimizer_zone_low = result.zone_low
        signal.entry_optimizer_zone_high = result.zone_high
        signal.entry_optimizer_wait_atr = result.wait_distance_atr
        signal.entry_optimizer_wait_percent = result.wait_distance_percent
        signal.entry_optimizer_ttl_candles = result.ttl_candles
        signal.entry_optimizer_allowed_now = result.allowed_now
        signal.entry_optimizer_reasons = result.reasons
        return signal
