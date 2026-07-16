from decimal import Decimal

from app.live_exchange import MexcPrivateClient


def test_get_signature_is_deterministic_when_time_patched(monkeypatch):
    monkeypatch.setattr("app.live_exchange.time.time", lambda: 1000.0)
    client = MexcPrivateClient("https://api.mexc.com", "access", "secret")
    first = client._headers("GET", {"symbol": "BTC_USDT"})
    second = client._headers("GET", {"symbol": "BTC_USDT"})
    assert first["Signature"] == second["Signature"]
    assert first["Request-Time"] == "1000000"


def test_post_signature_uses_json(monkeypatch):
    monkeypatch.setattr("app.live_exchange.time.time", lambda: 1000.0)
    client = MexcPrivateClient("https://api.mexc.com", "access", "secret")
    headers = client._headers("POST", {"symbol": "BTC_USDT", "vol": "1"})
    assert len(headers["Signature"]) == 64
