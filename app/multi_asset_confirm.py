import asyncio
import time
from decimal import Decimal, ROUND_DOWN

import aiohttp

from app.live_exchange import MexcPrivateClient
from app.risk_manager import ContractSpec, TradePlan, build_trade_plan
from app.portfolio_manager import PortfolioRiskManager


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


class MultiAssetConfirmService:
    def __init__(self, settings, live_db) -> None:
        self.settings = settings
        self.db = live_db
        self.portfolio = PortfolioRiskManager(settings)
        self.private = MexcPrivateClient(
            settings.mexc_base_url,
            settings.mexc_api_key,
            settings.mexc_api_secret,
            settings.mexc_recv_window_seconds,
        )

    async def public_get(
        self,
        path: str,
        params: dict | None = None,
    ):
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                self.settings.mexc_base_url.rstrip("/") + path,
                params=params,
            ) as response:
                payload = await response.json(content_type=None)
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise RuntimeError("MEXC public market-data request failed")
        return payload.get("data")

    async def contract_spec(self, symbol: str) -> ContractSpec:
        data = await self.public_get(
            "/api/v1/contract/detail/country",
            {"symbol": symbol},
        )
        item = data
        if isinstance(data, list):
            item = next(
                (value for value in data if value.get("symbol") == symbol),
                None,
            )
        if not item:
            raise RuntimeError("Спецификация контракта не найдена")
        return ContractSpec(
            symbol=symbol,
            contract_size=Decimal(str(item["contractSize"])),
            min_vol=Decimal(str(item["minVol"])),
            max_vol=Decimal(
                str(
                    item.get("maxVol")
                    or item.get("maxVolMarket")
                    or "999999999"
                )
            ),
            vol_unit=Decimal(str(item["volUnit"])),
            price_unit=Decimal(str(item["priceUnit"])),
            api_allowed=bool(item.get("apiAllowed")),
            state=int(item.get("state", 99)),
            max_leverage=int(
                item.get("maxLeverage")
                or self.settings.live_max_leverage
            ),
        )

    async def ticker_price(self, symbol: str) -> Decimal:
        data = await self.public_get(
            "/api/v1/contract/ticker",
            {"symbol": symbol},
        )
        return Decimal(str(data["lastPrice"]))

    async def account_equity(self) -> Decimal:
        assets = await self.private._request(
            "GET",
            "/api/v1/private/account/assets",
        )
        if isinstance(assets, list):
            usdt = next(
                (item for item in assets if item.get("currency") == "USDT"),
                None,
            )
            if usdt:
                return Decimal(
                    str(
                        usdt.get("equity")
                        or usdt.get("availableBalance")
                        or 0
                    )
                )
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

        equity = await self.account_equity()
        requested = min(
            Decimal(str(self.settings.live_risk_per_trade_percent)),
            Decimal(str(self.settings.live_max_risk_per_trade_percent)),
        )
        portfolio_positions = self.portfolio.positions_from_mexc(
            positions,
            equity,
        )
        assessment = self.portfolio.assess(
            signal,
            portfolio_positions,
            requested,
        )
        signal.portfolio_score = assessment.adjusted_score
        signal.portfolio_allowed = assessment.allowed
        signal.portfolio_group = assessment.correlation_group
        signal.portfolio_reasons = assessment.reasons
        if self.settings.portfolio_manager_enabled and not assessment.allowed:
            details = "; ".join(assessment.reasons) or "Portfolio Manager отклонил сделку"
            raise ValueError(details)

        trades_count, daily_pnl = self.db.today()
        if trades_count >= self.settings.live_max_trades_per_day:
            raise ValueError("Достигнут дневной лимит сделок")
        if daily_pnl <= -abs(self.settings.live_daily_loss_limit_usdt):
            raise ValueError("Достигнут дневной лимит убытка")

        spec = await self.contract_spec(symbol)
        current = await self.ticker_price(symbol)
        deviation = (
            abs(current - Decimal(str(signal.entry)))
            / current
            * Decimal("100")
        )
        if deviation > Decimal(
            str(self.settings.live_max_entry_deviation_percent)
        ):
            raise ValueError(
                f"Цена ушла от сигнала на {deviation:.3f}%"
            )

        return build_trade_plan(
            symbol=symbol,
            side=signal.side,
            price=current,
            raw_stop=Decimal(str(signal.stop_loss)),
            equity_usdt=equity,
            risk_percent=requested,
            max_notional_usdt=Decimal(
                str(self.settings.live_max_notional_usdt)
            ),
            leverage=self.settings.live_max_leverage,
            take_profit_r=Decimal(
                str(self.settings.live_take_profit_r)
            ),
            spec=spec,
        )

    @staticmethod
    def protection_prices(
        *,
        plan: TradePlan,
        actual_entry: Decimal,
        price_unit: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """
        Preserve the original R distance, but anchor TP/SL to the actual fill.
        """
        risk_distance = abs(
            plan.reference_price - plan.stop_loss
        )
        if risk_distance <= 0:
            raise ValueError("Некорректная дистанция Stop Loss")

        if plan.side == "LONG":
            stop_loss = actual_entry - risk_distance
            take_profit = (
                actual_entry
                + risk_distance * Decimal("2")
            )
        else:
            stop_loss = actual_entry + risk_distance
            take_profit = (
                actual_entry
                - risk_distance * Decimal("2")
            )

        stop_loss = floor_step(stop_loss, price_unit)
        take_profit = floor_step(take_profit, price_unit)

        if plan.side == "LONG" and not (
            stop_loss < actual_entry < take_profit
        ):
            raise ValueError("Некорректные LONG TP/SL после исполнения")
        if plan.side == "SHORT" and not (
            take_profit < actual_entry < stop_loss
        ):
            raise ValueError("Некорректные SHORT TP/SL после исполнения")

        return stop_loss, take_profit

    async def execute(
        self,
        plan: TradePlan,
        signal_score: int,
    ) -> dict:
        external_oid = (
            f"confirm-{plan.symbol}-{int(time.time())}"
        )[:32]
        trade_id = self.db.create_trade(
            {
                "external_oid": external_oid,
                "symbol": plan.symbol,
                "side": plan.side,
                "state": "SUBMITTING_ENTRY",
                "signal_score": signal_score,
                "requested_risk_usdt": float(plan.risk_usdt),
                "contracts": float(plan.contracts),
                "contract_size": float(plan.contract_size),
                "reference_price": float(plan.reference_price),
                "stop_loss": float(plan.stop_loss),
                "take_profit": float(plan.take_profit),
                "leverage": plan.leverage,
            }
        )

        position = None
        try:
            side_code = 1 if plan.side == "LONG" else 3

            # Entry is deliberately sent WITHOUT preset TP/SL.
            result = await self.private.create_market_order(
                symbol=plan.symbol,
                vol=plan.contracts,
                side=side_code,
                leverage=plan.leverage,
                open_type=self.settings.live_open_type,
                position_mode=self.settings.live_position_mode,
                external_oid=external_oid,
            )
            order_id = str(
                result.get("orderId")
                if isinstance(result, dict)
                else result
            )
            self.db.update_trade(
                trade_id,
                state="ENTRY_ACCEPTED",
                mexc_order_id=order_id,
            )

            for _ in range(15):
                await asyncio.sleep(1)
                positions = await self.private.open_positions(
                    plan.symbol
                )
                expected_type = 1 if plan.side == "LONG" else 2
                position = next(
                    (
                        item
                        for item in positions
                        if item.get("symbol") == plan.symbol
                        and int(item.get("positionType") or 0)
                        == expected_type
                    ),
                    None,
                )
                if position:
                    break

            if not position:
                raise RuntimeError(
                    "Ордер принят, но открытая позиция не обнаружена"
                )

            position_id = int(position["positionId"])
            actual_entry = Decimal(
                str(
                    position.get("holdAvgPrice")
                    or position.get("openAvgPrice")
                    or plan.reference_price
                )
            )
            actual_vol = Decimal(
                str(position.get("holdVol") or plan.contracts)
            )
            spec = await self.contract_spec(plan.symbol)
            stop_loss, take_profit = self.protection_prices(
                plan=plan,
                actual_entry=actual_entry,
                price_unit=spec.price_unit,
            )

            self.db.update_trade(
                trade_id,
                state="PLACING_PROTECTION",
                mexc_position_id=str(position_id),
                reference_price=float(actual_entry),
                stop_loss=float(stop_loss),
                take_profit=float(take_profit),
            )

            protection_result = (
                await self.private.place_position_tpsl(
                    position_id=position_id,
                    vol=actual_vol,
                    stop_loss_price=stop_loss,
                    take_profit_price=take_profit,
                    trigger_price_type=1,
                )
            )

            protection = []
            for _ in range(12):
                await asyncio.sleep(1)
                all_protection = await self.private.current_tpsl(
                    plan.symbol
                )
                protection = [
                    item
                    for item in all_protection
                    if str(item.get("positionId"))
                    == str(position_id)
                    and int(item.get("state") or 0) == 1
                ]
                has_stop = any(
                    Decimal(
                        str(item.get("stopLossPrice") or 0)
                    )
                    > 0
                    for item in protection
                )
                if has_stop:
                    break

            has_stop = any(
                Decimal(str(item.get("stopLossPrice") or 0)) > 0
                for item in protection
            )
            if not has_stop:
                raise RuntimeError(
                    "Stop Loss не подтверждён после открытия"
                )

            self.db.update_trade(
                trade_id,
                state="PROTECTED",
            )
            self.db.increment_trade_count()
            return {
                "trade_id": trade_id,
                "order": result,
                "position": position,
                "protection": protection,
                "protection_result": protection_result,
                "actual_stop_loss": stop_loss,
                "actual_take_profit": take_profit,
            }

        except Exception as exc:
            error_message = (
                f"{type(exc).__name__}: {exc}"
            )
            self.db.update_trade(
                trade_id,
                state="ERROR",
                error=error_message[:500],
            )

            # If an entry position exists but protection failed,
            # immediately attempt to remove the exposure.
            if position is not None:
                try:
                    await self.private.emergency_close(
                        position,
                        self.settings.live_position_mode,
                    )
                    self.db.update_trade(
                        trade_id,
                        state="EMERGENCY_CLOSE_SUBMITTED",
                        error=error_message[:500],
                    )
                except Exception as close_exc:
                    self.db.update_trade(
                        trade_id,
                        state="CRITICAL_UNPROTECTED",
                        error=(
                            f"{error_message}; emergency close failed: "
                            f"{type(close_exc).__name__}"
                        )[:500],
                    )
                    raise RuntimeError(
                        "Позиция могла остаться без защиты, а аварийное "
                        "закрытие не подтвердилось. Немедленно проверь MEXC."
                    ) from close_exc

            raise

    async def reconcile(self) -> dict:
        return {
            "positions": await self.private.open_positions(),
            "tpsl": await self.private.current_tpsl(),
        }

    async def close_position(self, position_id: int) -> dict:
        positions = await self.private.open_positions()
        position = next(
            (
                item
                for item in positions
                if int(item.get("positionId")) == position_id
            ),
            None,
        )
        if not position:
            raise ValueError("Позиция не найдена")
        return await self.private.emergency_close(
            position,
            self.settings.live_position_mode,
        )
