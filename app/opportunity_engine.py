from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import Settings
from app.models import Signal


@dataclass(slots=True)
class OpportunityAssessment:
    energy_score: int
    opportunity_score: int
    stage: str
    state: str
    heat: str
    expected_direction: str
    components: dict[str, int]
    reasons: list[str]


@dataclass(slots=True)
class HeatQueueItem:
    symbol: str
    energy_score: int
    opportunity_score: int
    stage: str
    heat: str
    expected_direction: str
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HeatQueue:
    """In-memory priority queue for markets that are preparing a move.

    v1.6.0 deliberately keeps this queue execution-neutral.  It is consumed by
    later Prediction/Trigger releases and must never open a trade by itself.
    """

    def __init__(self, max_items: int = 50) -> None:
        self.max_items = max(1, int(max_items))
        self._items: dict[str, HeatQueueItem] = {}

    def update(self, assessment: OpportunityAssessment, symbol: str) -> None:
        if assessment.heat == "COLD":
            self._items.pop(symbol, None)
            return
        self._items[symbol] = HeatQueueItem(
            symbol=symbol,
            energy_score=assessment.energy_score,
            opportunity_score=assessment.opportunity_score,
            stage=assessment.stage,
            heat=assessment.heat,
            expected_direction=assessment.expected_direction,
        )
        if len(self._items) > self.max_items:
            ordered = sorted(
                self._items.values(),
                key=lambda item: (item.opportunity_score, item.energy_score),
                reverse=True,
            )[: self.max_items]
            self._items = {item.symbol: item for item in ordered}

    def snapshot(self) -> list[HeatQueueItem]:
        return sorted(
            self._items.values(),
            key=lambda item: (item.opportunity_score, item.energy_score),
            reverse=True,
        )


class OpportunityEngine:
    """Detects market energy before a conventional entry signal matures."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.heat_queue = HeatQueue(settings.opportunity_heat_queue_max_items)

    @staticmethod
    def _clamp(value: float) -> int:
        return max(0, min(100, int(round(value))))

    @staticmethod
    def _value(signal: Signal, name: str, default: float = 0.0) -> float:
        try:
            return float((signal.diagnostics or {}).get(name, default) or default)
        except (TypeError, ValueError):
            return default

    def evaluate(self, signal: Signal) -> OpportunityAssessment:
        atr_compression = self._value(signal, "primary_atr_compression_ratio", 1.0)
        ema_compression = self._value(signal, "primary_ema_compression_percent", 2.0)
        range_compression = self._value(signal, "primary_range_compression_ratio", 1.0)
        volume_building = self._value(signal, "primary_volume_building_ratio", 1.0)
        vwap_distance = self._value(signal, "primary_vwap_distance_percent", 0.0)
        momentum = abs(self._value(signal, "primary_momentum_percent", 0.0))
        agreement = self._value(signal, "agreement", 0.0)
        relative_strength = signal.relative_strength_score or signal.score

        # Compression is strongest when current volatility/range is 55-80% of
        # its previous baseline.  Extremely dead markets are intentionally not
        # awarded a perfect score.
        atr_score = self._clamp(100 - abs(atr_compression - 0.68) * 130)
        ema_score = self._clamp(100 - ema_compression * 55)
        range_score = self._clamp(100 - abs(range_compression - 0.65) * 120)
        volume_score = self._clamp(45 + (volume_building - 1.0) * 90)
        vwap_score = self._clamp(100 - abs(vwap_distance) * 45)
        structure_score = self._clamp(signal.score * 0.65 + agreement * 8)
        relative_score = self._clamp(relative_strength)

        # A setup should be building, not already exhausted.  Moderate momentum
        # is useful; a large move means the release has probably happened.
        if momentum <= 0.25:
            momentum_score = 55
        elif momentum <= 0.90:
            momentum_score = self._clamp(70 + momentum * 25)
        elif momentum <= 1.60:
            momentum_score = self._clamp(95 - (momentum - 0.9) * 45)
        else:
            momentum_score = self._clamp(55 - (momentum - 1.6) * 25)

        components = {
            "atr_compression": atr_score,
            "ema_compression": ema_score,
            "range_compression": range_score,
            "volume_building": volume_score,
            "vwap_balance": vwap_score,
            "structure": structure_score,
            "momentum_building": momentum_score,
            "relative_strength": relative_score,
        }
        weights = {
            "atr_compression": 0.16,
            "ema_compression": 0.14,
            "range_compression": 0.14,
            "volume_building": 0.15,
            "vwap_balance": 0.10,
            "structure": 0.12,
            "momentum_building": 0.09,
            "relative_strength": 0.10,
        }
        energy = self._clamp(sum(components[key] * weights[key] for key in components))

        entry_quality = signal.entry_quality_score or signal.score
        confluence = signal.confluence_score or signal.score
        market = signal.market_intelligence_score or signal.score
        opportunity = self._clamp(
            energy * 0.55
            + entry_quality * 0.15
            + confluence * 0.15
            + market * 0.15
        )

        released = (
            momentum >= self.settings.opportunity_released_momentum_percent
            or signal.entry_timing in {"LATE", "CHASE"}
        )
        if released:
            stage = "RELEASED"
        elif energy >= self.settings.opportunity_charged_score:
            stage = "CHARGED"
        elif energy >= self.settings.opportunity_building_score:
            stage = "BUILDING"
        else:
            stage = "COLD"

        state = "WATCH" if stage in {"BUILDING", "CHARGED"} else stage
        if energy >= self.settings.opportunity_hot_score and state == "WATCH":
            heat = "HOT"
        elif energy >= self.settings.opportunity_warm_score and state == "WATCH":
            heat = "WARM"
        else:
            heat = "COLD"

        reasons = [
            f"ATR compression {atr_score}/100",
            f"EMA compression {ema_score}/100",
            f"Range compression {range_score}/100",
            f"Volume building {volume_score}/100",
        ]
        strongest = sorted(components.items(), key=lambda item: item[1], reverse=True)[:2]
        reasons.extend(f"Сильный фактор: {name} {score}/100" for name, score in strongest)
        if released:
            reasons.append("Импульс уже выпущен: ранний WATCH не создаётся")
        elif stage == "CHARGED":
            reasons.append("Рынок заряжен, ожидается отдельный trigger")
        elif stage == "BUILDING":
            reasons.append("Энергия накапливается, пара помещена в наблюдение")

        return OpportunityAssessment(
            energy_score=energy,
            opportunity_score=opportunity,
            stage=stage,
            state=state,
            heat=heat,
            expected_direction=signal.side,
            components=components,
            reasons=reasons,
        )

    def attach(self, signal: Signal) -> Signal:
        assessment = self.evaluate(signal)
        signal.energy_score = assessment.energy_score
        signal.opportunity_score = assessment.opportunity_score
        signal.opportunity_stage = assessment.stage
        signal.opportunity_state = assessment.state
        signal.opportunity_heat = assessment.heat
        signal.opportunity_direction = assessment.expected_direction
        signal.opportunity_components = assessment.components
        signal.opportunity_reasons = assessment.reasons
        self.heat_queue.update(assessment, signal.symbol)
        return signal
