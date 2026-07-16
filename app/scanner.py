from app.ai_filter import AiFilter
from app.analyzer import analyze
from app.config import Settings
from app.exchange import MexcPublicClient
from app.models import Signal


class Scanner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.exchange = MexcPublicClient(settings.mexc_base_url)
        self.ai = AiFilter(
            settings.openai_api_key,
            settings.openai_model,
            settings.ai_enabled,
        )

    async def run_once(self) -> list[Signal]:
        tickers = await self.exchange.tickers()
        candidates = [
            item
            for item in tickers
            if item.symbol in self.settings.whitelist
            and item.turnover_24h >= self.settings.min_24h_turnover_usdt
            and item.spread_percent <= self.settings.max_spread_percent
        ]
        candidates.sort(key=lambda item: item.turnover_24h, reverse=True)
        candidates = candidates[: self.settings.max_deep_candidates]

        signals: list[Signal] = []
        for ticker in candidates:
            candles = await self.exchange.candles(ticker.symbol)
            signal = analyze(ticker.symbol, candles)
            if signal and signal.score >= self.settings.min_signal_score_paper:
                signals.append(signal)

        signals.sort(key=lambda signal: signal.score, reverse=True)
        for signal in signals[: self.settings.max_ai_candidates]:
            await self.ai.review(signal)
        return signals[: self.settings.max_signals_per_cycle]
