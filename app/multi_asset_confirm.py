import asyncio
import time
from decimal import Decimal

import aiohttp

from app.live_exchange import MexcPrivateClient
from app.risk_manager import ContractSpec, TradePlan, build_trade_plan


class MultiAssetConfirmService:
    def __init__(self, settings, live_db) -> None:
        self.settings = settings
        self.db = live_db
        self.private = MexcPrivateClient(
            settings.mexc_base_url,
            settings.mexc_api_key,
            settings.mexc_api_secret,
            settings.mexc_recv_window_seconds,
        )

    async def public_get(self, path: str, params: dict | None = None):
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(self.settings.mexc_base_url.rstrip("/") + path, params=params) as response:
                payload = await response.json(content_type=None)
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise RuntimeError(f"MEXC public error: {payload}")
        return payload.get("data")

    async def contract_spec(self, symbol: str) -> ContractSpec:
        data = await self.public_get("/api/v1/contract/detail/country", {"symbol": symbol})
        item = data
        if isinstance(data, list):
            item = next((x for x in data if x.get("symbol") == symbol), None)
        if not item:
            raise RuntimeError("Спецификация контракта не найдена")
        return ContractSpec(
            symbol=symbol,
            contract_size=Decimal(str(item["contractSize"])),
            min_vol=Decimal(str(item["minVol"])),
            max_vol=Decimal(str(item.get("maxVol") or item.get("maxVolMarket") or "999999999")),
            vol_unit=Decimal(str(item["volUnit"])),
            price_unit=Decimal(str(item["priceUnit"])),
            api_allowed=bool(item.get("apiAllowed")),
            state=int(item.get("state", 99)),
            max_leverage=int(item.get("maxLeverage") or self.settings.live_max_leverage),
        )

    async def ticker_price(self, symbol: str) -> Decimal:
        data = await self.public_get("/api/v1/contract/ticker", {"symbol": symbol})
        return Decimal(str(data["lastPrice"]))

    async def account_equity(self) -> Decimal:
        assets = await self.private._request("GET", "/api/v1/private/account/assets")
        if isinstance(assets, list):
            usdt = next((x for x in assets if x.get("currency") == "USDT"), None)
            if usdt:
                return Decimal(str(usdt.get("equity") or usdt.get("availableBalance") or 0))
        raise RuntimeError("Не удалось получить USDT equity")

    async def prepare(self, signal) -> TradePlan:
        symbol = signal.symbol.upper()
        if symbol not in self.settings.live_whitelist:
            raise ValueError("Пара не входит в LIVE whitelist")
        if signal.score < self.settings.min_signal_score_confirm:
            raise ValueError("Оценка сигнала ниже CONFIRM-порога")

        positions = await self.private.open_positions()
        if len(positions) >= self.settings.live_max_open_positions:
            raise ValueError("Достигнут лимит открытых позиций")
        if any(str(p.get("symbol")) == symbol for p in positions):
            raise ValueError("По этой паре уже есть открытая позиция")

        trades_count, daily_pnl = self.db.today()
        if trades_count >= self.settings.live_max_trades_per_day:
            raise ValueError("Достигнут дневной лимит сделок")
        if daily_pnl <= -abs(self.settings.live_daily_loss_limit_usdt):
            raise ValueError("Достигнут дневной лимит убытка")

        spec = await self.contract_spec(symbol)
        current = await self.ticker_price(symbol)
        deviation = abs(current - Decimal(str(signal.entry))) / current * Decimal("100")
        if deviation > Decimal(str(self.settings.live_max_entry_deviation_percent)):
            raise ValueError(f"Цена ушла от сигнала на {deviation:.3f}%")

        equity = await self.account_equity()
        requested = min(
            Decimal(str(self.settings.live_risk_per_trade_percent)),
            Decimal(str(self.settings.live_max_risk_per_trade_percent)),
        )
        return build_trade_plan(
            symbol=symbol,
            side=signal.side,
            price=current,
            raw_stop=Decimal(str(signal.stop_loss)),
            equity_usdt=equity,
            risk_percent=requested,
            max_notional_usdt=Decimal(str(self.settings.live_max_notional_usdt)),
            leverage=self.settings.live_max_leverage,
            take_profit_r=Decimal(str(self.settings.live_take_profit_r)),
            spec=spec,
        )

    async def execute(self, plan: TradePlan, signal_score: int) -> dict:
        external_oid = f"confirm-{plan.symbol}-{int(time.time())}"
        trade_id = self.db.create_trade({
            "external_oid": external_oid,
            "symbol": plan.symbol,
            "side": plan.side,
            "state": "SUBMITTING",
            "signal_score": signal_score,
            "requested_risk_usdt": float(plan.risk_usdt),
            "contracts": float(plan.contracts),
            "contract_size": float(plan.contract_size),
            "reference_price": float(plan.reference_price),
            "stop_loss": float(plan.stop_loss),
            "take_profit": float(plan.take_profit),
            "leverage": plan.leverage,
        })
        try:
            side_code = 1 if plan.side == "LONG" else 3
            result = await self.private.create_market_order(
                symbol=plan.symbol,
                vol=plan.contracts,
                side=side_code,
                leverage=plan.leverage,
                open_type=self.settings.live_open_type,
                position_mode=self.settings.live_position_mode,
                external_oid=external_oid,
                stop_loss_price=plan.stop_loss,
                take_profit_price=plan.take_profit,
            )
            order_id = str(result.get("orderId") if isinstance(result, dict) else result)
            self.db.update_trade(trade_id, state="ORDER_ACCEPTED", mexc_order_id=order_id)

            position = None
            protection = []
            for _ in range(12):
                await asyncio.sleep(1)
                positions = await self.private.open_positions(plan.symbol)
                position = next((p for p in positions if p.get("symbol") == plan.symbol), None)
                if position:
                    protection = await self.private.current_tpsl(plan.symbol)
                    if protection:
                        break
            if not position:
                raise RuntimeError("Ордер принят, но позиция не обнаружена")
            if not protection:
                await self.private.emergency_close(position, self.settings.live_position_mode)
                raise RuntimeError("TP/SL не подтверждены; отправлено аварийное закрытие")

            self.db.update_trade(
                trade_id,
                state="PROTECTED",
                mexc_position_id=str(position.get("positionId")),
            )
            self.db.increment_trade_count()
            return {"trade_id": trade_id, "order": result, "position": position, "protection": protection}
        except Exception as exc:
            self.db.update_trade(trade_id, state="ERROR", error=f"{type(exc).__name__}: {exc}")
            raise

    async def reconcile(self) -> dict:
        return {
            "positions": await self.private.open_positions(),
            "tpsl": await self.private.current_tpsl(),
        }

    async def close_position(self, position_id: int) -> dict:
        positions = await self.private.open_positions()
        position = next((p for p in positions if int(p.get("positionId")) == position_id), None)
        if not position:
            raise ValueError("Позиция не найдена")
        return await self.private.emergency_close(position, self.settings.live_position_mode)
