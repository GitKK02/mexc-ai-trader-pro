from dataclasses import dataclass

from app.models import MarketTicker


@dataclass(slots=True)
class WhitelistBuildResult:
    symbols: set[str]
    rejected: dict[str, int]


class LiveWhitelistManager:
    def __init__(self, settings, database, public_client, public_get) -> None:
        self.settings = settings
        self.database = database
        self.public_client = public_client
        self.public_get = public_get

    def effective(self) -> set[str]:
        return self.database.effective_live_whitelist(
            self.settings.live_whitelist
        )

    def save(self, symbols: set[str]) -> set[str]:
        normalized = {
            symbol.strip().upper()
            for symbol in symbols
            if symbol.strip()
        }
        self.database.set_live_whitelist(normalized)
        return normalized

    def allow(self, symbol: str) -> set[str]:
        symbols = self.effective()
        symbols.add(symbol.strip().upper())
        return self.save(symbols)

    def deny(self, symbol: str) -> set[str]:
        symbols = self.effective()
        symbols.discard(symbol.strip().upper())
        return self.save(symbols)

    def clear(self) -> set[str]:
        return self.save(set())

    async def _contract_map(self) -> dict[str, dict]:
        data = await self.public_get(
            "/api/v1/contract/detail/country"
        )
        if isinstance(data, dict):
            data = [data]
        return {
            str(item.get("symbol") or "").upper(): item
            for item in (data or [])
            if item.get("symbol")
        }

    def _eligible(
        self,
        ticker: MarketTicker,
        contract: dict | None,
    ) -> tuple[bool, str]:
        if not ticker.symbol.endswith("_USDT"):
            return False, "not_usdt"
        if ticker.turnover_24h < self.settings.whitelist_min_turnover_usdt:
            return False, "turnover"
        if ticker.spread_percent > self.settings.whitelist_max_spread_percent:
            return False, "spread"
        if contract is None:
            return False, "contract_missing"
        if (
            self.settings.whitelist_require_api_allowed
            and not bool(contract.get("apiAllowed"))
        ):
            return False, "api_not_allowed"
        if (
            self.settings.whitelist_require_active_state
            and int(contract.get("state", 99)) != 0
        ):
            return False, "inactive"
        return True, "ok"

    async def build_top(self, limit: int | None = None) -> WhitelistBuildResult:
        tickers = await self.public_client.tickers()
        contracts = await self._contract_map()
        rejected: dict[str, int] = {}
        eligible: list[MarketTicker] = []
        for ticker in tickers:
            ok, reason = self._eligible(
                ticker,
                contracts.get(ticker.symbol),
            )
            if ok:
                eligible.append(ticker)
            else:
                rejected[reason] = rejected.get(reason, 0) + 1
        eligible.sort(
            key=lambda ticker: ticker.turnover_24h,
            reverse=True,
        )
        selected = eligible[: limit or self.settings.whitelist_top_limit]
        symbols = {ticker.symbol for ticker in selected}
        self.save(symbols)
        return WhitelistBuildResult(symbols, rejected)

    async def build_bluechips(self) -> WhitelistBuildResult:
        tickers = {
            ticker.symbol: ticker
            for ticker in await self.public_client.tickers()
        }
        contracts = await self._contract_map()
        symbols: set[str] = set()
        rejected: dict[str, int] = {}
        for symbol in self.settings.whitelist_bluechip_symbols:
            ticker = tickers.get(symbol)
            if ticker is None:
                rejected["ticker_missing"] = rejected.get("ticker_missing", 0) + 1
                continue
            ok, reason = self._eligible(ticker, contracts.get(symbol))
            if ok:
                symbols.add(symbol)
            else:
                rejected[reason] = rejected.get(reason, 0) + 1
        self.save(symbols)
        return WhitelistBuildResult(symbols, rejected)
