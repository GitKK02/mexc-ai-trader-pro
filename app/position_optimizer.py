from dataclasses import dataclass


@dataclass(slots=True)
class PositionOptimization:
    score: int
    multiplier: float
    tier: str
    allowed_to_scale_up: bool
    reasons: list[str]
    components: dict[str, int]


class PositionOptimizer:
    """Converts setup quality into a bounded risk-size multiplier.

    The optimizer never bypasses Smart Risk, portfolio, volatility or macro caps.
    It only recommends a multiplier that SmartRiskEngine applies before its hard
    min/max risk limits.
    """

    def __init__(self, settings) -> None:
        self.settings = settings

    @staticmethod
    def _score(value, fallback: int = 50) -> int:
        if value is None:
            return fallback
        return max(0, min(100, int(value)))

    def assess(self, signal) -> PositionOptimization:
        components = {
            "decision": self._score(signal.decision_score, signal.score),
            "confluence": self._score(signal.confluence_score),
            "prediction": self._score(signal.prediction_score),
            "trigger": self._score(signal.trigger_score),
            "entry": self._score(signal.entry_optimizer_score, signal.entry_quality_score or 50),
            "market": self._score(signal.market_opportunity_score, signal.market_intelligence_score or 50),
        }
        weights = {
            "decision": 0.24,
            "confluence": 0.18,
            "prediction": 0.16,
            "trigger": 0.16,
            "entry": 0.16,
            "market": 0.10,
        }
        score = round(sum(components[name] * weights[name] for name in components))
        reasons: list[str] = []

        hard_reduce = False
        if signal.entry_optimizer_action in {"SKIP_CHASE", "INVALID"}:
            hard_reduce = True
            reasons.append(f"Entry Optimizer: {signal.entry_optimizer_action}")
        if signal.volatility_state in {"PANIC", "EXTREME"}:
            hard_reduce = True
            reasons.append(f"Волатильность: {signal.volatility_state}")
        if signal.macro_guard_state in {"BLOCK", "BLACKOUT"}:
            hard_reduce = True
            reasons.append(f"Macro Guard: {signal.macro_guard_state}")
        if signal.false_breakout_risk is not None and signal.false_breakout_risk >= 70:
            reasons.append(f"Высокий false-breakout risk: {signal.false_breakout_risk}/100")
            score -= 10

        score = max(0, min(100, score))
        min_mult = float(self.settings.position_optimizer_min_multiplier)
        max_mult = float(self.settings.position_optimizer_max_multiplier)
        neutral = float(self.settings.position_optimizer_neutral_multiplier)

        if hard_reduce:
            multiplier = min_mult
            tier = "DEFENSIVE"
        elif score >= self.settings.position_optimizer_strong_score:
            multiplier = max_mult
            tier = "STRONG"
            reasons.append("Сильное согласование независимых модулей")
        elif score >= self.settings.position_optimizer_normal_score:
            multiplier = neutral
            tier = "NORMAL"
            reasons.append("Качество сделки соответствует базовому риску")
        else:
            span = max(1, self.settings.position_optimizer_normal_score)
            ratio = max(0.0, min(1.0, score / span))
            multiplier = min_mult + (neutral - min_mult) * ratio
            tier = "REDUCED"
            reasons.append("Размер снижен из-за недостаточной уверенности")

        allowed_to_scale_up = True
        if signal.volatility_guard_multiplier < 1 or signal.macro_guard_risk_multiplier < 1:
            allowed_to_scale_up = False
            multiplier = min(multiplier, neutral)
            reasons.append("Защитный guard запрещает увеличение базового риска")
        if signal.entry_optimizer_action not in {"ENTER_NOW", "NOT_EVALUATED"}:
            allowed_to_scale_up = False
            multiplier = min(multiplier, neutral)
            reasons.append("Увеличение отключено до оптимальной точки входа")
        if signal.trigger_confirmed is False:
            allowed_to_scale_up = False
            multiplier = min(multiplier, neutral)
            reasons.append("Trigger ещё не подтверждён")

        multiplier = max(min_mult, min(multiplier, max_mult))
        return PositionOptimization(
            score=score,
            multiplier=round(multiplier, 3),
            tier=tier,
            allowed_to_scale_up=allowed_to_scale_up,
            reasons=list(dict.fromkeys(reasons)),
            components=components,
        )
