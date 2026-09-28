"""Збереження лідів і записів. SQLite за замовчуванням (для Supabase — див. README)."""

import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("RECEPTIONIST_DB", os.path.join(os.path.dirname(__file__), "receptionist.db"))


def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT NOT NULL,
                channel     TEXT NOT NULL,
                business    TEXT,
                niche       TEXT,
                name        TEXT NOT NULL,
                phone       TEXT NOT NULL,
                email       TEXT,
                start_at    TEXT NOT NULL,
                notes       TEXT,
                calendar    TEXT,
                external_id TEXT
            )
        """)


def save_booking(**row) -> int:
    row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(f"INSERT INTO bookings ({cols}) VALUES ({marks})", tuple(row.values()))
        return cur.lastrowid


def list_bookings(limit: int = 50) -> list[dict]:
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM bookings ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
