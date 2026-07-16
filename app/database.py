import sqlite3
from pathlib import Path
from threading import Lock

from app.models import PaperPosition


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                balance REAL NOT NULL,
                initial_balance REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                status TEXT NOT NULL,
                entry_price REAL NOT NULL,
                current_price REAL NOT NULL,
                initial_quantity REAL NOT NULL,
                remaining_quantity REAL NOT NULL,
                stop_loss REAL NOT NULL,
                initial_stop_loss REAL NOT NULL,
                tp1 REAL NOT NULL,
                tp2 REAL NOT NULL,
                atr REAL NOT NULL,
                leverage INTEGER NOT NULL,
                risk_amount REAL NOT NULL,
                realized_pnl REAL NOT NULL DEFAULT 0,
                fees REAL NOT NULL DEFAULT 0,
                tp1_done INTEGER NOT NULL DEFAULT 0,
                tp2_done INTEGER NOT NULL DEFAULT 0,
                highest_price REAL NOT NULL,
                lowest_price REAL NOT NULL,
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                close_reason TEXT
            );
            """)

    def ensure_account(self, initial_balance: float) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO account(id, balance, initial_balance) VALUES(1, ?, ?)",
                (initial_balance, initial_balance),
            )

    def account(self) -> tuple[float, float]:
        with self.connect() as conn:
            row = conn.execute("SELECT balance, initial_balance FROM account WHERE id=1").fetchone()
            if row is None:
                raise RuntimeError("paper account is not initialized")
            return float(row["balance"]), float(row["initial_balance"])

    def change_balance(self, delta: float) -> None:
        with self._lock, self.connect() as conn:
            conn.execute("UPDATE account SET balance = balance + ? WHERE id=1", (delta,))

    @staticmethod
    def _row_to_position(row: sqlite3.Row) -> PaperPosition:
        return PaperPosition(
            id=row["id"], symbol=row["symbol"], side=row["side"], status=row["status"],
            entry_price=row["entry_price"], current_price=row["current_price"],
            initial_quantity=row["initial_quantity"], remaining_quantity=row["remaining_quantity"],
            stop_loss=row["stop_loss"], initial_stop_loss=row["initial_stop_loss"],
            tp1=row["tp1"], tp2=row["tp2"], atr=row["atr"], leverage=row["leverage"],
            risk_amount=row["risk_amount"], realized_pnl=row["realized_pnl"], fees=row["fees"],
            tp1_done=bool(row["tp1_done"]), tp2_done=bool(row["tp2_done"]),
            highest_price=row["highest_price"], lowest_price=row["lowest_price"],
            opened_at=row["opened_at"], closed_at=row["closed_at"], close_reason=row["close_reason"],
        )

    def insert_position(self, values: dict) -> int:
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        with self._lock, self.connect() as conn:
            cur = conn.execute(
                f"INSERT INTO positions ({columns}) VALUES ({placeholders})",
                tuple(values.values()),
            )
            return int(cur.lastrowid)

    def update_position(self, position_id: int, **values) -> None:
        if not values:
            return
        assignments = ",".join(f"{name}=?" for name in values)
        with self._lock, self.connect() as conn:
            conn.execute(
                f"UPDATE positions SET {assignments} WHERE id=?",
                (*values.values(), position_id),
            )

    def open_positions(self) -> list[PaperPosition]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM positions WHERE status='OPEN' ORDER BY id").fetchall()
            return [self._row_to_position(row) for row in rows]

    def position(self, position_id: int) -> PaperPosition | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
            return self._row_to_position(row) if row else None

    def recent_closed(self, limit: int = 10) -> list[PaperPosition]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status='CLOSED' ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._row_to_position(row) for row in rows]
