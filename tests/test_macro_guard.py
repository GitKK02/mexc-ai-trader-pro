import json
from datetime import datetime, timezone
from decimal import Decimal
from app.macro_guard import NewsMacroGuard

class Settings:
    macro_guard_calendar_path = ""
    macro_guard_block_minutes_before_high = 45
    macro_guard_block_minutes_after_high = 30
    macro_guard_wait_minutes_before_medium = 30
    macro_guard_wait_minutes_after_medium = 15
    macro_guard_high_impact_score = 80
    macro_guard_medium_impact_score = 50
    macro_guard_wait_risk_multiplier = 0.50
    macro_guard_fail_closed = False

NOW = datetime(2026,1,1,12,0,tzinfo=timezone.utc)

def guard(tmp_path, events):
    path = tmp_path/"events.json"
    path.write_text(json.dumps(events))
    settings = Settings()
    settings.macro_guard_calendar_path = str(path)
    return NewsMacroGuard(settings)

def test_high_blocks(tmp_path):
    result = guard(tmp_path,[{
        "title":"CPI","starts_at":"2026-01-01T12:20:00Z",
        "impact_score":90,"symbols":["ALL"]
    }]).evaluate(symbol="BTC_USDT", now=NOW)
    assert result.state == "BLOCKED"
    assert result.allowed is False

def test_medium_wait(tmp_path):
    result = guard(tmp_path,[{
        "title":"PPI","starts_at":"2026-01-01T12:20:00Z",
        "impact_score":60,"symbols":["ALL"]
    }]).evaluate(symbol="BTC_USDT", now=NOW)
    assert result.state == "WAIT"
    assert result.risk_multiplier == Decimal("0.5")

def test_symbol_scope(tmp_path):
    result = guard(tmp_path,[{
        "title":"SOL","starts_at":"2026-01-01T12:10:00Z",
        "impact_score":100,"symbols":["SOL_USDT"]
    }]).evaluate(symbol="BTC_USDT", now=NOW)
    assert result.state == "SAFE"

def test_old_safe(tmp_path):
    result = guard(tmp_path,[{
        "title":"Old","starts_at":"2026-01-01T10:00:00Z",
        "impact_score":100,"symbols":["ALL"]
    }]).evaluate(symbol="BTC_USDT", now=NOW)
    assert result.state == "SAFE"

def test_missing_fail_open(tmp_path):
    settings = Settings()
    settings.macro_guard_calendar_path = str(tmp_path/"missing.json")
    result = NewsMacroGuard(settings).evaluate(
        symbol="BTC_USDT", now=NOW
    )
    assert result.allowed is True
