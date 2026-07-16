import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


@dataclass(slots=True)
class MacroEvent:
    event_id: str
    title: str
    starts_at: datetime
    impact_score: int
    category: str
    symbols: list[str]
    enabled: bool = True


@dataclass(slots=True)
class MacroGuardResult:
    state: str
    allowed: bool
    risk_multiplier: Decimal
    reasons: list[str]
    active_events: list[MacroEvent]


class LocalMacroCalendar:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> list[MacroEvent]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("macro_events.json должен содержать массив")
        events = []
        for item in raw:
            starts_at = datetime.fromisoformat(
                str(item["starts_at"]).replace("Z", "+00:00")
            )
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=timezone.utc)
            events.append(
                MacroEvent(
                    event_id=str(item.get("id") or item["title"]),
                    title=str(item["title"]),
                    starts_at=starts_at.astimezone(timezone.utc),
                    impact_score=int(item.get("impact_score", 0)),
                    category=str(item.get("category", "MACRO")).upper(),
                    symbols=[
                        str(symbol).upper()
                        for symbol in item.get("symbols", ["ALL"])
                    ],
                    enabled=bool(item.get("enabled", True)),
                )
            )
        return events


class NewsMacroGuard:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.calendar = LocalMacroCalendar(
            settings.macro_guard_calendar_path
        )

    @staticmethod
    def _relevant(event: MacroEvent, symbol: str) -> bool:
        return "ALL" in event.symbols or symbol.upper() in event.symbols

    def evaluate(
        self,
        *,
        symbol: str,
        now: datetime | None = None,
    ) -> MacroGuardResult:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)

        try:
            events = self.calendar.load()
        except Exception as exc:
            if self.settings.macro_guard_fail_closed:
                return MacroGuardResult(
                    "BLOCKED", False, Decimal("0"),
                    ["Календарь недоступен", type(exc).__name__], []
                )
            return MacroGuardResult(
                "SAFE", True, Decimal("1"),
                ["Календарь недоступен: fail-open"], []
            )

        blocked, waiting = [], []
        for event in events:
            if not event.enabled or not self._relevant(event, symbol):
                continue
            delta = (event.starts_at - current).total_seconds() / 60
            if event.impact_score >= self.settings.macro_guard_high_impact_score:
                if (
                    -self.settings.macro_guard_block_minutes_after_high
                    <= delta
                    <= self.settings.macro_guard_block_minutes_before_high
                ):
                    blocked.append(event)
            elif event.impact_score >= self.settings.macro_guard_medium_impact_score:
                if (
                    -self.settings.macro_guard_wait_minutes_after_medium
                    <= delta
                    <= self.settings.macro_guard_wait_minutes_before_medium
                ):
                    waiting.append(event)

        def event_reasons(items):
            return [
                f"{event.title}: impact={event.impact_score}, "
                f"время={event.starts_at.isoformat()}"
                for event in items
            ]

        if blocked:
            return MacroGuardResult(
                "BLOCKED", False, Decimal("0"),
                event_reasons(blocked), blocked
            )
        if waiting:
            return MacroGuardResult(
                "WAIT", True,
                Decimal(str(self.settings.macro_guard_wait_risk_multiplier)),
                event_reasons(waiting), waiting
            )
        return MacroGuardResult("SAFE", True, Decimal("1"), [], [])

    def upcoming(
        self,
        *,
        now: datetime | None = None,
        limit: int = 10,
    ) -> list[MacroEvent]:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        events = [
            event for event in self.calendar.load()
            if event.enabled and event.starts_at >= current
        ]
        events.sort(key=lambda event: event.starts_at)
        return events[:limit]

    def attach(self, signal):
        result = self.evaluate(symbol=signal.symbol)
        signal.macro_guard_state = result.state
        signal.macro_guard_allowed = result.allowed
        signal.macro_guard_risk_multiplier = float(result.risk_multiplier)
        signal.macro_guard_reasons = result.reasons
        return signal
