from decimal import Decimal

from app.live_exchange import MexcPrivateClient
from app.multi_asset_confirm import MultiAssetConfirmService
from app.risk_manager import TradePlan


def test_tpsl_signature_payload(monkeypatch):
    monkeypatch.setattr(
        "app.live_exchange.time.time",
        lambda: 1000.0,
    )
    client = MexcPrivateClient(
        "https://api.mexc.com",
        "access",
        "secret",
    )
    params = {
        "positionId": 123,
        "vol": "1",
        "lossTrend": 1,
        "profitTrend": 1,
        "stopLossPrice": "76.2",
        "takeProfitPrice": "75.2",
    }
    headers = client._headers("POST", params)
    assert len(headers["Signature"]) == 64


def make_plan(side: str) -> TradePlan:
    return TradePlan(
        symbol="SOL_USDT",
        side=side,
        reference_price=Decimal("75.88"),
        contracts=Decimal("1"),
        contract_size=Decimal("0.1"),
        notional_usdt=Decimal("7.588"),
        risk_usdt=Decimal("0.033"),
        stop_loss=(
            Decimal("76.21")
            if side == "SHORT"
            else Decimal("75.55")
        ),
        take_profit=(
            Decimal("75.22")
            if side == "SHORT"
            else Decimal("76.54")
        ),
        leverage=1,
    )


def test_short_protection_prices():
    sl, tp = MultiAssetConfirmService.protection_prices(
        plan=make_plan("SHORT"),
        actual_entry=Decimal("75.90"),
        price_unit=Decimal("0.01"),
    )
    assert tp < Decimal("75.90") < sl


def test_long_protection_prices():
    sl, tp = MultiAssetConfirmService.protection_prices(
        plan=make_plan("LONG"),
        actual_entry=Decimal("75.90"),
        price_unit=Decimal("0.01"),
    )
    assert sl < Decimal("75.90") < tp
