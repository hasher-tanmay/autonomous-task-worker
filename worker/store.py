"""SQLite is the source of truth. Every sandbox has its own rows."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

SEED = [
    dict(id="X-100", vendor="Company X", issued="2026-09-02", amount="980.00", currency="USD", due="2026-09-30"),
    dict(id="X-101", vendor="Company X", issued="2026-10-01", amount="1240.50", currency="USD", due="2026-10-31"),
    dict(id="A-201", vendor="Acme Supplies", issued="2026-10-02", amount="325.75", currency="USD", due="2026-10-20"),
    dict(id="N-301", vendor="Northstar Labs", issued="2026-09-28", amount="7800.00", currency="USD", due="2026-10-28"),
    dict(id="B-401", vendor="Broken Fields Ltd", issued="2026-10-03", amount="49.00", currency="USD", due=""),
]

class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, fault TEXT, consumed INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS records(
              session TEXT, id TEXT, vendor TEXT, amount TEXT, currency TEXT, due TEXT,
              PRIMARY KEY(session, id), FOREIGN KEY(session) REFERENCES sessions(id));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def new_session(self, fault="none"):
        sid = uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO sessions(id,fault) VALUES(?,?)", (sid, fault))
        return sid

    def exists(self, sid):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone() is not None

    def list_records(self, sid):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,vendor,amount,currency,due FROM records WHERE session=? ORDER BY id", (sid,))]

    def save(self, sid, record):
        # Faults are intentional test scenarios; browser work and persistence are real.
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
            if not row:
                return {"ok": False, "error": "Unknown sandbox"}
            if row["fault"] == "always_fail":
                return {"ok": False, "error": "Service unavailable"}
            if not row["consumed"] and row["fault"] in ("fail_once", "lost_ack", "corrupt"):
                db.execute("UPDATE sessions SET consumed=1 WHERE id=?", (sid,))
                if row["fault"] == "fail_once":
                    return {"ok": False, "error": "Temporary save failure"}
                if row["fault"] == "corrupt":
                    record = {**record, "amount": "0.01"}
            before = db.execute("SELECT 1 FROM records WHERE session=? AND id=?", (sid, record["id"])).fetchone()
            db.execute("INSERT OR IGNORE INTO records VALUES(?,?,?,?,?,?)",
                       (sid, *(record[k] for k in ("id", "vendor", "amount", "currency", "due"))))
            if row["fault"] == "lost_ack" and not row["consumed"]:
                return {"ok": False, "error": "Connection lost after save; outcome unknown"}
            return {"ok": True, "duplicate": bool(before)}
