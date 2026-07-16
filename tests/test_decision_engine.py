from app.decision_engine import AIDecisionEngine
from app.models import Signal


class Settings:
    decision_enter_score = 90
    decision_confirm_score = 82
    decision_wait_score = 72
    decision_require_ai_for_enter = True
    decision_block_on_ai_error = False
    decision_ai_approve_bonus = 6
    decision_ai_wait_penalty = 6
    decision_ai_reject_penalty = 30
    decision_trend_regime_bonus = 5
    decision_range_regime_penalty = 8
    decision_unstable_btc_penalty = 12
    decision_min_timeframe_agreement = 3


def signal(
    *,
    scanner=92,
    portfolio=90,
    ai="APPROVE",
    regime="TREND",
    btc="BULLISH",
    side="LONG",
    agreement=4,
):
    return Signal(
        symbol="BTC_USDT",
        side=side,
        score=scanner,
        entry=100,
        stop_loss=99,
        tp1=101,
        tp2=102,
        atr=1,
        reasons=["test"],
        ai_decision=ai,
        market_regime=regime,
        btc_context=btc,
        timeframe_scores={
            "Min5": 88,
            "Min15": 92,
            "Min60": 94,
            "Hour4": 90,
        },
        diagnostics={
            "agreement": agreement,
            "primary_adx": 30,
            "primary_relative_volume": 1.3,
        },
        portfolio_score=portfolio,
        portfolio_allowed=True,
    )


def test_strong_approved_signal_is_enter():
    result = AIDecisionEngine(Settings()).evaluate(signal())
    assert result.action == "ENTER"
    assert result.score >= 90
    assert result.confidence == "HIGH"


def test_ai_reject_blocks_entry():
    result = AIDecisionEngine(Settings()).evaluate(
        signal(ai="REJECT")
    )
    assert result.action in {"WAIT", "REJECT"}
    assert result.score < 82


def test_portfolio_rejection_blocks_live_action():
    item = signal()
    item.portfolio_allowed = False
    item.portfolio_reasons = ["Group risk exceeded"]
    result = AIDecisionEngine(Settings()).evaluate(item)
    assert result.action in {"WAIT", "REJECT"}
    assert "Portfolio Manager запретил вход" in result.reasons


def test_unstable_btc_reduces_decision():
    normal = AIDecisionEngine(Settings()).evaluate(signal())
    unstable = AIDecisionEngine(Settings()).evaluate(
        signal(btc="UNSTABLE")
    )
    assert unstable.score < normal.score


def test_ai_error_never_reaches_enter_when_required():
    result = AIDecisionEngine(Settings()).evaluate(
        signal(ai="ERROR")
    )
    assert result.action != "ENTER"
