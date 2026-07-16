import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import aiohttp


class MexcApiError(RuntimeError):
    def __init__(self, code: int | str, message: str) -> None:
        self.code = code
        self.exchange_message = message
        super().__init__(f"MEXC error: code={code} message={message}")


class MexcPrivateClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        recv_window: int = 10,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.recv_window = recv_window

    def _headers(self, method: str, params: dict | None) -> dict[str, str]:
        clean = {key: value for key, value in (params or {}).items() if value is not None}
        timestamp = str(int(time.time() * 1000))
        if method.upper() in {"GET", "DELETE"}:
            parameter_string = urlencode(sorted(clean.items()))
        else:
            parameter_string = json.dumps(
                clean,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        target = f"{self.api_key}{timestamp}{parameter_string}".encode()
        signature = hmac.new(
            self.api_secret,
            target,
            hashlib.sha256,
        ).hexdigest()
        return {
            "ApiKey": self.api_key,
            "Request-Time": timestamp,
            "Signature": signature,
            "Recv-Window": str(self.recv_window),
            "Content-Type": "application/json",
            "Language": "en-US",
        }

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
    ):
        method = method.upper()
        clean = {key: value for key, value in (params or {}).items() if value is not None}
        headers = self._headers(method, clean)
        timeout = aiohttp.ClientTimeout(total=20)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            kwargs = {"headers": headers}
            if method in {"GET", "DELETE"}:
                kwargs["params"] = clean
            else:
                kwargs["data"] = json.dumps(
                    clean,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            async with session.request(
                method,
                f"{self.base_url}{path}",
                **kwargs,
            ) as response:
                payload = await response.json(content_type=None)

        if not isinstance(payload, dict) or payload.get("success") is not True:
            code = payload.get("code", "?") if isinstance(payload, dict) else "?"
            message = (
                str(payload.get("message", "Unknown MEXC error"))
                if isinstance(payload, dict)
                else "Unexpected MEXC response"
            )
            raise MexcApiError(code, message)

        return payload.get("data")

    async def open_positions(self, symbol: str | None = None) -> list[dict]:
        data = await self._request(
            "GET",
            "/api/v1/private/position/open_positions",
            {"symbol": symbol},
        )
        return data or []

    async def current_tpsl(self, symbol: str | None = None) -> list[dict]:
        data = await self._request(
            "GET",
            "/api/v1/private/stoporder/open_orders",
            {"symbol": symbol},
        )
        return data or []

    async def create_market_order(
        self,
        *,
        symbol: str,
        vol: Decimal,
        side: int,
        leverage: int,
        open_type: int,
        position_mode: int,
        external_oid: str,
        position_id: int | None = None,
        reduce_only: bool = False,
    ) -> dict:
        params = {
            "symbol": symbol,
            "price": 0,
            "vol": str(vol),
            "leverage": leverage,
            "side": side,
            "type": 5,
            "openType": open_type,
            "externalOid": external_oid,
            "positionId": position_id,
            "positionMode": position_mode,
            "reduceOnly": reduce_only,
        }
        return await self._request(
            "POST",
            "/api/v1/private/order/create",
            params,
        )

    async def place_position_tpsl(
        self,
        *,
        position_id: int,
        vol: Decimal,
        stop_loss_price: Decimal,
        take_profit_price: Decimal,
        trigger_price_type: int = 1,
    ):
        """
        Place full-position market TP/SL after the entry position exists.

        MEXC endpoint:
        POST /api/v1/private/stoporder/place
        """
        params = {
            "positionId": position_id,
            "vol": str(vol),
            "lossTrend": trigger_price_type,
            "profitTrend": trigger_price_type,
            "stopLossPrice": str(stop_loss_price),
            "takeProfitPrice": str(take_profit_price),
            "priceProtect": 0,
            "profitLossVolType": "SAME",
            "volType": 2,
            "takeProfitReverse": 2,
            "stopLossReverse": 2,
            "takeProfitType": 0,
            "takeProfitOrderPrice": 0,
            "stopLossType": 0,
            "stopLossOrderPrice": 0,
        }
        return await self._request(
            "POST",
            "/api/v1/private/stoporder/place",
            params,
        )


    async def modify_tpsl_plan(
        self,
        *,
        stop_plan_order_id: int,
        stop_loss_price: Decimal | None = None,
        take_profit_price: Decimal | None = None,
        loss_trend: int = 1,
        profit_trend: int = 1,
    ):
        params = {
            "stopPlanOrderId": stop_plan_order_id,
            "lossTrend": loss_trend,
            "profitTrend": profit_trend,
            "stopLossPrice": (
                str(stop_loss_price)
                if stop_loss_price is not None
                else None
            ),
            "takeProfitPrice": (
                str(take_profit_price)
                if take_profit_price is not None
                else None
            ),
            "takeProfitReverse": 2,
            "stopLossReverse": 2,
        }
        return await self._request(
            "POST",
            "/api/v1/private/stoporder/change_plan_price",
            params,
        )


    async def emergency_close(
        self,
        position: dict,
        position_mode: int,
    ) -> dict:
        position_type = int(position["positionType"])
        side = 4 if position_type == 1 else 2
        return await self.create_market_order(
            symbol=str(position["symbol"]),
            vol=Decimal(str(position["holdVol"])),
            side=side,
            leverage=int(position.get("leverage") or 1),
            open_type=int(position.get("openType") or 1),
            position_mode=position_mode,
            external_oid=f"emergency-close-{int(time.time())}",
            position_id=int(position["positionId"]),
            reduce_only=position_mode == 2,
        )
