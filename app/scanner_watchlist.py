from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.models import Signal


@dataclass(slots=True)
class WatchlistEntry:
    symbol: str
    side: str
    score: int
    previous_score: int
    delta: int
    streak: int
    status: str
    previous_status: str
    first_seen_at: datetime
    last_seen_at: datetime
    signal: Signal


class ScannerWatchlist:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._items: dict[str, WatchlistEntry] = {}

    @staticmethod
    def _key(signal: Signal) -> str:
        return f"{signal.symbol}:{signal.side}"

    def update(
        self,
        signals: list[Signal],
        *,
        now: datetime | None = None,
    ) -> list[WatchlistEntry]:
        current = now or datetime.now(timezone.utc)
        cutoff = current - timedelta(
            minutes=self.settings.scanner_watchlist_ttl_minutes
        )

        self._items = {
            key: value
            for key, value in self._items.items()
            if value.last_seen_at >= cutoff
        }

        seen_keys: set[str] = set()
        for signal in signals:
            key = self._key(signal)
            seen_keys.add(key)
            previous = self._items.get(key)
            old_score = previous.score if previous else signal.score
            delta = signal.score - old_score
            streak = (
                previous.streak + 1
                if previous is not None
                else 1
            )

            if signal.score >= self.settings.min_signal_score_paper:
                status = "READY"
            elif (
                delta >= self.settings.scanner_watchlist_promotion_delta
                and streak >= self.settings.scanner_watchlist_min_streak
            ):
                status = "RISING"
            elif delta > 0:
                status = "IMPROVING"
            elif delta < 0:
                status = "WEAKENING"
            else:
                status = "WATCHING"

            signal.watchlist_delta = delta
            signal.watchlist_streak = streak
            signal.watchlist_status = status
            signal.missing_points = max(
                0,
                self.settings.min_signal_score_paper - signal.score,
            )

            self._items[key] = WatchlistEntry(
                symbol=signal.symbol,
                side=signal.side,
                score=signal.score,
                previous_score=old_score,
                delta=delta,
                streak=streak,
                status=status,
                previous_status=(
                    previous.status
                    if previous is not None
                    else "NEW"
                ),
                first_seen_at=(
                    previous.first_seen_at
                    if previous
                    else current
                ),
                last_seen_at=current,
                signal=signal,
            )

        ranked = sorted(
            self._items.values(),
            key=lambda item: (
                item.status == "READY",
                item.status == "RISING",
                item.score,
                item.delta,
                item.streak,
            ),
            reverse=True,
        )
        return ranked[: self.settings.scanner_watchlist_max_items]

    def entries(self) -> list[WatchlistEntry]:
        return sorted(
            self._items.values(),
            key=lambda item: (
                item.status == "READY",
                item.status == "RISING",
                item.score,
                item.delta,
            ),
            reverse=True,
        )

    def clear(self) -> None:
        self._items.clear()
