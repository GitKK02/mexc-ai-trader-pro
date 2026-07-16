from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN


@dataclass(slots=True)
class ContractSpec:
    symbol: str
    contract_size: Decimal
    min_vol: Decimal
    max_vol: Decimal
    vol_unit: Decimal
    price_unit: Decimal
    api_allowed: bool
    state: int
    max_leverage: int


@dataclass(slots=True)
class TradePlan:
    symbol: str
    side: str
    reference_price: Decimal
    contracts: Decimal
    contract_size: Decimal
    notional_usdt: Decimal
    risk_usdt: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    leverage: int
    required_margin_usdt: Decimal = Decimal("0")
    estimated_costs_usdt: Decimal = Decimal("0")
    estimated_max_loss_usdt: Decimal = Decimal("0")
    risk_percent: Decimal = Decimal("0")
    margin_usage_percent: Decimal = Decimal("0")
    smart_risk_warnings: list[str] | None = None


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def build_trade_plan(
    *,
    symbol: str,
    side: str,
    price: Decimal,
    raw_stop: Decimal,
    equity_usdt: Decimal,
    risk_percent: Decimal,
    max_notional_usdt: Decimal,
    leverage: int,
    take_profit_r: Decimal,
    spec: ContractSpec,
) -> TradePlan:
    if not spec.api_allowed or spec.state != 0:
        raise ValueError("API-торговля для контракта недоступна")
    if leverage < 1 or leverage > spec.max_leverage:
        raise ValueError("Недопустимое плечо")
    if side not in {"LONG", "SHORT"}:
        raise ValueError("Недопустимое направление")
    stop_distance = abs(price - raw_stop)
    if stop_distance <= 0:
        raise ValueError("Некорректный Stop Loss")

    risk_budget = equity_usdt * risk_percent / Decimal("100")
    risk_per_contract = stop_distance * spec.contract_size
    if risk_per_contract <= 0:
        raise ValueError("Некорректный риск контракта")

    contracts = floor_step(risk_budget / risk_per_contract, spec.vol_unit)
    contracts = min(contracts, spec.max_vol)
    if contracts < spec.min_vol:
        raise ValueError(
            f"Минимальный контракт превышает риск: нужно минимум {spec.min_vol}, рассчитано {contracts}"
        )

    notional = price * spec.contract_size * contracts
    if notional > max_notional_usdt:
        capped = floor_step(max_notional_usdt / (price * spec.contract_size), spec.vol_unit)
        contracts = min(capped, contracts)
        if contracts < spec.min_vol:
            raise ValueError("Лимит номинала ниже минимально допустимого контракта")
        notional = price * spec.contract_size * contracts

    actual_risk = stop_distance * spec.contract_size * contracts
    price_unit = spec.price_unit
    if side == "LONG":
        stop = floor_step(raw_stop, price_unit)
        tp = floor_step(price + stop_distance * take_profit_r, price_unit)
    else:
        stop = floor_step(raw_stop, price_unit)
        tp = floor_step(price - stop_distance * take_profit_r, price_unit)

    return TradePlan(
        symbol=symbol,
        side=side,
        reference_price=price,
        contracts=contracts,
        contract_size=spec.contract_size,
        notional_usdt=notional,
        risk_usdt=actual_risk,
        stop_loss=stop,
        take_profit=tp,
        leverage=leverage,
    )
