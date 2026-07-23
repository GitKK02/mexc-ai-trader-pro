from app.market_intelligence import MarketIntelligenceEngine
from app.models import Signal


class Settings:
    market_selection_enabled = True
    market_selection_top_n = 2
    market_selection_min_score = 60
    market_selection_ready_bonus = 5
    market_selection_trigger_bonus = 8


def make_signal(symbol: str, opportunity: int, prediction: int, trigger: int, confirmed=False):
    return Signal(
        symbol=symbol, side="LONG", score=75, entry=100, stop_loss=99,
        tp1=101, tp2=102, atr=1, reasons=["test"],
        relative_strength_score=75, market_intelligence_score=75,
        opportunity_score=opportunity, prediction_score=prediction,
        trigger_score=trigger, prediction_state="READY",
        trigger_confirmed=confirmed,
    )


def test_selects_best_cross_market_opportunities():
    engine = MarketIntelligenceEngine(Settings())
    items = [
        make_signal("ETH_USDT", 70, 70, 60),
        make_signal("SOL_USDT", 90, 88, 85, True),
        make_signal("SUI_USDT", 84, 82, 78),
    ]
    engine.finalize_rankings(items)
    sol = next(x for x in items if x.symbol == "SOL_USDT")
    eth = next(x for x in items if x.symbol == "ETH_USDT")
    assert sol.market_opportunity_rank == 1
    assert sol.market_opportunity_selected is True
    assert eth.market_opportunity_selected is False
    assert len(engine.last_snapshot.top_opportunities) == 2


def test_invalidated_signal_receives_penalty():
    engine = MarketIntelligenceEngine(Settings())
    good = make_signal("SOL_USDT", 80, 80, 75)
    bad = make_signal("BAD_USDT", 95, 95, 95, True)
    bad.prediction_state = "INVALIDATED"
    engine.finalize_rankings([good, bad])
    assert good.market_opportunity_rank < bad.market_opportunity_rank
