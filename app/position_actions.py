from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

from app.position_intelligence import DynamicPositionManager


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


@dataclass(slots=True)
class BreakevenPlan:
    position_id: int
    symbol: str
    side: str
    stop_plan_order_id: int
    current_price: Decimal
    entry_price: Decimal
    current_stop_loss: Decimal
    take_profit: Decimal | None
    proposed_stop_loss: Decimal
    current_r: Decimal


class ConfirmedPositionActions:
    def __init__(self, settings, confirm_service) -> None:
        self.settings = settings
        self.confirm_service = confirm_service
        self.intelligence = DynamicPositionManager(settings)

    async def prepare_breakeven(
        self,
        position_id: int,
    ) -> BreakevenPlan:
        positions = await self.confirm_service.private.open_positions()
        position = next(
            (
                item
                for item in positions
                if int(item.get("positionId") or 0) == position_id
            ),
            None,
        )
        if not position:
            raise ValueError("Позиция не найдена на MEXC")

        symbol = str(position.get("symbol") or "")
        protection = await self.confirm_service.private.current_tpsl(symbol)
        active = [
            item
            for item in protection
            if str(item.get("positionId") or "") == str(position_id)
            and int(item.get("state") or 0) == 1
        ]
        if not active:
            raise ValueError("Активный TP/SL-ордер не найден")

        order = next(
            (
                item
                for item in active
                if Decimal(str(item.get("stopLossPrice") or 0)) > 0
            ),
            None,
        )
        if not order:
            raise ValueError("Активный Stop Loss не найден")

        ticker = await self.confirm_service.public_get(
            "/api/v1/contract/ticker",
            {"symbol": symbol},
        )
        current_price = Decimal(str(ticker["lastPrice"]))
        position_plan = self.intelligence.evaluate(
            position,
            current_price,
            protection,
        )
        if position_plan.current_r is None:
            raise ValueError("Невозможно рассчитать текущий R")
        if position_plan.current_r < Decimal(
            str(self.settings.position_actions_min_r_for_breakeven)
        ):
            raise ValueError(
                f"Безубыток разрешён только после "
                f"{self.settings.position_actions_min_r_for_breakeven}R"
            )

        spec = await self.confirm_service.contract_spec(symbol)
        entry = position_plan.entry_price
        buffer_fraction = Decimal(
            str(self.settings.position_actions_breakeven_buffer_percent)
        ) / Decimal("100")
        if position_plan.side == "LONG":
            proposed = entry * (Decimal("1") + buffer_fraction)
        else:
            proposed = entry * (Decimal("1") - buffer_fraction)
        proposed = floor_step(proposed, spec.price_unit)

        current_stop = Decimal(str(order["stopLossPrice"]))
        take_profit = (
            Decimal(str(order["takeProfitPrice"]))
            if Decimal(str(order.get("takeProfitPrice") or 0)) > 0
            else None
        )

        if position_plan.side == "LONG":
            if proposed >= current_price:
                raise ValueError(
                    "Новый LONG Stop Loss должен быть ниже текущей цены"
                )
            if proposed <= current_stop:
                raise ValueError(
                    "Текущий Stop Loss уже не хуже предлагаемого"
                )
        else:
            if proposed <= current_price:
                raise ValueError(
                    "Новый SHORT Stop Loss должен быть выше текущей цены"
                )
            if proposed >= current_stop:
                raise ValueError(
                    "Текущий Stop Loss уже не хуже предлагаемого"
                )

        return BreakevenPlan(
            position_id=position_id,
            symbol=symbol,
            side=position_plan.side,
            stop_plan_order_id=int(order["id"]),
            current_price=current_price,
            entry_price=entry,
            current_stop_loss=current_stop,
            take_profit=take_profit,
            proposed_stop_loss=proposed,
            current_r=position_plan.current_r,
        )

    async def execute_breakeven(
        self,
        plan: BreakevenPlan,
    ) -> dict:
        await self.confirm_service.private.modify_tpsl_plan(
            stop_plan_order_id=plan.stop_plan_order_id,
            stop_loss_price=plan.proposed_stop_loss,
            take_profit_price=plan.take_profit,
            loss_trend=1,
            profit_trend=1,
        )

        protection = await self.confirm_service.private.current_tpsl(
            plan.symbol
        )
        verified = next(
            (
                item
                for item in protection
                if int(item.get("id") or 0)
                == plan.stop_plan_order_id
                and int(item.get("state") or 0) == 1
                and Decimal(str(item.get("stopLossPrice") or 0))
                == plan.proposed_stop_loss
            ),
            None,
        )
        if not verified:
            raise RuntimeError(
                "MEXC приняла изменение, но новый Stop Loss "
                "не подтверждён повторной сверкой"
            )
        return verified
