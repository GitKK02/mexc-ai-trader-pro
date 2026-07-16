from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True)
class PositionPlan:
    position_id: str
    symbol: str
    side: str
    entry_price: Decimal
    current_price: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    current_r: Decimal | None
    action: str
    confidence: str
    reasons: list[str]


class DynamicPositionManager:
    """
    SHADOW/CONFIRM position-management advisor.

    This release intentionally does not modify exchange orders.
    It calculates lifecycle recommendations from actual MEXC positions
    and the currently visible TP/SL records.
    """

    def __init__(self, settings) -> None:
        self.settings = settings

    @staticmethod
    def _side(position: dict) -> str:
        return "LONG" if int(position.get("positionType") or 0) == 1 else "SHORT"

    @staticmethod
    def _find_protection(position_id: str, orders: list[dict]) -> tuple[Decimal | None, Decimal | None]:
        stop_loss = None
        take_profit = None
        for order in orders:
            if str(order.get("positionId") or "") != position_id:
                continue
            raw_sl = order.get("stopLossPrice")
            raw_tp = order.get("takeProfitPrice")
            if raw_sl not in (None, "", 0, "0"):
                stop_loss = Decimal(str(raw_sl))
            if raw_tp not in (None, "", 0, "0"):
                take_profit = Decimal(str(raw_tp))
        return stop_loss, take_profit

    @staticmethod
    def _current_r(
        side: str,
        entry: Decimal,
        current: Decimal,
        stop_loss: Decimal | None,
    ) -> Decimal | None:
        if stop_loss is None:
            return None
        initial_risk = abs(entry - stop_loss)
        if initial_risk <= 0:
            return None
        pnl_distance = current - entry if side == "LONG" else entry - current
        return pnl_distance / initial_risk

    def evaluate(
        self,
        position: dict,
        current_price: Decimal,
        protection_orders: list[dict],
    ) -> PositionPlan:
        position_id = str(position.get("positionId") or "")
        symbol = str(position.get("symbol") or "")
        side = self._side(position)
        entry = Decimal(
            str(
                position.get("holdAvgPrice")
                or position.get("openAvgPrice")
                or current_price
            )
        )
        stop_loss, take_profit = self._find_protection(
            position_id,
            protection_orders,
        )
        current_r = self._current_r(
            side,
            entry,
            current_price,
            stop_loss,
        )

        reasons: list[str] = []
        action = "HOLD"
        confidence = "LOW"

        if stop_loss is None:
            action = "PROTECTION_MISSING"
            confidence = "HIGH"
            reasons.append("Активный Stop Loss не найден")
        elif current_r is None:
            action = "REVIEW"
            reasons.append("Невозможно рассчитать R")
        elif current_r <= Decimal(str(self.settings.position_intelligence_exit_r)):
            action = "EXIT_REVIEW"
            confidence = "HIGH"
            reasons.append("Цена достигла или превысила исходный риск")
        elif current_r >= Decimal(str(self.settings.position_intelligence_trail_start_r)):
            action = "TRAIL_REVIEW"
            confidence = "HIGH"
            reasons.append("Позиция прошла порог включения trailing")
        elif current_r >= Decimal(str(self.settings.position_intelligence_breakeven_r)):
            action = "BREAKEVEN_REVIEW"
            confidence = "MEDIUM"
            reasons.append("Позиция достигла порога безубытка")
        elif current_r >= Decimal(str(self.settings.position_intelligence_tp1_r)):
            action = "TP1_REVIEW"
            confidence = "MEDIUM"
            reasons.append("Позиция достигла уровня TP1")
        elif current_r > 0:
            action = "HOLD"
            confidence = "MEDIUM"
            reasons.append("Позиция движется в прибыль, но порог управления не достигнут")
        else:
            action = "HOLD"
            confidence = "LOW"
            reasons.append("Позиция находится между входом и Stop Loss")

        if take_profit is None:
            reasons.append("Take Profit не найден")

        return PositionPlan(
            position_id=position_id,
            symbol=symbol,
            side=side,
            entry_price=entry,
            current_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            current_r=current_r,
            action=action,
            confidence=confidence,
            reasons=reasons,
        )
