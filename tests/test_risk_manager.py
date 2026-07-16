from decimal import Decimal
import pytest

from app.risk_manager import ContractSpec, build_trade_plan


SPEC = ContractSpec(
    symbol="BTC_USDT",
    contract_size=Decimal("0.0001"),
    min_vol=Decimal("1"),
    max_vol=Decimal("10000"),
    vol_unit=Decimal("1"),
    price_unit=Decimal("0.1"),
    api_allowed=True,
    state=0,
    max_leverage=10,
)


def test_dynamic_contract_sizing():
    plan = build_trade_plan(
        symbol="BTC_USDT",
        side="LONG",
        price=Decimal("60000"),
        raw_stop=Decimal("59400"),
        equity_usdt=Decimal("1000"),
        risk_percent=Decimal("0.1"),
        max_notional_usdt=Decimal("100"),
        leverage=1,
        take_profit_r=Decimal("2"),
        spec=SPEC,
    )
    assert plan.contracts >= 1
    assert plan.notional_usdt <= Decimal("100")
    assert plan.stop_loss < plan.reference_price < plan.take_profit


def test_rejects_unavailable_contract():
    bad = ContractSpec(
        symbol=SPEC.symbol, contract_size=SPEC.contract_size, min_vol=SPEC.min_vol,
        max_vol=SPEC.max_vol, vol_unit=SPEC.vol_unit, price_unit=SPEC.price_unit,
        api_allowed=False, state=SPEC.state, max_leverage=SPEC.max_leverage,
    )
    with pytest.raises(ValueError):
        build_trade_plan(
            symbol="BTC_USDT", side="LONG", price=Decimal("60000"),
            raw_stop=Decimal("59400"), equity_usdt=Decimal("1000"),
            risk_percent=Decimal("0.1"), max_notional_usdt=Decimal("100"),
            leverage=1, take_profit_r=Decimal("2"), spec=bad,
        )
