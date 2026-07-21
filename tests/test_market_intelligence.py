from app.market_intelligence import MarketIntelligenceEngine
from app.models import Signal


class Settings:
    market_breadth_min_signal_score = 55
    market_breadth_direction_threshold_percent = 60.0
    market_breadth_block_strong_opposite = True
    market_intelligence_leader_limit = 3
    relative_strength_percent_scale = 1.0


def signal(symbol, side, momentum, score=80):
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
        diagnostics={"primary_momentum_percent": momentum},
    )


def test_bullish_breadth_and_leader_ranking():
    items = [
        signal("BTC_USDT", "LONG", 1.0),
        signal("SOL_USDT", "LONG", 3.0),
        signal("ETH_USDT", "LONG", 1.5),
        signal("DOGE_USDT", "SHORT", -0.4),
    ]
    engine = MarketIntelligenceEngine(Settings())
    engine.attach_all(items)
    assert engine.last_snapshot.state == "BULLISH"
    sol = next(item for item in items if item.symbol == "SOL_USDT")
    assert sol.relative_strength_rank == 1
    assert sol.relative_strength_score > 50
    assert sol.market_intelligence_allowed is True


def test_opposite_signal_is_blocked_in_strong_breadth():
    items = [
        signal("BTC_USDT", "LONG", 1.0),
        signal("SOL_USDT", "LONG", 2.0),
        signal("ETH_USDT", "LONG", 1.2),
        signal("XRP_USDT", "SHORT", -0.2),
    ]
    MarketIntelligenceEngine(Settings()).attach_all(items)
    short = next(item for item in items if item.side == "SHORT")
    assert short.market_breadth_state == "BULLISH"
    assert short.market_intelligence_allowed is False


def test_empty_market_snapshot_is_safe():
    engine = MarketIntelligenceEngine(Settings())
    assert engine.attach_all([]) == []
    assert engine.last_snapshot.total_count == 0
