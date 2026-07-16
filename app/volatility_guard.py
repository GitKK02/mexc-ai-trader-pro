from dataclasses import dataclass
from decimal import Decimal

from app.models import Signal


@dataclass(slots=True)
class VolatilityGuardResult:
    allowed: bool
    risk_multiplier: Decimal
    volatility_state: str
    liquidity_state: str
    reasons: list[str]


class VolatilityLiquidityGuard:
    def __init__(self, settings) -> None:
        self.settings = settings

    def evaluate(
        self,
        signal: Signal,
        *,
        turnover_24h: Decimal,
        spread_percent: Decimal,
    ) -> VolatilityGuardResult:
        diagnostics = signal.diagnostics or {}
        atr_percent = Decimal(
            str(diagnostics.get("primary_atr_percent", 0) or 0)
        )
        relative_volume = Decimal(
            str(diagnostics.get("primary_relative_volume", 0) or 0)
        )
        momentum = Decimal(
            str(diagnostics.get("primary_momentum_percent", 0) or 0)
        )

        reasons: list[str] = []
        multiplier = Decimal("1")
        allowed = True

        panic_atr = Decimal(
            str(self.settings.volatility_guard_panic_atr_percent)
        )
        extreme_move = Decimal(
            str(self.settings.volatility_guard_extreme_move_percent)
        )

        if atr_percent >= panic_atr or abs(momentum) >= extreme_move:
            volatility_state = "PANIC"
            reasons.append("Резкое движение или экстремальный ATR")
            if self.settings.volatility_guard_block_panic:
                allowed = False
        elif atr_percent >= panic_atr * Decimal("0.6"):
            volatility_state = "HIGH"
            multiplier *= Decimal(
                str(
                    self.settings
                    .volatility_guard_reduce_risk_high_vol_multiplier
                )
            )
            reasons.append("Высокая волатильность: риск уменьшен")
        elif atr_percent <= Decimal("0.35"):
            volatility_state = "LOW"
            reasons.append("Низкая волатильность")
        else:
            volatility_state = "NORMAL"

        max_spread = Decimal(
            str(self.settings.volatility_guard_max_spread_percent)
        )
        min_volume = Decimal(
            str(self.settings.volatility_guard_min_relative_volume)
        )
        min_turnover = Decimal(
            str(
                self.settings
                .volatility_guard_low_liquidity_turnover_usdt
            )
        )

        if turnover_24h < min_turnover:
            liquidity_state = "LOW"
            reasons.append("Недостаточный суточный оборот")
            if self.settings.volatility_guard_block_low_liquidity:
                allowed = False
        elif spread_percent > max_spread:
            liquidity_state = "WIDE_SPREAD"
            multiplier *= Decimal(
                str(
                    self.settings
                    .volatility_guard_reduce_risk_wide_spread_multiplier
                )
            )
            reasons.append("Широкий спред: риск уменьшен")
        elif relative_volume < min_volume:
            liquidity_state = "THIN_VOLUME"
            multiplier *= Decimal(
                str(
                    self.settings
                    .volatility_guard_reduce_risk_low_volume_multiplier
                )
            )
            reasons.append("Слабый относительный объём: риск уменьшен")
        else:
            liquidity_state = "NORMAL"

        multiplier = max(Decimal("0.10"), min(multiplier, Decimal("1")))

        return VolatilityGuardResult(
            allowed=allowed,
            risk_multiplier=multiplier,
            volatility_state=volatility_state,
            liquidity_state=liquidity_state,
            reasons=reasons,
        )

    def attach(
        self,
        signal: Signal,
        *,
        turnover_24h: Decimal,
        spread_percent: Decimal,
    ) -> Signal:
        result = self.evaluate(
            signal,
            turnover_24h=turnover_24h,
            spread_percent=spread_percent,
        )
        signal.volatility_state = result.volatility_state
        signal.liquidity_state = result.liquidity_state
        signal.volatility_guard_allowed = result.allowed
        signal.volatility_guard_multiplier = float(
            result.risk_multiplier
        )
        signal.volatility_guard_reasons = result.reasons
        return signal
