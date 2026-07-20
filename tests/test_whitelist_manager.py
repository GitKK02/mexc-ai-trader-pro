import asyncio
from app.live_database import LiveDatabase
from app.models import MarketTicker
from app.whitelist_manager import LiveWhitelistManager


class Settings:
    live_whitelist = {"BTC_USDT"}
    whitelist_min_turnover_usdt = 20_000_000
    whitelist_max_spread_percent = 0.20
    whitelist_require_api_allowed = True
    whitelist_require_active_state = True
    whitelist_top_limit = 100
    whitelist_bluechip_symbols = {"BTC_USDT", "DOGE_USDT"}


class PublicClient:
    async def tickers(self):
        return [
            MarketTicker("BTC_USDT", 100, 99.95, 100.0, 100_000_000),
            MarketTicker("DOGE_USDT", 1, 0.99, 1.01, 80_000_000),
            MarketTicker("BAD_USDT", 1, 0.9, 1.1, 90_000_000),
            MarketTicker("LOW_USDT", 1, 0.999, 1.0, 1_000_000),
        ]


async def public_get(path, params=None):
    return [
        {"symbol": "BTC_USDT", "apiAllowed": True, "state": 0},
        {"symbol": "DOGE_USDT", "apiAllowed": True, "state": 0},
        {"symbol": "BAD_USDT", "apiAllowed": True, "state": 0},
        {"symbol": "LOW_USDT", "apiAllowed": True, "state": 0},
    ]


def manager(tmp_path):
    db = LiveDatabase(str(tmp_path / "trades.db"))
    return LiveWhitelistManager(Settings(), db, PublicClient(), public_get)


def test_runtime_whitelist_persists(tmp_path):
    item = manager(tmp_path)
    item.allow("DOGE_USDT")
    assert item.effective() == {"BTC_USDT", "DOGE_USDT"}
    second = manager(tmp_path)
    assert second.effective() == {"BTC_USDT", "DOGE_USDT"}


def test_deny_and_clear(tmp_path):
    item = manager(tmp_path)
    item.allow("DOGE_USDT")
    item.deny("BTC_USDT")
    assert item.effective() == {"DOGE_USDT"}
    item.clear()
    assert item.effective() == set()


def test_top_builder_filters_spread_and_turnover(tmp_path):
    item = manager(tmp_path)
    result = asyncio.run(item.build_top(100))
    assert result.symbols == {"BTC_USDT"}
    assert result.rejected["spread"] == 2
    assert result.rejected["turnover"] == 1


def test_bluechips_use_same_filters(tmp_path):
    item = manager(tmp_path)
    result = asyncio.run(item.build_bluechips())
    assert result.symbols == {"BTC_USDT"}
