"""Persistent previews and atomic reservations shared by CLI and UI processes."""
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3


class OrderStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS orders (
                preview_id TEXT PRIMARY KEY, client_order_id TEXT UNIQUE NOT NULL,
                account TEXT NOT NULL, amount_cents INTEGER NOT NULL,
                expires REAL NOT NULL, state TEXT NOT NULL,
                submitted_day TEXT, preview TEXT NOT NULL, result TEXT
            )''')
            db.execute('''CREATE TABLE IF NOT EXISTS execution_mode (
                id INTEGER PRIMARY KEY CHECK (id=1), enabled INTEGER NOT NULL,
                revision INTEGER NOT NULL
            )''')
            db.execute('''CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY, account TEXT NOT NULL, state TEXT NOT NULL,
                expires REAL NOT NULL, preview TEXT NOT NULL, owner TEXT,
                heartbeat REAL, stop INTEGER NOT NULL DEFAULT 0,
                completed_count INTEGER NOT NULL DEFAULT 0,
                submitted_amount TEXT NOT NULL DEFAULT '0',
                submitted_quantity TEXT NOT NULL DEFAULT '0', message TEXT NOT NULL DEFAULT ''
            )''')
            db.execute('''CREATE TABLE IF NOT EXISTS batch_children (
                batch_id TEXT NOT NULL, sequence INTEGER NOT NULL, state TEXT NOT NULL,
                payload TEXT NOT NULL, result TEXT, PRIMARY KEY(batch_id, sequence)
            )''')

    @staticmethod
    def assert_no_active_batch(db, account):
        if db.execute("SELECT 1 FROM batches WHERE account=? AND state IN ('RUNNING','STOPPING','UNKNOWN','INTERRUPTED')", (account,)).fetchone():
            raise ValueError("진행 중이거나 결과 확인이 필요한 분할 주문이 있습니다. 주문 기록을 확인해 주세요.")

    @staticmethod
    def mode(db, default=False):
        row = db.execute("SELECT enabled,revision FROM execution_mode WHERE id=1").fetchone()
        return {"executionEnabled": bool(row["enabled"]) if row else default,
                "modeRevision": row["revision"] if row else 0}

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def save(self, preview):
        with self.connect(write=True) as db:
            if self.mode(db)["modeRevision"] != preview.get("modeRevision", 0):
                raise ValueError("주문 모드가 변경되었습니다. 다시 미리보기해 주세요.")
            db.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?, 'PREVIEW', NULL, ?, NULL)", (
                preview["previewId"], preview["clientOrderId"], preview["accountSeq"],
                preview["amountCents"], preview["expiresTimestamp"], json.dumps(preview)))

    @staticmethod
    def spent(db, day, account):
        return db.execute("""SELECT COALESCE(SUM(amount_cents), 0) FROM orders
            WHERE submitted_day=? AND account=? AND state IN ('SUBMITTING','SUBMITTED','UNKNOWN')""",
                          (day, account)).fetchone()[0]

    def finish(self, preview_id, state, result):
        with self.connect(write=True) as db:
            db.execute("UPDATE orders SET state=?, result=? WHERE preview_id=?",
                       (state, json.dumps(result), preview_id))

    def history(self):
        with self.connect() as db:
            rows = db.execute("SELECT preview,state,result FROM orders WHERE state != 'PREVIEW' ORDER BY rowid DESC LIMIT 30").fetchall()
        return [{"preview": json.loads(row["preview"]), "state": row["state"],
                 "result": json.loads(row["result"]) if row["result"] else None} for row in rows]
