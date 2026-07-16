import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

import aiohttp

from app.live_exchange import MexcPrivateClient


@dataclass(slots=True)
class LiveQuote:
    symbol: str
    side: str
    price: Decimal
    contracts: Decimal
    contract_size: Decimal
    notional_usdt: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    leverage: int
    open_type: int
    position_mode: int


class LiveSmokeService:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.private = MexcPrivateClient(
            settings.mexc_base_url,
            settings.mexc_api_key,
            settings.mexc_api_secret,
            settings.mexc_recv_window_seconds,
        )

    async def _public_get(self, path: str, params: dict | None = None):
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"{self.settings.mexc_base_url.rstrip('/')}{path}",
                params=params,
            ) as response:
                payload = await response.json(content_type=None)
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise RuntimeError(f"Public MEXC error: {payload}")
        return payload.get("data")

    async def contract(self) -> dict:
        data = await self._public_get(
            "/api/v1/contract/detail/country",
            {"symbol": self.settings.live_symbol},
        )
        if isinstance(data, list):
            for item in data:
                if item.get("symbol") == self.settings.live_symbol:
                    return item
            raise RuntimeError("Contract not found")
        return data

    async def ticker(self) -> dict:
        return await self._public_get(
            "/api/v1/contract/ticker",
            {"symbol": self.settings.live_symbol},
        )

    async def preflight(self) -> dict:
        contract = await self.contract()
        ticker = await self.ticker()
        positions = await self.private.open_positions()
        tpsl = await self.private.current_tpsl(self.settings.live_symbol)
        return {
            "contract": contract,
            "ticker": ticker,
            "positions": positions,
            "tpsl": tpsl,
        }

    async def quote(self, side: str) -> LiveQuote:
        side = side.upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError("side must be LONG or SHORT")
        data = await self.preflight()
        contract = data["contract"]
        ticker = data["ticker"]

        if data["positions"]:
            raise RuntimeError("На аккаунте уже есть открытая фьючерсная позиция")
        if not bool(contract.get("apiAllowed")):
            raise RuntimeError("API-торговля для контракта запрещена")
        if int(contract.get("state", 99)) != 0:
            raise RuntimeError("Контракт сейчас недоступен для торговли")

        price = Decimal(str(ticker["lastPrice"]))
        min_vol = Decimal(str(contract["minVol"]))
        vol_unit = Decimal(str(contract["volUnit"]))
        configured = Decimal(str(self.settings.live_contracts))
        contracts = max(configured, min_vol)
        contracts = (contracts / vol_unit).to_integral_value(rounding=ROUND_DOWN) * vol_unit
        if contracts <= 0:
            raise RuntimeError("Некорректное количество контрактов")

        contract_size = Decimal(str(contract["contractSize"]))
        notional = price * contract_size * contracts
        if notional > Decimal(str(self.settings.live_max_notional_usdt)):
            raise RuntimeError(
                f"Номинал {notional:.2f} USDT превышает LIVE_MAX_NOTIONAL_USDT"
            )

        stop_pct = Decimal(str(self.settings.live_stop_percent)) / Decimal("100")
        tp_pct = Decimal(str(self.settings.live_take_profit_percent)) / Decimal("100")
        price_unit = Decimal(str(contract["priceUnit"]))

        if side == "LONG":
            sl = price * (Decimal("1") - stop_pct)
            tp = price * (Decimal("1") + tp_pct)
        else:
            sl = price * (Decimal("1") + stop_pct)
            tp = price * (Decimal("1") - tp_pct)

        sl = (sl / price_unit).to_integral_value(rounding=ROUND_DOWN) * price_unit
        tp = (tp / price_unit).to_integral_value(rounding=ROUND_DOWN) * price_unit

        return LiveQuote(
            symbol=self.settings.live_symbol,
            side=side,
            price=price,
            contracts=contracts,
            contract_size=contract_size,
            notional_usdt=notional,
            stop_loss=sl,
            take_profit=tp,
            leverage=self.settings.live_leverage,
            open_type=self.settings.live_open_type,
            position_mode=self.settings.live_position_mode,
        )

    async def execute(self, quote: LiveQuote) -> dict:
        side_code = 1 if quote.side == "LONG" else 3
        result = await self.private.create_market_order(
            symbol=quote.symbol,
            vol=quote.contracts,
            side=side_code,
            leverage=quote.leverage,
            open_type=quote.open_type,
            position_mode=quote.position_mode,
            external_oid=f"smoke-{int(time.time())}",
            stop_loss_price=quote.stop_loss,
            take_profit_price=quote.take_profit,
        )

        position = None
        tpsl = []
        for _ in range(10):
            await asyncio.sleep(1)
            positions = await self.private.open_positions(quote.symbol)
            if positions:
                position = positions[0]
                tpsl = await self.private.current_tpsl(quote.symbol)
                if tpsl:
                    break

        if position is None:
            raise RuntimeError(
                f"Ордер принят ({result}), но открытая позиция не найдена. "
                "Немедленно проверь MEXC вручную."
            )
        if not tpsl:
            try:
                await self.private.emergency_close(position, quote.position_mode)
            finally:
                raise RuntimeError(
                    "Позиция открылась, но TP/SL не подтверждены. "
                    "Отправлена аварийная команда закрытия; проверь MEXC вручную."
                )

        return {"order": result, "position": position, "tpsl": tpsl}

    async def emergency_close(self) -> list[dict]:
        positions = await self.private.open_positions()
        results = []
        for position in positions:
            results.append(
                await self.private.emergency_close(
                    position,
                    self.settings.live_position_mode,
                )
            )
        return results
