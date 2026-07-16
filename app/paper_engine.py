from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import Settings
from app.database import Database
from app.models import PaperPosition, Signal


@dataclass(slots=True)
class EngineEvent:
    kind: str
    position_id: int
    text: str


class PaperEngine:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.db = database
        self.db.ensure_account(settings.paper_initial_balance_usdt)

    @staticmethod
    def unrealized(position: PaperPosition, price: float) -> float:
        direction = 1 if position.side == "LONG" else -1
        return (price - position.entry_price) * position.remaining_quantity * direction

    def equity(self) -> float:
        balance, _ = self.db.account()
        return balance + sum(self.unrealized(p, p.current_price) for p in self.db.open_positions())

    def open_from_signal(self, signal: Signal) -> PaperPosition:
        if len(self.db.open_positions()) >= self.settings.max_positions:
            raise ValueError("достигнут лимит открытых позиций")
        if any(p.symbol == signal.symbol for p in self.db.open_positions()):
            raise ValueError("по этой паре уже есть открытая позиция")

        equity = self.equity()
        risk_amount = equity * self.settings.risk_per_trade_percent / 100
        stop_distance = abs(signal.entry - signal.stop_loss)
        if stop_distance <= 0:
            raise ValueError("некорректное расстояние до стопа")
        quantity = risk_amount / stop_distance

        slip = self.settings.paper_slippage_percent / 100
        entry = signal.entry * (1 + slip if signal.side == "LONG" else 1 - slip)
        notional = entry * quantity
        entry_fee = notional * self.settings.paper_taker_fee_percent / 100
        self.db.change_balance(-entry_fee)

        now = datetime.now(timezone.utc).isoformat()
        position_id = self.db.insert_position({
            "symbol": signal.symbol, "side": signal.side, "status": "OPEN",
            "entry_price": entry, "current_price": entry,
            "initial_quantity": quantity, "remaining_quantity": quantity,
            "stop_loss": signal.stop_loss, "initial_stop_loss": signal.stop_loss,
            "tp1": signal.tp1, "tp2": signal.tp2, "atr": signal.atr,
            "leverage": self.settings.max_leverage, "risk_amount": risk_amount,
            "realized_pnl": 0.0, "fees": entry_fee, "tp1_done": 0, "tp2_done": 0,
            "highest_price": entry, "lowest_price": entry, "opened_at": now,
        })
        result = self.db.position(position_id)
        assert result is not None
        return result

    def _close_quantity(self, position: PaperPosition, price: float, quantity: float) -> tuple[float, float]:
        quantity = min(quantity, position.remaining_quantity)
        direction = 1 if position.side == "LONG" else -1
        pnl = (price - position.entry_price) * quantity * direction
        fee = price * quantity * self.settings.paper_taker_fee_percent / 100
        self.db.change_balance(pnl - fee)
        return pnl, fee

    def close_full(self, position_id: int, price: float, reason: str) -> EngineEvent:
        position = self.db.position(position_id)
        if position is None or position.status != "OPEN":
            raise ValueError("позиция не найдена")
        pnl, fee = self._close_quantity(position, price, position.remaining_quantity)
        now = datetime.now(timezone.utc).isoformat()
        self.db.update_position(
            position.id, status="CLOSED", current_price=price, remaining_quantity=0,
            realized_pnl=position.realized_pnl + pnl, fees=position.fees + fee,
            closed_at=now, close_reason=reason,
        )
        return EngineEvent("CLOSED", position.id, f"{position.symbol} закрыта: {pnl:+.2f} USDT, причина: {reason}")

    def update_price(self, position: PaperPosition, price: float) -> list[EngineEvent]:
        events: list[EngineEvent] = []
        highest = max(position.highest_price, price)
        lowest = min(position.lowest_price, price)
        self.db.update_position(position.id, current_price=price, highest_price=highest, lowest_price=lowest)
        position = self.db.position(position.id)
        assert position is not None

        stop_hit = price <= position.stop_loss if position.side == "LONG" else price >= position.stop_loss
        if stop_hit:
            return [self.close_full(position.id, position.stop_loss, "STOP_LOSS")]

        tp1_hit = price >= position.tp1 if position.side == "LONG" else price <= position.tp1
        if not position.tp1_done and tp1_hit:
            qty = position.initial_quantity * self.settings.tp1_close_percent / 100
            pnl, fee = self._close_quantity(position, position.tp1, qty)
            remaining = position.remaining_quantity - qty
            buffer = position.entry_price * self.settings.breakeven_buffer_percent / 100
            new_stop = position.entry_price + buffer if position.side == "LONG" else position.entry_price - buffer
            self.db.update_position(
                position.id, remaining_quantity=remaining, realized_pnl=position.realized_pnl + pnl,
                fees=position.fees + fee, tp1_done=1, stop_loss=new_stop,
            )
            events.append(EngineEvent("TP1", position.id, f"{position.symbol}: TP1, закрыто {self.settings.tp1_close_percent:.0f}%, SL → безубыток"))
            position = self.db.position(position.id)
            assert position is not None

        tp2_hit = price >= position.tp2 if position.side == "LONG" else price <= position.tp2
        if not position.tp2_done and tp2_hit:
            qty = position.initial_quantity * self.settings.tp2_close_percent / 100
            pnl, fee = self._close_quantity(position, position.tp2, qty)
            remaining = max(0.0, position.remaining_quantity - qty)
            self.db.update_position(
                position.id, remaining_quantity=remaining, realized_pnl=position.realized_pnl + pnl,
                fees=position.fees + fee, tp2_done=1,
            )
            events.append(EngineEvent("TP2", position.id, f"{position.symbol}: TP2, закрыто ещё {self.settings.tp2_close_percent:.0f}%"))
            position = self.db.position(position.id)
            assert position is not None

        if position.tp2_done and position.remaining_quantity > 0:
            distance = position.atr * self.settings.trailing_atr_multiplier
            candidate = highest - distance if position.side == "LONG" else lowest + distance
            better = candidate > position.stop_loss if position.side == "LONG" else candidate < position.stop_loss
            if better:
                self.db.update_position(position.id, stop_loss=candidate)

        return events
