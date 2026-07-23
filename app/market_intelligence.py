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
    top_opportunities: list[str]
    confidence: int


class MarketIntelligenceEngine:
    """Market breadth, relative strength and cross-market opportunity ranking."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.last_snapshot = self._empty_snapshot()

    @staticmethod
    def _empty_snapshot() -> MarketSnapshot:
        return MarketSnapshot("UNKNOWN", 0, 0, 0, 0, 0.0, 0.0, [], [], [], 0)

    @staticmethod
    def _clamp(value: float) -> int:
        return max(0, min(round(value), 100))

    @staticmethod
    def _momentum(signal: Signal | None) -> float:
        if signal is None:
            return 0.0
        diagnostics = signal.diagnostics or {}
        try:
            return float(diagnostics.get("primary_momentum_percent", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _directional_momentum(cls, signal: Signal) -> float:
        momentum = cls._momentum(signal)
        return momentum if signal.side == "LONG" else -momentum

    def _snapshot(self, signals: list[Signal]) -> MarketSnapshot:
        if not signals:
            return self._empty_snapshot()
        minimum = int(getattr(self.settings, "market_breadth_min_signal_score", 55))
        long_count = sum(1 for s in signals if s.side == "LONG" and s.score >= minimum)
        short_count = sum(1 for s in signals if s.side == "SHORT" and s.score >= minimum)
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
        confidence = self._clamp(max(long_percent, short_percent)) if state in {"BULLISH", "BEARISH"} else 50
        ranked = sorted(signals, key=lambda x: (self._directional_momentum(x), x.score), reverse=True)
        limit = int(getattr(self.settings, "market_intelligence_leader_limit", 5))
        return MarketSnapshot(
            state, long_count, short_count, neutral_count, total,
            round(long_percent, 1), round(short_percent, 1),
            [x.symbol for x in ranked[:limit]],
            [x.symbol for x in reversed(ranked[-limit:])], [], confidence,
        )

    def attach_all(self, signals: list[Signal]) -> list[Signal]:
        if not signals:
            self.last_snapshot = self._snapshot([])
            return signals
        snapshot = self._snapshot(signals)
        self.last_snapshot = snapshot
        directional = [self._directional_momentum(x) for x in signals]
        market_median = median(directional) if directional else 0.0
        btc = next((x for x in signals if x.symbol == "BTC_USDT"), None)
        btc_momentum = self._momentum(btc)
        ranked = sorted(signals, key=lambda x: (self._directional_momentum(x), x.score), reverse=True)
        ranks = {x.symbol: i for i, x in enumerate(ranked, 1)}
        total = max(1, len(ranked))
        block_opposite = bool(getattr(self.settings, "market_breadth_block_strong_opposite", True))
        scale = max(0.1, float(getattr(self.settings, "relative_strength_percent_scale", 1.0)))
        for signal in signals:
            directional_momentum = self._directional_momentum(signal)
            btc_directional = btc_momentum if signal.side == "LONG" else -btc_momentum
            vs_btc = directional_momentum - btc_directional
            vs_market = directional_momentum - market_median
            rank = ranks.get(signal.symbol, total)
            rank_bonus = (1 - (rank - 1) / max(1, total - 1)) * 20 - 10
            relative_score = self._clamp(55 + (vs_btc / scale) * 12 + (vs_market / scale) * 10 + rank_bonus)
            aligned = snapshot.state in {"MIXED", "THIN"} or (snapshot.state == "BULLISH" and signal.side == "LONG") or (snapshot.state == "BEARISH" and signal.side == "SHORT")
            opposite = (snapshot.state == "BULLISH" and signal.side == "SHORT") or (snapshot.state == "BEARISH" and signal.side == "LONG")
            breadth_score = 85 if aligned and snapshot.state in {"BULLISH", "BEARISH"} else 20 if opposite else 55 if snapshot.state == "MIXED" else 40
            score = self._clamp(relative_score * 0.65 + breadth_score * 0.35)
            signal.relative_strength_score = relative_score
            signal.relative_strength_rank = rank
            signal.relative_strength_vs_btc = round(vs_btc, 3)
            signal.relative_strength_vs_market = round(vs_market, 3)
            signal.market_breadth_state = snapshot.state
            signal.market_breadth_long_percent = snapshot.long_percent
            signal.market_breadth_short_percent = snapshot.short_percent
            signal.market_intelligence_score = score
            signal.market_intelligence_allowed = not (block_opposite and opposite)
            signal.market_intelligence_reasons = [
                f"Relative strength: rank {rank}/{total}, score {relative_score}/100",
                f"К BTC: {vs_btc:+.2f}% | к медиане рынка: {vs_market:+.2f}%",
                f"Market breadth: {snapshot.state} — LONG {snapshot.long_percent:.1f}% / SHORT {snapshot.short_percent:.1f}%",
            ]
            if opposite:
                signal.market_intelligence_reasons.append("Направление сигнала против сильной ширины рынка")
        return signals

    def finalize_rankings(self, signals: list[Signal]) -> list[Signal]:
        """Rank fully enriched opportunities after Prediction and Trigger engines."""
        if not signals or not bool(getattr(self.settings, "market_selection_enabled", True)):
            return signals
        ready_bonus = int(getattr(self.settings, "market_selection_ready_bonus", 5))
        trigger_bonus = int(getattr(self.settings, "market_selection_trigger_bonus", 8))
        minimum = int(getattr(self.settings, "market_selection_min_score", 68))
        top_n = max(1, int(getattr(self.settings, "market_selection_top_n", 3)))
        for signal in signals:
            score = (
                signal.score * 0.15
                + (signal.relative_strength_score or 50) * 0.15
                + (signal.market_intelligence_score or 50) * 0.15
                + (signal.opportunity_score or signal.score) * 0.20
                + (signal.prediction_score or signal.score) * 0.20
                + (signal.trigger_score or 50) * 0.15
            )
            if signal.prediction_state == "READY":
                score += ready_bonus
            if signal.trigger_confirmed:
                score += trigger_bonus
            if signal.market_intelligence_allowed is False or signal.prediction_state == "INVALIDATED" or signal.trigger_state == "INVALIDATED":
                score -= 30
            if signal.false_breakout_risk is not None:
                score -= max(0, signal.false_breakout_risk - 40) * 0.20
            signal.market_opportunity_score = self._clamp(score)
            signal.market_opportunity_selected = False
            signal.market_priority = "HOT" if signal.market_opportunity_score >= 82 else "WARM" if signal.market_opportunity_score >= minimum else "NORMAL"
        ranked = sorted(signals, key=lambda x: (x.market_opportunity_score or 0, x.trigger_confirmed, x.prediction_score or 0), reverse=True)
        for rank, signal in enumerate(ranked, 1):
            signal.market_opportunity_rank = rank
            signal.market_opportunity_selected = rank <= top_n and (signal.market_opportunity_score or 0) >= minimum
        self.last_snapshot.top_opportunities = [f"{x.symbol} {x.side} {x.market_opportunity_score}/100" for x in ranked[:top_n]]
        return signals
