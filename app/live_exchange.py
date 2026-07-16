import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import aiohttp


class MexcApiError(RuntimeError):
    pass


class MexcPrivateClient:
    def __init__(self, base_url: str, api_key: str, api_secret: str, recv_window: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.recv_window = recv_window

    def _headers(self, method: str, params: dict | None) -> dict[str, str]:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        timestamp = str(int(time.time() * 1000))
        if method.upper() in {"GET", "DELETE"}:
            parameter_string = urlencode(sorted(clean.items()))
        else:
            parameter_string = json.dumps(clean, separators=(",", ":"), ensure_ascii=False)
        target = f"{self.api_key}{timestamp}{parameter_string}".encode()
        signature = hmac.new(self.api_secret, target, hashlib.sha256).hexdigest()
        return {
            "ApiKey": self.api_key,
            "Request-Time": timestamp,
            "Signature": signature,
            "Recv-Window": str(self.recv_window),
            "Content-Type": "application/json",
            "Language": "en-US",
        }

    async def _request(self, method: str, path: str, params: dict | None = None):
        method = method.upper()
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        headers = self._headers(method, clean)
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            kwargs = {"headers": headers}
            if method in {"GET", "DELETE"}:
                kwargs["params"] = clean
            else:
                kwargs["data"] = json.dumps(clean, separators=(",", ":"), ensure_ascii=False)
            async with session.request(method, f"{self.base_url}{path}", **kwargs) as response:
                payload = await response.json(content_type=None)
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise MexcApiError(
                f"MEXC error: code={payload.get('code') if isinstance(payload, dict) else '?'} "
                f"message={payload.get('message') if isinstance(payload, dict) else payload}"
            )
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
        stop_loss_price: Decimal | None = None,
        take_profit_price: Decimal | None = None,
        position_id: int | None = None,
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
            "stopLossPrice": str(stop_loss_price) if stop_loss_price is not None else None,
            "takeProfitPrice": str(take_profit_price) if take_profit_price is not None else None,
            "lossTrend": 1 if stop_loss_price is not None else None,
            "profitTrend": 1 if take_profit_price is not None else None,
            "positionMode": position_mode,
            "reduceOnly": False,
        }
        return await self._request("POST", "/api/v1/private/order/create", params)

    async def emergency_close(self, position: dict, position_mode: int) -> dict:
        position_type = int(position["positionType"])
        side = 4 if position_type == 1 else 2
        return await self.create_market_order(
            symbol=str(position["symbol"]),
            vol=Decimal(str(position["holdVol"])),
            side=side,
            leverage=int(position.get("leverage") or 1),
            open_type=int(position.get("openType") or 1),
            position_mode=position_mode,
            external_oid=f"smoke-close-{int(time.time())}",
            position_id=int(position["positionId"]),
        )
