import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


class LiveDatabase:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        with self.connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS live_trades(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_oid TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                state TEXT NOT NULL,
                signal_score INTEGER NOT NULL,
                requested_risk_usdt REAL NOT NULL,
                contracts REAL NOT NULL,
                contract_size REAL NOT NULL,
                reference_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                leverage INTEGER NOT NULL,
                mexc_order_id TEXT,
                mexc_position_id TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS daily_state(
                day TEXT PRIMARY KEY,
                trades_count INTEGER NOT NULL DEFAULT 0,
                realized_pnl REAL NOT NULL DEFAULT 0
            );
            """)

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_trade(self, values: dict) -> int:
        now = datetime.now(timezone.utc).isoformat()
        values = {**values, "created_at": now, "updated_at": now}
        cols = ",".join(values)
        marks = ",".join("?" for _ in values)
        with self.lock, self.connect() as conn:
            cur = conn.execute(f"INSERT INTO live_trades({cols}) VALUES({marks})", tuple(values.values()))
            return int(cur.lastrowid)

    def update_trade(self, trade_id: int, **values) -> None:
        if not values:
            return
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        assignments = ",".join(f"{k}=?" for k in values)
        with self.lock, self.connect() as conn:
            conn.execute(f"UPDATE live_trades SET {assignments} WHERE id=?", (*values.values(), trade_id))

    def today(self) -> tuple[int, float]:
        day = datetime.now(timezone.utc).date().isoformat()
        with self.lock, self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO daily_state(day) VALUES(?)", (day,))
            row = conn.execute("SELECT trades_count, realized_pnl FROM daily_state WHERE day=?", (day,)).fetchone()
            return int(row["trades_count"]), float(row["realized_pnl"])

    def increment_trade_count(self) -> None:
        day = datetime.now(timezone.utc).date().isoformat()
        with self.lock, self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO daily_state(day) VALUES(?)", (day,))
            conn.execute("UPDATE daily_state SET trades_count=trades_count+1 WHERE day=?", (day,))

    def recent(self, limit: int = 10):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM live_trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
