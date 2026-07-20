from types import SimpleNamespace

from app.confluence_engine import ConfluenceEngine
from app.models import Signal


def settings(**overrides):
    values = dict(
        confluence_min_adx=18.0,
        confluence_min_scanner_score=72,
        confluence_min_relative_volume=0.8,
        confluence_min_timeframe_agreement=3,
        confluence_min_entry_quality=65,
        confluence_min_confirmations=6,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def signal(**overrides):
    values = dict(
        symbol="BTC_USDT",
        side="LONG",
        score=85,
        entry=100.0,
        stop_loss=99.0,
        tp1=101.0,
        tp2=102.0,
        atr=1.0,
        reasons=[],
        market_regime="TREND",
        detailed_regime="STRONG_BULL_TREND",
        btc_context="BULLISH",
        diagnostics={
            "primary_adx": 25,
            "primary_relative_volume": 1.2,
            "agreement": 4,
        },
        timeframe_scores={"Min5": 80, "Min15": 85},
        entry_quality_score=82,
        entry_timing="GOOD",
        entry_allowed=True,
        portfolio_allowed=True,
        regime_allowed=True,
        volatility_guard_allowed=True,
        macro_guard_allowed=True,
    )
    values.update(overrides)
    return Signal(**values)


def test_strong_signal_has_full_confluence():
    result = ConfluenceEngine(settings()).evaluate(signal())
    assert result.confirmations == 8
    assert result.score == 100
    assert result.allowed is True


def test_late_low_volume_signal_is_blocked():
    result = ConfluenceEngine(settings()).evaluate(
        signal(
            entry_quality_score=45,
            entry_timing="LATE",
            diagnostics={
                "primary_adx": 12,
                "primary_relative_volume": 0.4,
                "agreement": 1,
            },
            market_regime="RANGE",
            detailed_regime="SIDEWAYS",
            btc_context="UNSTABLE",
        )
    )
    assert result.confirmations < 6
    assert result.allowed is False
    assert result.score < 75


def test_attach_populates_signal_fields():
    item = ConfluenceEngine(settings()).attach(signal())
    assert item.confluence_confirmations == 8
    assert item.confluence_total == 8
    assert item.confluence_checks["entry"] is True
