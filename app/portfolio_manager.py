from dataclasses import dataclass
from decimal import Decimal

from app.models import Signal


@dataclass(slots=True)
class PortfolioPosition:
    symbol: str
    side: str
    risk_percent: Decimal
    position_id: str = ""


@dataclass(slots=True)
class PortfolioAssessment:
    allowed: bool
    adjusted_score: int
    requested_risk_percent: Decimal
    total_risk_after: Decimal
    same_direction_risk_after: Decimal
    group_risk_after: Decimal
    correlation_group: str
    reasons: list[str]


class PortfolioRiskManager:
    def __init__(self, settings) -> None:
        self.settings = settings

    def group_for(self, symbol: str) -> str:
        normalized = symbol.upper()
        for group, symbols in self.settings.correlation_groups.items():
            if normalized in symbols:
                return group
        return "OTHER"

    @staticmethod
    def side_from_position(position: dict) -> str:
        # MEXC positionType: 1 long, 2 short.
        return "LONG" if int(position.get("positionType") or 0) == 1 else "SHORT"

    def estimate_position_risk_percent(
        self,
        position: dict,
        equity_usdt: Decimal,
    ) -> Decimal:
        """
        Conservative fallback for positions recovered from MEXC.

        MEXC open-position responses do not always provide the active SL price.
        In that case, reserve the configured per-trade risk budget instead of
        assuming zero portfolio risk.
        """
        if equity_usdt <= 0:
            return Decimal(str(self.settings.live_max_risk_per_trade_percent))

        stop_loss = position.get("stopLossPrice")
        average = position.get("holdAvgPrice")
        hold_vol = position.get("holdVol")
        contract_size = position.get("contractSize")

        if (
            stop_loss is not None
            and average is not None
            and hold_vol is not None
            and contract_size is not None
        ):
            distance = abs(Decimal(str(average)) - Decimal(str(stop_loss)))
            risk_usdt = (
                distance
                * Decimal(str(hold_vol))
                * Decimal(str(contract_size))
            )
            if risk_usdt > 0:
                return risk_usdt / equity_usdt * Decimal("100")

        return Decimal(str(self.settings.live_risk_per_trade_percent))

    def positions_from_mexc(
        self,
        positions: list[dict],
        equity_usdt: Decimal,
    ) -> list[PortfolioPosition]:
        result: list[PortfolioPosition] = []
        for position in positions:
            symbol = str(position.get("symbol") or "").upper()
            if not symbol:
                continue
            result.append(
                PortfolioPosition(
                    symbol=symbol,
                    side=self.side_from_position(position),
                    risk_percent=self.estimate_position_risk_percent(
                        position,
                        equity_usdt,
                    ),
                    position_id=str(position.get("positionId") or ""),
                )
            )
        return result

    def assess(
        self,
        signal: Signal,
        positions: list[PortfolioPosition],
        requested_risk_percent: Decimal,
    ) -> PortfolioAssessment:
        score = int(signal.score)
        reasons: list[str] = []
        symbol = signal.symbol.upper()
        group = self.group_for(symbol)

        if self.settings.portfolio_block_same_symbol and any(
            position.symbol == symbol for position in positions
        ):
            return PortfolioAssessment(
                allowed=False,
                adjusted_score=0,
                requested_risk_percent=requested_risk_percent,
                total_risk_after=sum(
                    (position.risk_percent for position in positions),
                    Decimal("0"),
                )
                + requested_risk_percent,
                same_direction_risk_after=Decimal("0"),
                group_risk_after=Decimal("0"),
                correlation_group=group,
                reasons=["По этой паре уже есть открытая позиция"],
            )

        total_current = sum(
            (position.risk_percent for position in positions),
            Decimal("0"),
        )
        same_direction_current = sum(
            (
                position.risk_percent
                for position in positions
                if position.side == signal.side
            ),
            Decimal("0"),
        )
        same_group_positions = [
            position
            for position in positions
            if self.group_for(position.symbol) == group
        ]
        same_group_current = sum(
            (position.risk_percent for position in same_group_positions),
            Decimal("0"),
        )

        total_after = total_current + requested_risk_percent
        direction_after = same_direction_current + requested_risk_percent
        group_after = same_group_current + requested_risk_percent

        if same_direction_current > 0:
            score -= self.settings.portfolio_reduce_score_same_direction
            reasons.append(
                "Оценка снижена из-за уже открытой позиции в том же направлении"
            )

        if same_group_positions:
            score -= self.settings.portfolio_reduce_score_same_group
            reasons.append(
                f"Оценка снижена из-за корреляционной группы {group}"
            )

        allowed = True
        if total_after > Decimal(
            str(self.settings.portfolio_max_total_risk_percent)
        ):
            allowed = False
            reasons.append("Превышен общий лимит риска портфеля")

        if direction_after > Decimal(
            str(self.settings.portfolio_max_same_direction_risk_percent)
        ):
            allowed = False
            reasons.append("Превышен лимит риска в одном направлении")

        if group_after > Decimal(
            str(self.settings.portfolio_max_group_risk_percent)
        ):
            allowed = False
            reasons.append(
                f"Превышен лимит риска корреляционной группы {group}"
            )

        if len(same_group_positions) >= self.settings.portfolio_max_positions_per_group:
            allowed = False
            reasons.append(
                f"В группе {group} уже достигнут лимит позиций"
            )

        if score < self.settings.portfolio_min_adjusted_score_confirm:
            allowed = False
            reasons.append(
                "Скорректированная оценка ниже порога Portfolio Manager"
            )

        return PortfolioAssessment(
            allowed=allowed,
            adjusted_score=max(0, min(score, 100)),
            requested_risk_percent=requested_risk_percent,
            total_risk_after=total_after,
            same_direction_risk_after=direction_after,
            group_risk_after=group_after,
            correlation_group=group,
            reasons=reasons,
        )

    def rank(
        self,
        signals: list[Signal],
        positions: list[PortfolioPosition],
        requested_risk_percent: Decimal,
    ) -> list[tuple[Signal, PortfolioAssessment]]:
        ranked = [
            (
                signal,
                self.assess(
                    signal,
                    positions,
                    requested_risk_percent,
                ),
            )
            for signal in signals
        ]
        ranked.sort(
            key=lambda item: (
                item[1].allowed,
                item[1].adjusted_score,
            ),
            reverse=True,
        )
        return ranked
