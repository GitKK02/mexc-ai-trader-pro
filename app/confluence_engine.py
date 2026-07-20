from dataclasses import dataclass

from app.models import Signal


@dataclass(slots=True)
class ConfluenceResult:
    score: int
    confirmations: int
    total: int
    allowed: bool
    checks: dict[str, bool]
    reasons: list[str]


class ConfluenceEngine:
    """Counts independent confirmations instead of trusting one aggregate score."""

    def __init__(self, settings) -> None:
        self.settings = settings

    @staticmethod
    def _number(mapping: dict | None, key: str, default: float = 0.0) -> float:
        try:
            return float((mapping or {}).get(key, default) or default)
        except (TypeError, ValueError):
            return default

    def evaluate(self, signal: Signal) -> ConfluenceResult:
        diagnostics = signal.diagnostics or {}
        timeframe_scores = signal.timeframe_scores or {}
        primary_adx = self._number(diagnostics, "primary_adx")
        relative_volume = self._number(diagnostics, "primary_relative_volume")
        agreement = int(self._number(diagnostics, "agreement"))

        trend_ok = (
            signal.market_regime == "TREND"
            or signal.detailed_regime in {
                "STRONG_BULL_TREND",
                "STRONG_BEAR_TREND",
                "WEAK_BULL_TREND",
                "WEAK_BEAR_TREND",
                "BREAKOUT",
            }
            or primary_adx >= self.settings.confluence_min_adx
        )
        momentum_ok = signal.score >= self.settings.confluence_min_scanner_score
        volume_ok = relative_volume >= self.settings.confluence_min_relative_volume
        timeframe_ok = agreement >= self.settings.confluence_min_timeframe_agreement
        entry_ok = (
            signal.entry_allowed is not False
            and (signal.entry_quality_score or 0) >= self.settings.confluence_min_entry_quality
            and signal.entry_timing not in {"LATE", "CHASE"}
        )
        regime_ok = (
            signal.regime_allowed is not False
            and signal.volatility_guard_allowed is not False
            and signal.macro_guard_allowed is not False
        )
        btc_ok = signal.btc_context not in {"UNSTABLE"}
        portfolio_ok = signal.portfolio_allowed is not False

        checks = {
            "trend": trend_ok,
            "momentum": momentum_ok,
            "volume": volume_ok,
            "timeframes": timeframe_ok,
            "entry": entry_ok,
            "regime": regime_ok,
            "btc": btc_ok,
            "portfolio": portfolio_ok,
        }
        confirmations = sum(checks.values())
        total = len(checks)
        score = round(confirmations / total * 100) if total else 0
        allowed = confirmations >= self.settings.confluence_min_confirmations

        names = {
            "trend": "Тренд",
            "momentum": "Импульс",
            "volume": "Объём",
            "timeframes": "Таймфреймы",
            "entry": "Точка входа",
            "regime": "Режим и guards",
            "btc": "BTC-контекст",
            "portfolio": "Портфель",
        }
        reasons = [
            f"{names[key]}: {'подтверждено' if value else 'не подтверждено'}"
            for key, value in checks.items()
        ]
        if not allowed:
            reasons.append(
                f"Недостаточно независимых подтверждений: {confirmations}/{total}, "
                f"нужно ≥{self.settings.confluence_min_confirmations}"
            )

        return ConfluenceResult(
            score=score,
            confirmations=confirmations,
            total=total,
            allowed=allowed,
            checks=checks,
            reasons=reasons,
        )

    def attach(self, signal: Signal) -> Signal:
        result = self.evaluate(signal)
        signal.confluence_score = result.score
        signal.confluence_confirmations = result.confirmations
        signal.confluence_total = result.total
        signal.confluence_allowed = result.allowed
        signal.confluence_checks = result.checks
        signal.confluence_reasons = result.reasons
        return signal
