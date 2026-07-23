from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import Settings
from app.models import Signal


@dataclass(slots=True)
class TriggerSnapshot:
    prediction_score: int
    breakout_readiness: int
    relative_volume: float
    momentum_percent: float
    entry: float
    observed_at: datetime


@dataclass(slots=True)
class TriggerAssessment:
    trigger_score: int
    state: str
    trigger_type: str
    confirmed: bool
    components: dict[str, int]
    reasons: list[str]


class TriggerEngine:
    """Confirms the transition from a mature WATCH setup to an early trigger.

    The engine compares consecutive scanner observations. It never opens an
    order by itself; TRIGGERED is only a decision input for a later execution
    flow. This avoids treating a single noisy candle as an entry command.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._snapshots: dict[str, TriggerSnapshot] = {}

    @staticmethod
    def _clamp(value: float) -> int:
        return max(0, min(100, int(round(value))))

    @staticmethod
    def _value(signal: Signal, name: str, default: float = 0.0) -> float:
        try:
            return float((signal.diagnostics or {}).get(name, default) or default)
        except (TypeError, ValueError):
            return default

    def evaluate(self, signal: Signal) -> TriggerAssessment:
        prediction = signal.prediction_score or 0
        readiness = signal.breakout_readiness or 0
        false_risk = signal.false_breakout_risk or 100
        relative_volume = self._value(signal, "primary_relative_volume", 0.0)
        momentum = self._value(signal, "primary_momentum_percent", 0.0)
        breakout_level = self._value(signal, "primary_breakout_level", signal.entry)
        previous = self._snapshots.get(signal.symbol)

        direction_sign = 1.0 if signal.side == "LONG" else -1.0
        directional_momentum = momentum * direction_sign
        breakout_distance_percent = 0.0
        if breakout_level > 0:
            breakout_distance_percent = (
                (signal.entry - breakout_level) / breakout_level * 100 * direction_sign
            )

        prediction_acceleration = 0
        volume_acceleration = 0.0
        momentum_acceleration = 0.0
        if previous is not None:
            prediction_acceleration = prediction - previous.prediction_score
            volume_acceleration = relative_volume - previous.relative_volume
            momentum_acceleration = (momentum - previous.momentum_percent) * direction_sign

        momentum_score = self._clamp(
            45 + directional_momentum * 35 + max(0.0, momentum_acceleration) * 45
        )
        breakout_score = self._clamp(48 + breakout_distance_percent * 90)
        volume_score = self._clamp(
            35 + relative_volume * 35 + max(0.0, volume_acceleration) * 55
        )
        acceleration_score = self._clamp(
            50 + prediction_acceleration * 5 + max(0.0, momentum_acceleration) * 50
        )
        safety_score = self._clamp(100 - false_risk)

        components = {
            "prediction": self._clamp(prediction),
            "readiness": self._clamp(readiness),
            "momentum_activation": momentum_score,
            "breakout_activation": breakout_score,
            "volume_confirmation": volume_score,
            "acceleration": acceleration_score,
            "safety": safety_score,
        }
        trigger_score = self._clamp(
            components["prediction"] * 0.18
            + components["readiness"] * 0.18
            + momentum_score * 0.18
            + breakout_score * 0.16
            + volume_score * 0.14
            + acceleration_score * 0.08
            + safety_score * 0.08
        )

        mature = signal.prediction_state == "READY"
        invalidated = (
            signal.prediction_state == "INVALIDATED"
            or signal.opportunity_stage == "RELEASED"
            or signal.entry_timing in {"LATE", "CHASE"}
            or false_risk >= self.settings.trigger_invalidation_risk
        )
        has_history = previous is not None
        momentum_confirmed = (
            directional_momentum >= self.settings.trigger_min_directional_momentum_percent
        )
        volume_confirmed = relative_volume >= self.settings.trigger_min_relative_volume
        breakout_confirmed = (
            breakout_distance_percent >= self.settings.trigger_min_breakout_distance_percent
        )
        acceleration_confirmed = (
            prediction_acceleration >= self.settings.trigger_min_prediction_acceleration
            or momentum_acceleration >= self.settings.trigger_min_momentum_acceleration_percent
        )
        confirmations = sum(
            (momentum_confirmed, volume_confirmed, breakout_confirmed, acceleration_confirmed)
        )
        confirmed = (
            mature
            and has_history
            and trigger_score >= self.settings.trigger_ready_score
            and confirmations >= self.settings.trigger_min_confirmations
            and false_risk <= self.settings.trigger_max_false_breakout_risk
        )

        if invalidated:
            state = "INVALIDATED"
        elif confirmed:
            state = "TRIGGERED"
        elif mature:
            state = "ARMED"
        elif signal.prediction_state == "WATCH":
            state = "WATCH"
        else:
            state = "COLD"

        if breakout_confirmed and volume_confirmed:
            trigger_type = "BREAKOUT"
        elif momentum_confirmed and acceleration_confirmed:
            trigger_type = "MOMENTUM_RELEASE"
        elif mature:
            trigger_type = "AWAITING_CONFIRMATION"
        else:
            trigger_type = "NONE"

        reasons = [
            f"Trigger score {trigger_score}/100",
            f"Подтверждения {confirmations}/4",
            f"Directional momentum {directional_momentum:+.3f}%",
            f"Relative volume {relative_volume:.2f}x",
            f"Breakout distance {breakout_distance_percent:+.3f}%",
        ]
        if state == "TRIGGERED":
            reasons.append("Ранний триггер подтверждён двумя последовательными наблюдениями")
        elif state == "ARMED" and not has_history:
            reasons.append("Сетап вооружён: требуется следующее наблюдение для защиты от шума")
        elif state == "ARMED":
            reasons.append("Сетап созрел, но подтверждений триггера пока недостаточно")
        elif state == "INVALIDATED":
            reasons.append("Триггер отменён: вход запоздал или риск ложного движения высок")

        self._snapshots[signal.symbol] = TriggerSnapshot(
            prediction_score=prediction,
            breakout_readiness=readiness,
            relative_volume=relative_volume,
            momentum_percent=momentum,
            entry=signal.entry,
            observed_at=datetime.now(timezone.utc),
        )
        return TriggerAssessment(
            trigger_score=trigger_score,
            state=state,
            trigger_type=trigger_type,
            confirmed=confirmed,
            components=components,
            reasons=reasons,
        )

    def attach(self, signal: Signal) -> Signal:
        assessment = self.evaluate(signal)
        signal.trigger_score = assessment.trigger_score
        signal.trigger_state = assessment.state
        signal.trigger_type = assessment.trigger_type
        signal.trigger_confirmed = assessment.confirmed
        signal.trigger_components = assessment.components
        signal.trigger_reasons = assessment.reasons
        return signal
