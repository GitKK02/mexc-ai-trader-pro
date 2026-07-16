from datetime import datetime, timedelta, timezone

from app.models import Signal
from app.scanner_watchlist import ScannerWatchlist


class Settings:
    scanner_watchlist_ttl_minutes = 180
    scanner_watchlist_promotion_delta = 5
    scanner_watchlist_min_streak = 2
    scanner_watchlist_max_items = 30
    min_signal_score_paper = 70


def signal(score: int):
    return Signal(
        symbol="BTC_USDT",
        side="LONG",
        score=score,
        entry=100,
        stop_loss=99,
        tp1=101,
        tp2=102,
        atr=1,
        reasons=["test"],
    )


def test_new_candidate_is_watching():
    watchlist = ScannerWatchlist(Settings())
    entries = watchlist.update([signal(60)])
    assert entries[0].status == "WATCHING"
    assert entries[0].signal.missing_points == 10


def test_rising_candidate():
    watchlist = ScannerWatchlist(Settings())
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    watchlist.update([signal(60)], now=now)
    entries = watchlist.update(
        [signal(66)],
        now=now + timedelta(minutes=1),
    )
    assert entries[0].status == "RISING"
    assert entries[0].delta == 6
    assert entries[0].streak == 2


def test_ready_candidate():
    watchlist = ScannerWatchlist(Settings())
    entries = watchlist.update([signal(72)])
    assert entries[0].status == "READY"


def test_weakening_candidate():
    watchlist = ScannerWatchlist(Settings())
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    watchlist.update([signal(65)], now=now)
    entries = watchlist.update(
        [signal(62)],
        now=now + timedelta(minutes=1),
    )
    assert entries[0].status == "WEAKENING"


def test_expired_candidate_removed():
    watchlist = ScannerWatchlist(Settings())
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    watchlist.update([signal(65)], now=now)
    entries = watchlist.update(
        [],
        now=now + timedelta(minutes=181),
    )
    assert entries == []
