from dataclasses import dataclass


@dataclass(slots=True)
class MarketTicker:
    symbol: str
    last_price: float
    bid: float
    ask: float
    turnover_24h: float

    @property
    def spread_percent(self) -> float:
        if self.bid <= 0:
            return 999.0
        return ((self.ask - self.bid) / self.bid) * 100


@dataclass(slots=True)
class Signal:
    symbol: str
    side: str
    score: int
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    atr: float
    reasons: list[str]
    ai_decision: str = "SKIPPED"
    ai_summary: str = ""
    strategy: str = "Trend Pullback / Momentum"
    market_regime: str = "UNKNOWN"
    btc_context: str = "NEUTRAL"
    timeframe_scores: dict[str, int] | None = None
    diagnostics: dict[str, float | str] | None = None
    portfolio_score: int | None = None
    portfolio_allowed: bool | None = None
    portfolio_group: str = ""
    portfolio_reasons: list[str] | None = None
    decision_score: int | None = None
    decision_action: str = "WAIT"
    decision_confidence: str = "LOW"
    decision_reasons: list[str] | None = None
    component_scores: dict[str, int] | None = None
    volatility_state: str = "NORMAL"
    liquidity_state: str = "NORMAL"
    volatility_guard_allowed: bool | None = None
    volatility_guard_multiplier: float = 1.0
    volatility_guard_reasons: list[str] | None = None
    detailed_regime: str = "UNKNOWN"
    regime_score_adjustment: int = 0
    regime_allowed: bool | None = None
    regime_reasons: list[str] | None = None
    macro_guard_state: str = "SAFE"
    macro_guard_allowed: bool | None = None
    macro_guard_risk_multiplier: float = 1.0
    macro_guard_reasons: list[str] | None = None
    near_signal: bool = False
    missing_points: int = 0
    watchlist_delta: int = 0
    watchlist_streak: int = 1
    watchlist_status: str = "NEW"
    entry_quality_score: int | None = None
    entry_timing: str = "UNKNOWN"
    entry_phase: str = "SETUP"
    entry_allowed: bool | None = None
    entry_distance_atr: float = 0.0
    entry_distance_percent: float = 0.0
    entry_remaining_tp1_r: float = 0.0
    entry_reasons: list[str] | None = None
    decision_created_at: str = ""
    confluence_score: int | None = None
    confluence_confirmations: int = 0
    confluence_total: int = 0
    confluence_allowed: bool | None = None
    confluence_checks: dict[str, bool] | None = None
    confluence_reasons: list[str] | None = None
    relative_strength_score: int | None = None
    relative_strength_rank: int = 0
    relative_strength_vs_btc: float = 0.0
    relative_strength_vs_market: float = 0.0
    market_breadth_state: str = "UNKNOWN"
    market_breadth_long_percent: float = 0.0
    market_breadth_short_percent: float = 0.0
    market_intelligence_score: int | None = None
    market_intelligence_allowed: bool | None = None
    market_intelligence_reasons: list[str] | None = None


@dataclass(slots=True)
class PaperPosition:
    id: int
    symbol: str
    side: str
    status: str
    entry_price: float
    current_price: float
    initial_quantity: float
    remaining_quantity: float
    stop_loss: float
    initial_stop_loss: float
    tp1: float
    tp2: float
    atr: float
    leverage: int
    risk_amount: float
    realized_pnl: float
    fees: float
    tp1_done: bool
    tp2_done: bool
    highest_price: float
    lowest_price: float
    opened_at: str
    closed_at: str | None
    close_reason: str | None
