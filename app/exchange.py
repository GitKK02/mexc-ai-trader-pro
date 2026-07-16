import aiohttp

from app.models import MarketTicker


class MexcPublicClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def tickers(self) -> list[MarketTicker]:
        url = f"{self.base_url}/api/v1/contract/ticker"
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                payload = await response.json()

        raw_items = payload.get("data", [])
        items: list[MarketTicker] = []
        for raw in raw_items:
            try:
                symbol = str(raw["symbol"]).upper()
                last = float(raw.get("lastPrice") or 0)
                bid = float(raw.get("bid1") or raw.get("bidPrice") or 0)
                ask = float(raw.get("ask1") or raw.get("askPrice") or 0)
                turnover = float(raw.get("amount24") or raw.get("turnover24") or 0)
                if last > 0:
                    items.append(
                        MarketTicker(
                            symbol=symbol,
                            last_price=last,
                            bid=bid,
                            ask=ask,
                            turnover_24h=turnover,
                        )
                    )
            except (KeyError, TypeError, ValueError):
                continue
        return items

    async def candles(self, symbol: str, interval: str = "Min15", limit: int = 260) -> list[dict]:
        url = f"{self.base_url}/api/v1/contract/kline/{symbol}"
        params = {"interval": interval, "limit": limit}
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                payload = await response.json()

        data = payload.get("data", {})
        opens = data.get("open", [])
        closes = data.get("close", [])
        highs = data.get("high", [])
        lows = data.get("low", [])
        volumes = data.get("vol", [])
        result = []
        for open_price, close, high, low, volume in zip(opens, closes, highs, lows, volumes):
            result.append(
                {
                    "open": float(open_price),
                    "close": float(close),
                    "high": float(high),
                    "low": float(low),
                    "volume": float(volume),
                }
            )
        return result
