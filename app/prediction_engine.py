from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.models import Signal


@dataclass(slots=True)
class PredictionAssessment:
    prediction_score: int
    breakout_readiness: int
    false_breakout_risk: int
    direction: str
    state: str
    horizon: str
    components: dict[str, int]
    reasons: list[str]


class PredictionEngine:
    """Estimates whether a WATCH setup is maturing before the impulse.

    Scores are calibrated indicators, not guaranteed real-world probabilities.
    This release is execution-neutral: READY never opens a position by itself.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _clamp(value: float) -> int:
        return max(0, min(100, int(round(value))))

    @staticmethod
    def _value(signal: Signal, name: str, default: float = 0.0) -> float:
        try:
            return float((signal.diagnostics or {}).get(name, default) or default)
        except (TypeError, ValueError):
            return default

    def evaluate(self, signal: Signal) -> PredictionAssessment:
        energy = signal.energy_score or 0
        opportunity = signal.opportunity_score or 0
        momentum = self._value(signal, "primary_momentum_percent", 0.0)
        relative_volume = self._value(signal, "primary_relative_volume", 1.0)
        volume_building = self._value(signal, "primary_volume_building_ratio", 1.0)
        atr_compression = self._value(signal, "primary_atr_compression_ratio", 1.0)
        range_compression = self._value(signal, "primary_range_compression_ratio", 1.0)
        ema_compression = self._value(signal, "primary_ema_compression_percent", 2.0)
        vwap_distance = self._value(signal, "primary_vwap_distance_percent", 0.0)
        agreement = self._value(signal, "agreement", 0.0)
        adx = self._value(signal, "primary_adx", 0.0)
        impulse_candles = int(self._value(signal, "primary_impulse_candles", 0.0))

        direction_sign = 1.0 if signal.side == "LONG" else -1.0
        directional_momentum = momentum * direction_sign
        directional_vwap = vwap_distance * direction_sign

        compression_score = self._clamp(
            100
            - abs(atr_compression - 0.68) * 55
            - abs(range_compression - 0.68) * 45
            - ema_compression * 25
        )
        volume_score = self._clamp(
            42 + (volume_building - 1.0) * 75 + (relative_volume - 0.8) * 35
        )
        alignment_score = self._clamp(agreement * 18 + max(0.0, adx - 12.0) * 1.4)
        pressure_score = self._clamp(
            58 + directional_vwap * 35 + directional_momentum * 18
        )
        context_score = self._clamp(
            (signal.relative_strength_score or signal.score) * 0.45
            + (signal.market_intelligence_score or signal.score) * 0.30
            + (signal.confluence_score or signal.score) * 0.25
        )

        components = {
            "energy": self._clamp(energy),
            "opportunity": self._clamp(opportunity),
            "compression": compression_score,
            "volume_building": volume_score,
            "directional_pressure": pressure_score,
            "alignment": alignment_score,
            "market_context": context_score,
        }
        prediction = self._clamp(
            components["energy"] * 0.24
            + components["opportunity"] * 0.18
            + compression_score * 0.16
            + volume_score * 0.14
            + pressure_score * 0.10
            + alignment_score * 0.08
            + context_score * 0.10
        )

        breakout_readiness = self._clamp(
            energy * 0.30
            + compression_score * 0.25
            + volume_score * 0.20
            + pressure_score * 0.15
            + alignment_score * 0.10
        )

        exhaustion = max(0.0, abs(momentum) - self.settings.prediction_max_early_momentum_percent)
        low_volume_penalty = max(0.0, self.settings.prediction_min_relative_volume - relative_volume)
        opposite_pressure = max(0.0, -directional_momentum) + max(0.0, -directional_vwap)
        fake_breakout_risk = self._clamp(
            18
            + exhaustion * 30
            + impulse_candles * 9
            + low_volume_penalty * 55
            + opposite_pressure * 24
            + (18 if signal.entry_timing in {"LATE", "CHASE"} else 0)
            + (12 if signal.opportunity_stage == "RELEASED" else 0)
        )

        valid_watch = signal.opportunity_state == "WATCH"
        ready = (
            valid_watch
            and prediction >= self.settings.prediction_ready_score
            and breakout_readiness >= self.settings.prediction_breakout_ready_score
            and fake_breakout_risk <= self.settings.prediction_max_false_breakout_risk
        )
        invalidated = (
            signal.opportunity_stage == "RELEASED"
            or signal.entry_timing in {"LATE", "CHASE"}
            or fake_breakout_risk >= self.settings.prediction_invalidation_risk
        )
        if invalidated:
            state = "INVALIDATED"
        elif ready:
            state = "READY"
        elif valid_watch and prediction >= self.settings.prediction_watch_score:
            state = "WATCH"
        else:
            state = "COLD"

        if state == "READY" and breakout_readiness >= 88:
            horizon = "1–3 свечи"
        elif state == "READY":
            horizon = "2–5 свечей"
        elif state == "WATCH":
            horizon = "3–8 свечей"
        else:
            horizon = "не определён"

        reasons = [
            f"Prediction {prediction}/100",
            f"Breakout readiness {breakout_readiness}/100",
            f"False breakout risk {fake_breakout_risk}/100",
            f"Compression {compression_score}/100",
            f"Volume building {volume_score}/100",
        ]
        if state == "READY":
            reasons.append("Сетап созрел, но ожидается отдельный Trigger Engine")
        elif state == "INVALIDATED":
            reasons.append("Ранний вход отменён: движение выпущено или риск ложного пробоя высок")
        elif state == "WATCH":
            reasons.append("Предпосылки формируются, наблюдение продолжается")

        return PredictionAssessment(
            prediction_score=prediction,
            breakout_readiness=breakout_readiness,
            false_breakout_risk=fake_breakout_risk,
            direction=signal.side,
            state=state,
            horizon=horizon,
            components=components,
            reasons=reasons,
        )

    def attach(self, signal: Signal) -> Signal:
        assessment = self.evaluate(signal)
        signal.prediction_score = assessment.prediction_score
        signal.breakout_readiness = assessment.breakout_readiness
        signal.false_breakout_risk = assessment.false_breakout_risk
        signal.prediction_direction = assessment.direction
        signal.prediction_state = assessment.state
        signal.prediction_horizon = assessment.horizon
        signal.prediction_components = assessment.components
        signal.prediction_reasons = assessment.reasons
        return signal
