import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from app.models import PaperPosition, Signal


@dataclass(slots=True)
class LearningSummary:
    total_samples: int
    opened_samples: int
    closed_samples: int
    wins: int
    losses: int
    win_rate: float
    average_pnl: float
    best_setup: str


class LearningEngine:
    """Stores immutable signal features and links them to PAPER outcomes.

    v1.8.0 deliberately does not mutate strategy weights. It creates the
    trustworthy dataset needed for later calibration.
    """

    def __init__(self, path: str, enabled: bool = True) -> None:
        self.enabled = enabled
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        if enabled:
            self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS learning_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    scanner_score INTEGER NOT NULL,
                    opportunity_score INTEGER,
                    prediction_score INTEGER,
                    prediction_state TEXT NOT NULL,
                    breakout_readiness INTEGER,
                    false_breakout_risk INTEGER,
                    trigger_score INTEGER,
                    trigger_state TEXT NOT NULL,
                    trigger_confirmed INTEGER NOT NULL DEFAULT 0,
                    market_score INTEGER,
                    market_rank INTEGER NOT NULL DEFAULT 0,
                    decision_score INTEGER,
                    decision_action TEXT NOT NULL,
                    entry_quality INTEGER,
                    confluence_score INTEGER,
                    relative_strength INTEGER,
                    market_regime TEXT NOT NULL,
                    btc_context TEXT NOT NULL,
                    features_json TEXT NOT NULL,
                    paper_position_id INTEGER UNIQUE,
                    opened_at TEXT,
                    closed_at TEXT,
                    outcome TEXT,
                    realized_pnl REAL,
                    close_reason TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_learning_symbol_created
                    ON learning_samples(symbol, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_learning_outcome
                    ON learning_samples(outcome);
                """
            )

    @staticmethod
    def _features(signal: Signal) -> dict:
        return {
            "timeframe_scores": signal.timeframe_scores or {},
            "diagnostics": signal.diagnostics or {},
            "component_scores": signal.component_scores or {},
            "opportunity_components": signal.opportunity_components or {},
            "prediction_components": signal.prediction_components or {},
            "trigger_components": signal.trigger_components or {},
            "confluence_checks": signal.confluence_checks or {},
            "volatility_state": signal.volatility_state,
            "liquidity_state": signal.liquidity_state,
            "detailed_regime": signal.detailed_regime,
            "market_breadth_state": signal.market_breadth_state,
            "entry_timing": signal.entry_timing,
            "entry_phase": signal.entry_phase,
            "prediction_state": signal.prediction_state,
            "trigger_state": signal.trigger_state,
            "opportunity_stage": signal.opportunity_stage,
        }

    def record_signal(self, signal: Signal) -> int | None:
        if not self.enabled:
            return None
        now = datetime.now(timezone.utc).isoformat()
        values = (
            now, signal.symbol, signal.side, signal.score,
            signal.opportunity_score, signal.prediction_score, signal.prediction_state,
            signal.breakout_readiness, signal.false_breakout_risk,
            signal.trigger_score, signal.trigger_state, int(signal.trigger_confirmed),
            signal.market_opportunity_score, signal.market_opportunity_rank,
            signal.decision_score, signal.decision_action,
            signal.entry_quality_score, signal.confluence_score,
            signal.relative_strength_score, signal.detailed_regime,
            signal.btc_context,
            json.dumps(self._features(signal), ensure_ascii=False, sort_keys=True),
        )
        with self._lock, self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO learning_samples (
                    created_at, symbol, side, scanner_score,
                    opportunity_score, prediction_score, prediction_state, breakout_readiness,
                    false_breakout_risk, trigger_score, trigger_state, trigger_confirmed,
                    market_score, market_rank, decision_score, decision_action,
                    entry_quality, confluence_score, relative_strength,
                    market_regime, btc_context, features_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                values,
            )
            return int(cur.lastrowid)

    def attach_paper_position(self, signal: Signal, position: PaperPosition) -> None:
        if not self.enabled:
            return
        with self._lock, self.connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM learning_samples
                WHERE symbol=? AND side=? AND paper_position_id IS NULL
                ORDER BY id DESC LIMIT 1
                """,
                (signal.symbol, signal.side),
            ).fetchone()
            if row is None:
                sample_id = self.record_signal(signal)
            else:
                sample_id = int(row["id"])
            conn.execute(
                """
                UPDATE learning_samples
                SET paper_position_id=?, opened_at=?
                WHERE id=?
                """,
                (position.id, position.opened_at, sample_id),
            )

    @staticmethod
    def classify_outcome(position: PaperPosition) -> str:
        net = position.realized_pnl - position.fees
        reason = (position.close_reason or "").upper()
        if net > 0:
            return "WIN"
        if net < 0:
            return "LOSS"
        if "BREAK" in reason or "BE" == reason:
            return "BREAKEVEN"
        return "FLAT"

    def sync_closed_positions(self, positions: list[PaperPosition]) -> int:
        if not self.enabled:
            return 0
        updated = 0
        with self._lock, self.connect() as conn:
            for position in positions:
                cur = conn.execute(
                    """
                    UPDATE learning_samples
                    SET closed_at=?, outcome=?, realized_pnl=?, close_reason=?
                    WHERE paper_position_id=? AND outcome IS NULL
                    """,
                    (
                        position.closed_at,
                        self.classify_outcome(position),
                        position.realized_pnl - position.fees,
                        position.close_reason,
                        position.id,
                    ),
                )
                updated += cur.rowcount
        return updated

    def summary(self) -> LearningSummary:
        if not self.enabled:
            return LearningSummary(0, 0, 0, 0, 0, 0.0, 0.0, "—")
        with self.connect() as conn:
            totals = conn.execute(
                """
                SELECT COUNT(*) total,
                       SUM(CASE WHEN paper_position_id IS NOT NULL THEN 1 ELSE 0 END) opened,
                       SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) closed,
                       SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) wins,
                       SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) losses,
                       AVG(CASE WHEN outcome IS NOT NULL THEN realized_pnl END) avg_pnl
                FROM learning_samples
                """
            ).fetchone()
            best = conn.execute(
                """
                SELECT prediction_state, trigger_state, COUNT(*) n,
                       AVG(CASE WHEN outcome='WIN' THEN 1.0 ELSE 0.0 END) wr
                FROM learning_samples
                WHERE outcome IN ('WIN','LOSS')
                GROUP BY prediction_state, trigger_state
                HAVING COUNT(*) >= 3
                ORDER BY wr DESC, n DESC LIMIT 1
                """
            ).fetchone()
        wins = int(totals["wins"] or 0)
        losses = int(totals["losses"] or 0)
        decided = wins + losses
        best_setup = "—" if best is None else (
            f"{best['prediction_state']}→{best['trigger_state']} "
            f"({float(best['wr']) * 100:.1f}%, n={best['n']})"
        )
        return LearningSummary(
            total_samples=int(totals["total"] or 0),
            opened_samples=int(totals["opened"] or 0),
            closed_samples=int(totals["closed"] or 0),
            wins=wins,
            losses=losses,
            win_rate=(wins / decided * 100) if decided else 0.0,
            average_pnl=float(totals["avg_pnl"] or 0.0),
            best_setup=best_setup,
        )
