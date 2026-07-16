from decimal import Decimal
import pytest
from app.risk_manager import ContractSpec
from app.smart_risk import SmartRiskEngine, SmartRiskRequest

class Settings:
    smart_risk_base_percent=0.10
    smart_risk_min_percent=0.03
    smart_risk_max_percent=0.25
    smart_risk_low_vol_atr_percent=0.60
    smart_risk_high_vol_atr_percent=2.50
    smart_risk_low_vol_multiplier=1.10
    smart_risk_normal_vol_multiplier=1.00
    smart_risk_high_vol_multiplier=0.60
    smart_risk_extreme_vol_multiplier=0.35
    smart_risk_fee_percent_round_trip=0.11
    smart_risk_slippage_percent_round_trip=0.06
    smart_risk_max_margin_usage_percent=15.0
    smart_risk_reject_if_min_contract_exceeds_risk=True

SPEC = ContractSpec(
    symbol="BTC_USDT", contract_size=Decimal("0.0001"),
    min_vol=Decimal("1"), max_vol=Decimal("100000"),
    vol_unit=Decimal("1"), price_unit=Decimal("0.1"),
    api_allowed=True, state=0, max_leverage=20,
)

def req(atr="1", leverage=2):
    return SmartRiskRequest(
        equity_usdt=Decimal("1000"), entry_price=Decimal("60000"),
        stop_loss_price=Decimal("59400"), atr_percent=Decimal(atr),
        leverage=leverage, max_notional_usdt=Decimal("200"),
    )

def test_normal():
    r = SmartRiskEngine(Settings()).calculate(req(), SPEC)
    assert r.risk_percent == Decimal("0.10")
    assert r.notional_usdt <= Decimal("200")
    assert r.estimated_max_loss_usdt > r.price_risk_usdt

def test_high_vol_reduces():
    e = SmartRiskEngine(Settings())
    assert e.calculate(req("3"), SPEC).contracts <= e.calculate(req("1"), SPEC).contracts

def test_margin_cap():
    assert SmartRiskEngine(Settings()).calculate(req(leverage=1), SPEC).margin_usage_percent <= Decimal("15")

def test_tiny_equity_rejected():
    q = SmartRiskRequest(
        equity_usdt=Decimal("1"), entry_price=Decimal("60000"),
        stop_loss_price=Decimal("50000"), atr_percent=Decimal("1"),
        leverage=1, max_notional_usdt=Decimal("100"),
    )
    with pytest.raises(ValueError):
        SmartRiskEngine(Settings()).calculate(q, SPEC)
