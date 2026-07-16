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
