from decimal import Decimal

from app.models import Signal
from app.portfolio_manager import (
    PortfolioPosition,
    PortfolioRiskManager,
)


class Settings:
    portfolio_correlation_groups = (
        "BTC:BTC_USDT;"
        "L1_BETA:SOL_USDT,AVAX_USDT,SUI_USDT;"
        "LARGE_CAP:ETH_USDT,BNB_USDT"
    )
    portfolio_block_same_symbol = True
    portfolio_max_total_risk_percent = 0.50
    portfolio_max_same_direction_risk_percent = 0.35
    portfolio_max_group_risk_percent = 0.25
    portfolio_max_positions_per_group = 1
    portfolio_min_adjusted_score_confirm = 80
    portfolio_reduce_score_same_direction = 8
    portfolio_reduce_score_same_group = 15
    live_max_risk_per_trade_percent = 0.10
    live_risk_per_trade_percent = 0.05

    @property
    def correlation_groups(self):
        groups = {}
        for raw_group in self.portfolio_correlation_groups.split(";"):
            name, raw_symbols = raw_group.split(":", 1)
            groups[name] = set(raw_symbols.split(","))
        return groups


def signal(symbol: str, side: str = "LONG", score: int = 90):
    return Signal(
        symbol=symbol,
        side=side,
        score=score,
        entry=100,
        stop_loss=99,
        tp1=101,
        tp2=102,
        atr=1,
        reasons=["test"],
    )


def test_same_group_is_blocked():
    manager = PortfolioRiskManager(Settings())
    positions = [
        PortfolioPosition(
            symbol="SOL_USDT",
            side="LONG",
            risk_percent=Decimal("0.10"),
        )
    ]
    result = manager.assess(
        signal("AVAX_USDT"),
        positions,
        Decimal("0.05"),
    )
    assert result.allowed is False
    assert result.correlation_group == "L1_BETA"
    assert result.adjusted_score == 67


def test_different_group_is_allowed():
    manager = PortfolioRiskManager(Settings())
    positions = [
        PortfolioPosition(
            symbol="BTC_USDT",
            side="LONG",
            risk_percent=Decimal("0.10"),
        )
    ]
    result = manager.assess(
        signal("ETH_USDT", score=95),
        positions,
        Decimal("0.05"),
    )
    assert result.allowed is True
    assert result.adjusted_score == 87


def test_duplicate_symbol_is_blocked():
    manager = PortfolioRiskManager(Settings())
    positions = [
        PortfolioPosition(
            symbol="ETH_USDT",
            side="SHORT",
            risk_percent=Decimal("0.05"),
        )
    ]
    result = manager.assess(
        signal("ETH_USDT", side="LONG"),
        positions,
        Decimal("0.05"),
    )
    assert result.allowed is False
    assert result.adjusted_score == 0


def test_total_risk_cap():
    manager = PortfolioRiskManager(Settings())
    positions = [
        PortfolioPosition(
            symbol="BTC_USDT",
            side="LONG",
            risk_percent=Decimal("0.48"),
        )
    ]
    result = manager.assess(
        signal("ETH_USDT", score=99),
        positions,
        Decimal("0.05"),
    )
    assert result.allowed is False
    assert result.total_risk_after == Decimal("0.53")
