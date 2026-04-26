import sqlite3
import json
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

DB_PATH = "/app/data/advisor.db"


@dataclass
class Recommendation:
    category: str          # index | workload | health | config
    severity: str          # critical | warning | info
    title: str
    description: str
    action: str            # what to do
    sql: Optional[str]     # ready-to-run SQL if applicable


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                category    TEXT NOT NULL,
                severity    TEXT NOT NULL,
                title       TEXT NOT NULL,
                description TEXT NOT NULL,
                action      TEXT NOT NULL,
                sql         TEXT,
                status      TEXT NOT NULL DEFAULT 'open',
                created_at  TEXT NOT NULL,
                resolved_at TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_status
            ON recommendations(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_title
            ON recommendations(title, status)
        """)


def upsert_recommendations(recs: list[Recommendation]):
    """
    Insert new recommendations.
    Skip if a recommendation with the same title is already open or dismissed.
    If it was previously resolved and the problem is back — reopen it.
    """
    now = datetime.utcnow().isoformat()
    with _connect() as conn:
        for rec in recs:
            existing = conn.execute(
                "SELECT id, status FROM recommendations WHERE title = ? ORDER BY id DESC LIMIT 1",
                (rec.title,)
            ).fetchone()

            if existing is None:
                # Brand new recommendation
                conn.execute(
                    """INSERT INTO recommendations
                       (category, severity, title, description, action, sql, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'open', ?)""",
                    (rec.category, rec.severity, rec.title,
                     rec.description, rec.action, rec.sql, now)
                )
            elif existing["status"] == "resolved":
                # Problem came back — reopen
                conn.execute(
                    """INSERT INTO recommendations
                       (category, severity, title, description, action, sql, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'open', ?)""",
                    (rec.category, rec.severity, rec.title,
                     rec.description, rec.action, rec.sql, now)
                )
            # status = open or dismissed → leave as is


def get_recommendations(status: Optional[str] = None) -> list[dict]:
    with _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM recommendations WHERE status = ? ORDER BY id DESC",
                (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM recommendations ORDER BY id DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def update_status(rec_id: int, status: str) -> bool:
    """Set status to: open | dismissed | resolved"""
    now = datetime.utcnow().isoformat() if status in ("resolved", "dismissed") else None
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE recommendations SET status = ?, resolved_at = ? WHERE id = ?",
            (status, now, rec_id)
        )
        return cur.rowcount > 0
