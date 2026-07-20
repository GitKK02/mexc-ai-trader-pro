from dataclasses import dataclass

from app.models import Signal


@dataclass(slots=True)
class EntryAssessment:
    score: int
    timing: str
    phase: str
    allowed: bool
    distance_atr: float
    distance_percent: float
    remaining_to_tp1_r: float
    reasons: list[str]


class EntryIntelligence:
    """Rates whether the current price is still a sensible entry.

    This layer deliberately separates a strong market idea from a good entry
    point. A signal may remain technically strong while the current price is
    already extended and should be watched for a pullback instead of chased.
    """

    def __init__(self, settings) -> None:
        self.settings = settings

    @staticmethod
    def _number(diagnostics: dict, key: str, default: float = 0.0) -> float:
        try:
            return float(diagnostics.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    def evaluate(self, signal: Signal) -> EntryAssessment:
        diagnostics = signal.diagnostics or {}
        entry = float(signal.entry)
        atr = max(float(signal.atr), 1e-12)
        ema20 = self._number(diagnostics, "primary_ema20", entry)
        breakout = self._number(diagnostics, "primary_breakout_level", ema20)
        momentum = abs(self._number(diagnostics, "primary_momentum_percent"))
        impulse_candles = int(self._number(diagnostics, "primary_impulse_candles"))
        relative_volume = self._number(diagnostics, "primary_relative_volume")

        anchor = breakout if breakout > 0 else ema20
        raw_distance = entry - anchor if signal.side == "LONG" else anchor - entry
        distance_atr = raw_distance / atr
        distance_percent = abs(raw_distance) / entry * 100 if entry else 0.0

        risk_distance = abs(entry - float(signal.stop_loss))
        reward_left = (
            float(signal.tp1) - entry
            if signal.side == "LONG"
            else entry - float(signal.tp1)
        )
        remaining_to_tp1_r = reward_left / risk_distance if risk_distance > 0 else 0.0

        score = 100
        reasons: list[str] = []

        if distance_atr > 0:
            score -= round(min(distance_atr, 2.0) * 28)
        else:
            score -= round(min(abs(distance_atr), 1.0) * 8)
            reasons.append("Цена находится в зоне отката")

        if impulse_candles >= self.settings.entry_max_impulse_candles:
            score -= 18
            reasons.append(f"Импульс длится уже {impulse_candles} свечей")
        elif impulse_candles >= 2:
            score -= 8

        if momentum >= self.settings.entry_high_momentum_percent:
            score -= 12
            reasons.append("Краткосрочный импульс уже растянут")

        if relative_volume >= 1.2 and distance_atr <= 0.6:
            score += 6
            reasons.append("Объём подтверждает вход без сильного растяжения")

        if remaining_to_tp1_r < self.settings.entry_min_remaining_tp1_r:
            score -= 25
            reasons.append(
                f"До TP1 осталось только {remaining_to_tp1_r:.2f}R"
            )

        score = max(0, min(round(score), 100))
        chase = (
            distance_atr > self.settings.entry_max_distance_atr
            or distance_percent > self.settings.entry_max_distance_percent
            or remaining_to_tp1_r < self.settings.entry_min_remaining_tp1_r
        )

        if chase:
            timing = "CHASE"
            phase = "EXTENDED"
        elif distance_atr > self.settings.entry_late_distance_atr:
            timing = "LATE"
            phase = "EXTENDED"
        elif distance_atr >= -0.15:
            timing = "GOOD"
            phase = "TRIGGERED"
        else:
            timing = "EARLY"
            phase = "ARMED"

        allowed = not chase if self.settings.entry_chase_guard_enabled else True
        if timing == "GOOD":
            reasons.append("Цена находится рядом с рабочей зоной входа")
        elif timing == "LATE":
            reasons.append("Вход запоздал: предпочтителен откат или ретест")
        elif timing == "CHASE":
            reasons.append("Вход вслед за движением заблокирован")
        elif timing == "EARLY":
            reasons.append("Сетап формируется, триггер ещё ранний")

        return EntryAssessment(
            score=score,
            timing=timing,
            phase=phase,
            allowed=allowed,
            distance_atr=round(distance_atr, 3),
            distance_percent=round(distance_percent, 3),
            remaining_to_tp1_r=round(remaining_to_tp1_r, 3),
            reasons=list(dict.fromkeys(reasons))[:6],
        )

    def attach(self, signal: Signal) -> Signal:
        result = self.evaluate(signal)
        signal.entry_quality_score = result.score
        signal.entry_timing = result.timing
        signal.entry_phase = result.phase
        signal.entry_allowed = result.allowed
        signal.entry_distance_atr = result.distance_atr
        signal.entry_distance_percent = result.distance_percent
        signal.entry_remaining_tp1_r = result.remaining_to_tp1_r
        signal.entry_reasons = result.reasons
        return signal
