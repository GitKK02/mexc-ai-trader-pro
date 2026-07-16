import asyncio
import logging

from app.ai_filter import AiFilter
from app.analyzer import analyze_timeframe, combine_timeframes
from app.config import Settings
from app.exchange import MexcPublicClient
from app.models import Signal

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
        if signal.score < self.settings.min_signal_score_paper:
            return None
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
        signals = [
            signal for signal in raw_signals if signal is not None
        ]
        signals.sort(key=lambda signal: signal.score, reverse=True)

        ai_limit = min(
            self.settings.scanner_ai_only_top_n,
            self.settings.max_ai_candidates,
        )
        for signal in signals[:ai_limit]:
            await self.ai.review(signal)

        return signals[: self.settings.max_signals_per_cycle]
