from types import SimpleNamespace

from app.position_optimizer import PositionOptimizer


class Settings:
    position_optimizer_min_multiplier = 0.55
    position_optimizer_neutral_multiplier = 1.0
    position_optimizer_max_multiplier = 1.25
    position_optimizer_normal_score = 72
    position_optimizer_strong_score = 88


def signal(**overrides):
    values = dict(
        score=80, decision_score=90, confluence_score=90,
        prediction_score=90, trigger_score=90,
        entry_optimizer_score=90, entry_quality_score=85,
        market_opportunity_score=90, market_intelligence_score=85,
        entry_optimizer_action="ENTER_NOW", volatility_state="NORMAL",
        macro_guard_state="SAFE", false_breakout_risk=20,
        volatility_guard_multiplier=1.0, macro_guard_risk_multiplier=1.0,
        trigger_confirmed=True,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_strong_setup_scales_up():
    result = PositionOptimizer(Settings()).assess(signal())
    assert result.tier == "STRONG"
    assert result.multiplier == 1.25
    assert result.allowed_to_scale_up is True


def test_unconfirmed_trigger_never_scales_up():
    result = PositionOptimizer(Settings()).assess(signal(trigger_confirmed=False))
    assert result.multiplier <= 1.0
    assert result.allowed_to_scale_up is False


def test_guard_caps_multiplier_at_neutral():
    result = PositionOptimizer(Settings()).assess(
        signal(volatility_guard_multiplier=0.5)
    )
    assert result.multiplier <= 1.0
    assert "Защитный guard" in " ".join(result.reasons)


def test_chase_uses_defensive_multiplier():
    result = PositionOptimizer(Settings()).assess(
        signal(entry_optimizer_action="SKIP_CHASE")
    )
    assert result.tier == "DEFENSIVE"
    assert result.multiplier == 0.55
