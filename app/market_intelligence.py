from dataclasses import dataclass
from statistics import median

from app.models import Signal


@dataclass(slots=True)
class MarketSnapshot:
    state: str
    long_count: int
    short_count: int
    neutral_count: int
    total_count: int
    long_percent: float
    short_percent: float
    leaders: list[str]
    laggards: list[str]


class MarketIntelligenceEngine:
    """Relative-strength and market-breadth context for scanner signals."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.last_snapshot = MarketSnapshot(
            state="UNKNOWN",
            long_count=0,
            short_count=0,
            neutral_count=0,
            total_count=0,
            long_percent=0.0,
            short_percent=0.0,
            leaders=[],
            laggards=[],
        )

    @staticmethod
    def _clamp(value: float) -> int:
        return max(0, min(round(value), 100))

    @staticmethod
    def _momentum(signal: Signal) -> float:
        diagnostics = signal.diagnostics or {}
        try:
            return float(diagnostics.get("primary_momentum_percent", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _directional_momentum(signal: Signal) -> float:
        momentum = MarketIntelligenceEngine._momentum(signal)
        return momentum if signal.side == "LONG" else -momentum

    def _snapshot(self, signals: list[Signal]) -> MarketSnapshot:
        minimum = int(getattr(self.settings, "market_breadth_min_signal_score", 55))
        long_count = sum(
            1 for signal in signals
            if signal.side == "LONG" and signal.score >= minimum
        )
        short_count = sum(
            1 for signal in signals
            if signal.side == "SHORT" and signal.score >= minimum
        )
        total = len(signals)
        neutral_count = max(0, total - long_count - short_count)
        active = max(1, long_count + short_count)
        long_percent = long_count / active * 100
        short_percent = short_count / active * 100
        threshold = float(getattr(self.settings, "market_breadth_direction_threshold_percent", 60.0))
        if long_percent >= threshold:
            state = "BULLISH"
        elif short_percent >= threshold:
            state = "BEARISH"
        elif active < max(3, round(total * 0.25)):
            state = "THIN"
        else:
            state = "MIXED"

        ranked = sorted(
            signals,
            key=lambda item: (self._directional_momentum(item), item.score),
            reverse=True,
        )
        limit = int(getattr(self.settings, "market_intelligence_leader_limit", 5))
        leaders = [item.symbol for item in ranked[:limit]]
        laggards = [item.symbol for item in reversed(ranked[-limit:])]
        return MarketSnapshot(
            state=state,
            long_count=long_count,
            short_count=short_count,
            neutral_count=neutral_count,
            total_count=total,
            long_percent=round(long_percent, 1),
            short_percent=round(short_percent, 1),
            leaders=leaders,
            laggards=laggards,
        )

    def attach_all(self, signals: list[Signal]) -> list[Signal]:
        if not signals:
            self.last_snapshot = self._snapshot([])
            return signals

        snapshot = self._snapshot(signals)
        self.last_snapshot = snapshot
        directional = [self._directional_momentum(item) for item in signals]
        market_median = median(directional) if directional else 0.0
        btc = next((item for item in signals if item.symbol == "BTC_USDT"), None)
        btc_momentum = self._momentum(btc) if btc else 0.0

        ranked = sorted(
            signals,
            key=lambda item: (self._directional_momentum(item), item.score),
            reverse=True,
        )
        ranks = {item.symbol: index for index, item in enumerate(ranked, start=1)}
        total = max(1, len(ranked))
        block_opposite = bool(
            getattr(self.settings, "market_breadth_block_strong_opposite", True)
        )
        strength_scale = max(
            0.1,
            float(getattr(self.settings, "relative_strength_percent_scale", 1.0)),
        )

        for signal in signals:
            momentum = self._momentum(signal)
            directional_momentum = self._directional_momentum(signal)
            btc_directional = btc_momentum if signal.side == "LONG" else -btc_momentum
            vs_btc = directional_momentum - btc_directional
            vs_market = directional_momentum - market_median
            rank = ranks.get(signal.symbol, total)
            rank_bonus = (1 - (rank - 1) / max(1, total - 1)) * 20 - 10
            relative_score = self._clamp(
                55
                + (vs_btc / strength_scale) * 12
                + (vs_market / strength_scale) * 10
                + rank_bonus
            )

            aligned = (
                snapshot.state == "MIXED"
                or snapshot.state == "THIN"
                or (snapshot.state == "BULLISH" and signal.side == "LONG")
                or (snapshot.state == "BEARISH" and signal.side == "SHORT")
            )
            opposite = (
                (snapshot.state == "BULLISH" and signal.side == "SHORT")
                or (snapshot.state == "BEARISH" and signal.side == "LONG")
            )
            breadth_score = 50
            if aligned and snapshot.state in {"BULLISH", "BEARISH"}:
                breadth_score = 85
            elif opposite:
                breadth_score = 20
            elif snapshot.state == "MIXED":
                breadth_score = 55
            elif snapshot.state == "THIN":
                breadth_score = 40

            score = self._clamp(relative_score * 0.65 + breadth_score * 0.35)
            allowed = not (block_opposite and opposite)
            reasons = [
                f"Relative strength: rank {rank}/{total}, score {relative_score}/100",
                f"К BTC: {vs_btc:+.2f}% | к медиане рынка: {vs_market:+.2f}%",
                f"Market breadth: {snapshot.state} — LONG {snapshot.long_percent:.1f}% / SHORT {snapshot.short_percent:.1f}%",
            ]
            if opposite:
                reasons.append("Направление сигнала против сильной ширины рынка")
            elif aligned and snapshot.state in {"BULLISH", "BEARISH"}:
                reasons.append("Направление сигнала подтверждено шириной рынка")

            signal.relative_strength_score = relative_score
            signal.relative_strength_rank = rank
            signal.relative_strength_vs_btc = round(vs_btc, 3)
            signal.relative_strength_vs_market = round(vs_market, 3)
            signal.market_breadth_state = snapshot.state
            signal.market_breadth_long_percent = snapshot.long_percent
            signal.market_breadth_short_percent = snapshot.short_percent
            signal.market_intelligence_score = score
            signal.market_intelligence_allowed = allowed
            signal.market_intelligence_reasons = reasons
        return signals
