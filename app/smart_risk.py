from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from app.risk_manager import ContractSpec

def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

@dataclass(slots=True)
class SmartRiskRequest:
    equity_usdt: Decimal
    entry_price: Decimal
    stop_loss_price: Decimal
    atr_percent: Decimal
    leverage: int
    max_notional_usdt: Decimal

@dataclass(slots=True)
class SmartRiskResult:
    risk_percent: Decimal
    risk_budget_usdt: Decimal
    contracts: Decimal
    notional_usdt: Decimal
    required_margin_usdt: Decimal
    price_risk_usdt: Decimal
    estimated_costs_usdt: Decimal
    estimated_max_loss_usdt: Decimal
    margin_usage_percent: Decimal
    warnings: list[str]

class SmartRiskEngine:
    def __init__(self, settings):
        self.settings = settings

    def volatility_multiplier(self, atr_percent: Decimal) -> Decimal:
        low = Decimal(str(self.settings.smart_risk_low_vol_atr_percent))
        high = Decimal(str(self.settings.smart_risk_high_vol_atr_percent))
        if atr_percent <= low:
            return Decimal(str(self.settings.smart_risk_low_vol_multiplier))
        if atr_percent <= high:
            return Decimal(str(self.settings.smart_risk_normal_vol_multiplier))
        if atr_percent <= high * Decimal("2"):
            return Decimal(str(self.settings.smart_risk_high_vol_multiplier))
        return Decimal(str(self.settings.smart_risk_extreme_vol_multiplier))

    def calculate(self, request: SmartRiskRequest, spec: ContractSpec) -> SmartRiskResult:
        if request.equity_usdt <= 0 or request.entry_price <= 0 or request.leverage <= 0:
            raise ValueError("Некорректные входные данные Smart Risk")
        distance = abs(request.entry_price - request.stop_loss_price)
        if distance <= 0:
            raise ValueError("Некорректная дистанция Stop Loss")

        mult = self.volatility_multiplier(request.atr_percent)
        base = Decimal(str(self.settings.smart_risk_base_percent))
        minimum = Decimal(str(self.settings.smart_risk_min_percent))
        maximum = Decimal(str(self.settings.smart_risk_max_percent))
        risk_percent = max(minimum, min(base * mult, maximum))
        budget = request.equity_usdt * risk_percent / Decimal("100")

        risk_per_contract = distance * spec.contract_size
        min_contract_risk = risk_per_contract * spec.min_vol
        if (
            self.settings.smart_risk_reject_if_min_contract_exceeds_risk
            and min_contract_risk > budget
        ):
            raise ValueError(
                f"Минимальный контракт превышает риск: "
                f"{min_contract_risk:.4f} > {budget:.4f} USDT"
            )

        contracts = floor_step(budget / risk_per_contract, spec.vol_unit)
        contracts = min(contracts, spec.max_vol)
        if contracts < spec.min_vol:
            contracts = spec.min_vol

        notional = request.entry_price * spec.contract_size * contracts
        if notional > request.max_notional_usdt:
            contracts = floor_step(
                request.max_notional_usdt /
                (request.entry_price * spec.contract_size),
                spec.vol_unit,
            )
            if contracts < spec.min_vol:
                raise ValueError("Лимит номинала ниже минимального контракта")
            notional = request.entry_price * spec.contract_size * contracts

        margin = notional / Decimal(str(request.leverage))
        margin_pct = margin / request.equity_usdt * Decimal("100")
        max_margin_pct = Decimal(str(self.settings.smart_risk_max_margin_usage_percent))
        if margin_pct > max_margin_pct:
            max_margin = request.equity_usdt * max_margin_pct / Decimal("100")
            contracts = floor_step(
                max_margin * Decimal(str(request.leverage)) /
                (request.entry_price * spec.contract_size),
                spec.vol_unit,
            )
            if contracts < spec.min_vol:
                raise ValueError("Лимит маржи ниже минимального контракта")
            notional = request.entry_price * spec.contract_size * contracts
            margin = notional / Decimal(str(request.leverage))
            margin_pct = margin / request.equity_usdt * Decimal("100")

        price_risk = risk_per_contract * contracts
        costs_pct = (
            Decimal(str(self.settings.smart_risk_fee_percent_round_trip))
            + Decimal(str(self.settings.smart_risk_slippage_percent_round_trip))
        )
        costs = notional * costs_pct / Decimal("100")
        max_loss = price_risk + costs
        warnings = []
        if max_loss > budget:
            warnings.append("Расходы повышают max loss выше чистого риска по SL")
        if request.atr_percent > Decimal(str(self.settings.smart_risk_high_vol_atr_percent)):
            warnings.append("Размер уменьшен из-за высокой волатильности")
        return SmartRiskResult(
            risk_percent=risk_percent,
            risk_budget_usdt=budget,
            contracts=contracts,
            notional_usdt=notional,
            required_margin_usdt=margin,
            price_risk_usdt=price_risk,
            estimated_costs_usdt=costs,
            estimated_max_loss_usdt=max_loss,
            margin_usage_percent=margin_pct,
            warnings=warnings,
        )
