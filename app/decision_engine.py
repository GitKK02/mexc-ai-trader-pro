from dataclasses import dataclass
from datetime import datetime, timezone

from app.models import Signal


@dataclass(slots=True)
class DecisionResult:
    score: int
    action: str
    confidence: str
    reasons: list[str]
    components: dict[str, int]


class AIDecisionEngine:
    """
    Deterministic decision layer.

    OpenAI is treated as one input, not as the sole trading authority.
    The final decision remains bounded by technical and portfolio scores.
    """

    def __init__(self, settings) -> None:
        self.settings = settings

    @staticmethod
    def _clamp(value: int) -> int:
        return max(0, min(value, 100))

    @staticmethod
    def _timeframe_component(signal: Signal) -> int:
        scores = signal.timeframe_scores or {}
        if not scores:
            return signal.score
        return round(sum(scores.values()) / len(scores))

    @staticmethod
    def _agreement(signal: Signal) -> int:
        diagnostics = signal.diagnostics or {}
        try:
            return int(diagnostics.get("agreement", 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _momentum_component(signal: Signal) -> int:
        diagnostics = signal.diagnostics or {}
        scanner_score = int(signal.score)
        adx = float(diagnostics.get("primary_adx", 0) or 0)
        volume = float(
            diagnostics.get("primary_relative_volume", 0) or 0
        )
        score = scanner_score
        if adx >= 25:
            score += 5
        elif adx < 15:
            score -= 8
        if volume >= 1.2:
            score += 5
        elif volume < 0.7:
            score -= 7
        return max(0, min(score, 100))

    def evaluate(self, signal: Signal) -> DecisionResult:
        reasons: list[str] = []

        scanner = int(signal.score)
        timeframe = self._timeframe_component(signal)
        portfolio = (
            int(signal.portfolio_score)
            if signal.portfolio_score is not None
            else scanner
        )
        momentum = self._momentum_component(signal)

        entry_quality = (
            int(signal.entry_quality_score)
            if signal.entry_quality_score is not None
            else scanner
        )
        components = {
            "scanner": scanner,
            "timeframes": timeframe,
            "momentum": momentum,
            "portfolio": portfolio,
            "entry": entry_quality,
        }

        entry_weight = max(0.0, min(float(getattr(self.settings, "entry_quality_weight", 0.20)), 0.40))
        base_weight = 1.0 - entry_weight
        weighted = round(
            (
                scanner * 0.30
                + timeframe * 0.25
                + momentum * 0.20
                + portfolio * 0.25
            ) * base_weight
            + entry_quality * entry_weight
        )

        agreement = self._agreement(signal)
        if agreement >= self.settings.decision_min_timeframe_agreement:
            weighted += 4
            reasons.append(
                f"Подтверждение на {agreement} таймфреймах"
            )
        else:
            weighted -= 10
            reasons.append("Недостаточное согласование таймфреймов")

        regime = (signal.market_regime or "UNKNOWN").upper()
        if regime == "TREND":
            weighted += self.settings.decision_trend_regime_bonus
            reasons.append("Трендовый режим рынка")
        elif regime == "RANGE":
            weighted -= self.settings.decision_range_regime_penalty
            reasons.append("Рынок находится в диапазоне")
        elif regime == "HIGH_VOLATILITY":
            weighted -= 5
            reasons.append("Повышенная волатильность")
        elif regime == "COMPRESSION":
            reasons.append("Сжатие волатильности: нужен подтверждённый выход")

        btc_context = (signal.btc_context or "NEUTRAL").upper()
        if btc_context == "UNSTABLE":
            weighted -= self.settings.decision_unstable_btc_penalty
            reasons.append("BTC-контекст нестабилен")
        elif (
            btc_context == "BULLISH"
            and signal.side == "LONG"
        ) or (
            btc_context == "BEARISH"
            and signal.side == "SHORT"
        ):
            weighted += 3
            reasons.append("Направление совпадает с BTC-контекстом")
        elif btc_context in {"BULLISH", "BEARISH"}:
            weighted -= 6
            reasons.append("Сделка направлена против BTC-контекста")

        ai_decision = (signal.ai_decision or "SKIPPED").upper()
        if ai_decision == "APPROVE":
            weighted += self.settings.decision_ai_approve_bonus
            reasons.append("OpenAI подтвердил структуру сигнала")
        elif ai_decision == "WAIT":
            weighted -= self.settings.decision_ai_wait_penalty
            reasons.append("OpenAI рекомендует ожидание")
        elif ai_decision == "REJECT":
            weighted -= self.settings.decision_ai_reject_penalty
            reasons.append("OpenAI отклонил сигнал")
        elif ai_decision == "ERROR":
            reasons.append("OpenAI недоступен")
            if self.settings.decision_block_on_ai_error:
                weighted = min(
                    weighted,
                    self.settings.decision_wait_score - 1,
                )
        else:
            reasons.append("OpenAI-проверка не выполнена")

        if signal.entry_allowed is False:
            weighted = min(weighted, self.settings.decision_wait_score - 1)
            reasons.extend(signal.entry_reasons or [])
            reasons.append("Entry Intelligence запретил поздний вход")
        elif entry_quality < getattr(self.settings, "entry_min_quality_confirm", 60):
            weighted = min(weighted, self.settings.decision_confirm_score - 1)
            reasons.extend(signal.entry_reasons or [])
            reasons.append("Качество текущей точки входа ниже CONFIRM-порога")
        elif signal.entry_timing == "LATE":
            weighted -= 8
            reasons.extend(signal.entry_reasons or [])
        elif signal.entry_timing == "GOOD":
            weighted += 4
            reasons.append("Точка входа находится в рабочей зоне")

        if signal.portfolio_allowed is False:
            weighted = min(
                weighted,
                self.settings.decision_wait_score - 1,
            )
            reasons.extend(signal.portfolio_reasons or [])
            reasons.append("Portfolio Manager запретил вход")

        if signal.volatility_guard_allowed is False:
            weighted = min(
                weighted,
                self.settings.decision_wait_score - 1,
            )
            reasons.extend(signal.volatility_guard_reasons or [])
            reasons.append("Volatility Guard запретил вход")
        elif signal.volatility_guard_multiplier < 1:
            penalty = round(
                (1 - signal.volatility_guard_multiplier) * 10
            )
            weighted -= penalty
            reasons.extend(signal.volatility_guard_reasons or [])
        if signal.regime_allowed is False:
            weighted = min(weighted, self.settings.decision_wait_score - 1)
            reasons.extend(signal.regime_reasons or [])
            reasons.append("Market Regime Engine запретил вход")
        else:
            weighted += int(signal.regime_score_adjustment or 0)
            reasons.extend(signal.regime_reasons or [])

        if signal.macro_guard_allowed is False:
            weighted = min(
                weighted,
                self.settings.decision_wait_score - 1,
            )
            reasons.extend(signal.macro_guard_reasons or [])
            reasons.append("News & Macro Guard запретил вход")
        elif signal.macro_guard_risk_multiplier < 1:
            weighted -= 8
            reasons.extend(signal.macro_guard_reasons or [])
            reasons.append("Macro Guard уменьшил риск")

        score = self._clamp(weighted)

        if (
            score >= self.settings.decision_enter_score
            and signal.portfolio_allowed is not False
            and (
                not self.settings.decision_require_ai_for_enter
                or ai_decision == "APPROVE"
            )
        ):
            action = "ENTER"
        elif (
            score >= self.settings.decision_confirm_score
            and signal.portfolio_allowed is not False
        ):
            action = "CONFIRM"
        elif score >= self.settings.decision_wait_score:
            action = "WAIT"
        else:
            action = "REJECT"

        if score >= 90:
            confidence = "HIGH"
        elif score >= 80:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        return DecisionResult(
            score=score,
            action=action,
            confidence=confidence,
            reasons=list(dict.fromkeys(reasons))[:8],
            components=components,
        )

    def attach(self, signal: Signal) -> Signal:
        result = self.evaluate(signal)
        signal.decision_score = result.score
        signal.decision_action = result.action
        signal.decision_confidence = result.confidence
        signal.decision_reasons = result.reasons
        signal.component_scores = result.components
        signal.decision_created_at = datetime.now(timezone.utc).isoformat()
        return signal

    def rank(self, signals: list[Signal]) -> list[Signal]:
        evaluated = [self.attach(signal) for signal in signals]
        order = {
            "ENTER": 4,
            "CONFIRM": 3,
            "WAIT": 2,
            "REJECT": 1,
        }
        evaluated.sort(
            key=lambda signal: (
                order.get(signal.decision_action, 0),
                signal.decision_score or 0,
            ),
            reverse=True,
        )
        return evaluated
