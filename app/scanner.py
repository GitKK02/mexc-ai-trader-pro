import asyncio
import logging
from decimal import Decimal

from app.ai_filter import AiFilter
from app.analyzer import analyze_timeframe, combine_timeframes
from app.config import Settings
from app.exchange import MexcPublicClient
from app.models import Signal
from app.volatility_guard import VolatilityLiquidityGuard
from app.market_regime import MarketRegimeEngine
from app.macro_guard import NewsMacroGuard
from app.entry_intelligence import EntryIntelligence
from app.confluence_engine import ConfluenceEngine
from app.market_intelligence import MarketIntelligenceEngine
from app.opportunity_engine import OpportunityEngine

logger = logging.getLogger(__name__)


class Scanner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.exchange = MexcPublicClient(settings.mexc_base_url)
        self.ai = AiFilter(
            settings.openai_api_key,
            settings.openai_model,
            settings.ai_enabled,
        )
        self.volatility_guard = VolatilityLiquidityGuard(settings)
        self.market_regime_engine = MarketRegimeEngine(settings)
        self.macro_guard = NewsMacroGuard(settings)
        self.entry_intelligence = EntryIntelligence(settings)
        self.confluence_engine = ConfluenceEngine(settings)
        self.market_intelligence = MarketIntelligenceEngine(settings)
        self.opportunity_engine = OpportunityEngine(settings)
        self.near_signals: list[Signal] = []
        self.all_candidates: list[Signal] = []
        self._semaphore = asyncio.Semaphore(
            settings.scanner_max_parallel_requests
        )

    async def _candles(self, symbol: str, timeframe: str) -> list[dict]:
        async with self._semaphore:
            return await self.exchange.candles(
                symbol,
                interval=timeframe,
                limit=max(self.settings.scanner_min_history_bars, 220),
            )

    async def _btc_context(self) -> str:
        if not self.settings.scanner_btc_context_enabled:
            return "NEUTRAL"
        try:
            candles = await self._candles("BTC_USDT", "Min60")
            result = analyze_timeframe(
                "Min60",
                candles,
                min_relative_volume=0.5,
                require_volume_confirmation=False,
            )
            if result is None:
                return "NEUTRAL"
            if result.atr_percent >= 4 or (
                result.adx >= 35 and abs(result.momentum_percent) >= 2
            ):
                return "UNSTABLE"
            return "BULLISH" if result.side == "LONG" else "BEARISH"
        except Exception:
            logger.exception("BTC context analysis failed")
            return "NEUTRAL"

    async def _analyze_symbol(
        self,
        symbol: str,
        btc_context: str,
    ) -> Signal | None:
        analyses = {}
        for timeframe in self.settings.configured_timeframes:
            try:
                candles = await self._candles(symbol, timeframe)
                result = analyze_timeframe(
                    timeframe,
                    candles,
                    min_relative_volume=self.settings.scanner_min_relative_volume,
                    require_volume_confirmation=self.settings.scanner_require_volume_confirmation,
                )
                if result is None:
                    continue
                if not (
                    self.settings.scanner_min_atr_percent
                    <= result.atr_percent
                    <= self.settings.scanner_max_atr_percent
                ):
                    continue
                analyses[timeframe] = result
            except Exception:
                logger.exception(
                    "Timeframe analysis failed: %s %s",
                    symbol,
                    timeframe,
                )

        signal = combine_timeframes(symbol, analyses, btc_context)
        if signal is None:
            return None
        signal.near_signal = (
            signal.score < self.settings.min_signal_score_paper
        )
        signal.missing_points = max(
            0,
            self.settings.min_signal_score_paper - signal.score,
        )
        return signal

    async def run_once(self) -> list[Signal]:
        tickers = await self.exchange.tickers()
        candidates = [
            item
            for item in tickers
            if item.symbol in self.settings.whitelist
            and item.turnover_24h >= self.settings.min_24h_turnover_usdt
            and item.spread_percent <= self.settings.max_spread_percent
        ]
        candidates.sort(
            key=lambda item: item.turnover_24h,
            reverse=True,
        )
        candidates = candidates[: self.settings.max_deep_candidates]

        btc_context = await self._btc_context()
        raw_signals = await asyncio.gather(
            *[
                self._analyze_symbol(ticker.symbol, btc_context)
                for ticker in candidates
            ]
        )
        ticker_map = {
            ticker.symbol: ticker
            for ticker in candidates
        }
        signals = []
        for signal in raw_signals:
            if signal is None:
                continue
            ticker = ticker_map.get(signal.symbol)
            if ticker and self.settings.volatility_guard_enabled:
                signal = self.volatility_guard.attach(
                    signal,
                    turnover_24h=Decimal(
                        str(ticker.turnover_24h)
                    ),
                    spread_percent=Decimal(
                        str(ticker.spread_percent)
                    ),
                )
            if self.settings.market_regime_engine_enabled:
                signal = self.market_regime_engine.attach(signal)
            if self.settings.macro_guard_enabled:
                signal = self.macro_guard.attach(signal)
            if self.settings.entry_intelligence_enabled:
                signal = self.entry_intelligence.attach(signal)
            if self.settings.confluence_engine_enabled:
                signal = self.confluence_engine.attach(signal)
            signals.append(signal)
        if self.settings.market_intelligence_enabled:
            signals = self.market_intelligence.attach_all(signals)
        if self.settings.opportunity_engine_enabled:
            signals = [self.opportunity_engine.attach(signal) for signal in signals]
        signals.sort(
            key=lambda signal: (
                signal.score * 0.75
                + (signal.market_intelligence_score or signal.score) * 0.15
                + (signal.opportunity_score or signal.score) * 0.10
            ),
            reverse=True,
        )
        self.all_candidates = signals
        qualified = [
            signal
            for signal in signals
            if signal.score >= self.settings.min_signal_score_paper
        ]
        self.near_signals = [
            signal
            for signal in signals
            if self.settings.scanner_near_signal_score
            <= signal.score
            < self.settings.min_signal_score_paper
        ]

        ai_limit = min(
            self.settings.scanner_ai_only_top_n,
            self.settings.max_ai_candidates,
        )
        for signal in qualified[:ai_limit]:
            await self.ai.review(signal)

        return qualified[: self.settings.max_signals_per_cycle]
