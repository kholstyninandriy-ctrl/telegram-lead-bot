"""SQLite-шар: CRM-нотатки, збережені ліди, кеш пошуку, нагадування.

Всі публічні функції мають async-обгортку (`a*`), яка виконує запит у
окремому потоці — щоб синхронний sqlite не блокував event loop бота.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from config import DB_PATH, SEARCH_CACHE_TTL_MIN

TS_FMT = "%Y-%m-%d %H:%M"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ts_now() -> str:
    return utc_now().strftime(TS_FMT)


@contextmanager
def _con():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        yield con
        con.commit()
    finally:
        con.close()


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}


def init_db() -> None:
    with _con() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                biz_name    TEXT,
                phone       TEXT,
                status      TEXT,
                comment     TEXT,
                created_at  TEXT NOT NULL
            )
        """)
        # Міграції для баз, створених попередніми версіями бота
        cols = _columns(con, "notes")
        for name, ddl in (
            ("place_id", "ALTER TABLE notes ADD COLUMN place_id TEXT"),
            ("remind_at", "ALTER TABLE notes ADD COLUMN remind_at TEXT"),
            ("reminded", "ALTER TABLE notes ADD COLUMN reminded INTEGER DEFAULT 0"),
        ):
            if name not in cols:
                con.execute(ddl)

        con.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                place_id    TEXT,
                query       TEXT,
                created_at  TEXT NOT NULL,
                payload     TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                cache_key   TEXT PRIMARY KEY,
                created_at  TEXT NOT NULL,
                payload     TEXT NOT NULL
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, id DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_leads_user ON leads(user_id, id DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_notes_remind ON notes(reminded, remind_at)")


# ─── Нотатки ──────────────────────────────────────────────────────────────────

def add_note(user_id: int, biz_name: str, phone: str, status: str,
             comment: str, place_id: str = "") -> int:
    with _con() as con:
        cur = con.execute(
            "INSERT INTO notes (user_id, biz_name, phone, status, comment, created_at, place_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, biz_name, phone, status, comment, ts_now(), place_id),
        )
        return int(cur.lastrowid)


def get_notes(user_id: int, status: str = "", limit: int = 500) -> list[dict]:
    sql = "SELECT * FROM notes WHERE user_id=?"
    args: list[Any] = [user_id]
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with _con() as con:
        return [dict(r) for r in con.execute(sql, args)]


def delete_note(note_id: int, user_id: int) -> bool:
    with _con() as con:
        cur = con.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
        return cur.rowcount > 0


def notes_stats(user_id: int) -> dict:
    with _con() as con:
        rows = con.execute(
            "SELECT status, COUNT(*) AS c FROM notes WHERE user_id=? GROUP BY status",
            (user_id,),
        ).fetchall()
        total = con.execute(
            "SELECT COUNT(*) AS c FROM notes WHERE user_id=?", (user_id,)
        ).fetchone()["c"]
        week_ago = (utc_now() - timedelta(days=7)).strftime(TS_FMT)
        week = con.execute(
            "SELECT COUNT(*) AS c FROM notes WHERE user_id=? AND created_at>=?",
            (user_id, week_ago),
        ).fetchone()["c"]
        leads_total = con.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE user_id=?", (user_id,)
        ).fetchone()["c"]
    return {
        "total": total,
        "week": week,
        "leads_total": leads_total,
        "by_status": {r["status"]: r["c"] for r in rows},
    }


def contacted_keys(user_id: int) -> set[str]:
    """Ключі (place_id / цифри телефону / назва) бізнесів, які вже є в CRM."""
    keys: set[str] = set()
    with _con() as con:
        for r in con.execute(
            "SELECT biz_name, phone, place_id FROM notes WHERE user_id=?", (user_id,)
        ):
            if r["place_id"]:
                keys.add(f"id:{r['place_id']}")
            digits = "".join(ch for ch in (r["phone"] or "") if ch.isdigit())
            if len(digits) >= 7:
                keys.add(f"tel:{digits}")
            if r["biz_name"]:
                keys.add(f"name:{r['biz_name'].strip().lower()}")
    return keys


# ─── Нагадування ──────────────────────────────────────────────────────────────

def set_reminder(note_id: int, user_id: int, when: datetime) -> bool:
    with _con() as con:
        cur = con.execute(
            "UPDATE notes SET remind_at=?, reminded=0 WHERE id=? AND user_id=?",
            (when.astimezone(timezone.utc).strftime(TS_FMT), note_id, user_id),
        )
        return cur.rowcount > 0


def pending_reminders() -> list[dict]:
    with _con() as con:
        return [
            dict(r)
            for r in con.execute(
                "SELECT * FROM notes WHERE remind_at IS NOT NULL AND COALESCE(reminded,0)=0"
            )
        ]


def mark_reminded(note_id: int) -> None:
    with _con() as con:
        con.execute("UPDATE notes SET reminded=1 WHERE id=?", (note_id,))


# ─── Ліди ─────────────────────────────────────────────────────────────────────

def save_leads(user_id: int, query: str, leads: Iterable[dict]) -> list[int]:
    """Зберігає ліди пошуку і повертає їхні id — вони йдуть у callback_data кнопок,
    тому кнопки під картками працюють навіть після перезапуску бота."""
    ids: list[int] = []
    ts = ts_now()
    with _con() as con:
        for lead in leads:
            cur = con.execute(
                "INSERT INTO leads (user_id, place_id, query, created_at, payload) VALUES (?,?,?,?,?)",
                (user_id, lead.get("place_id", ""), query, ts,
                 json.dumps(lead, ensure_ascii=False)),
            )
            ids.append(int(cur.lastrowid))
    return ids


def get_lead(lead_id: int, user_id: int) -> dict | None:
    with _con() as con:
        row = con.execute(
            "SELECT payload FROM leads WHERE id=? AND user_id=?", (lead_id, user_id)
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["payload"])
    except json.JSONDecodeError:
        return None
    data["lead_id"] = lead_id
    return data


def last_search_leads(user_id: int) -> list[dict]:
    """Ліди останнього пошуку користувача (для /export_search)."""
    with _con() as con:
        row = con.execute(
            "SELECT query, created_at FROM leads WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if not row:
            return []
        rows = con.execute(
            "SELECT payload FROM leads WHERE user_id=? AND query=? AND created_at=? ORDER BY id",
            (user_id, row["query"], row["created_at"]),
        ).fetchall()
    out = []
    for r in rows:
        try:
            out.append(json.loads(r["payload"]))
        except json.JSONDecodeError:
            continue
    return out


def prune_leads(user_id: int, keep: int = 500) -> None:
    with _con() as con:
        con.execute(
            "DELETE FROM leads WHERE user_id=? AND id NOT IN "
            "(SELECT id FROM leads WHERE user_id=? ORDER BY id DESC LIMIT ?)",
            (user_id, user_id, keep),
        )


# ─── Кеш пошуку ───────────────────────────────────────────────────────────────

def cache_get(key: str) -> list[dict] | None:
    if SEARCH_CACHE_TTL_MIN <= 0:
        return None
    with _con() as con:
        row = con.execute(
            "SELECT created_at, payload FROM search_cache WHERE cache_key=?", (key,)
        ).fetchone()
    if not row:
        return None
    try:
        created = datetime.strptime(row["created_at"], TS_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if utc_now() - created > timedelta(minutes=SEARCH_CACHE_TTL_MIN):
        return None
    try:
        return json.loads(row["payload"])
    except json.JSONDecodeError:
        return None


def cache_put(key: str, places: list[dict]) -> None:
    if SEARCH_CACHE_TTL_MIN <= 0:
        return
    with _con() as con:
        con.execute(
            "INSERT OR REPLACE INTO search_cache (cache_key, created_at, payload) VALUES (?,?,?)",
            (key, ts_now(), json.dumps(places, ensure_ascii=False)),
        )
        con.execute(
            "DELETE FROM search_cache WHERE cache_key NOT IN "
            "(SELECT cache_key FROM search_cache ORDER BY created_at DESC LIMIT 200)"
        )


# ─── async-обгортки ───────────────────────────────────────────────────────────

async def ainit_db() -> None:
    await asyncio.to_thread(init_db)


async def aadd_note(*args, **kwargs) -> int:
    return await asyncio.to_thread(add_note, *args, **kwargs)


async def aget_notes(*args, **kwargs) -> list[dict]:
    return await asyncio.to_thread(get_notes, *args, **kwargs)


async def adelete_note(*args, **kwargs) -> bool:
    return await asyncio.to_thread(delete_note, *args, **kwargs)


async def anotes_stats(user_id: int) -> dict:
    return await asyncio.to_thread(notes_stats, user_id)


async def acontacted_keys(user_id: int) -> set[str]:
    return await asyncio.to_thread(contacted_keys, user_id)


async def asave_leads(*args, **kwargs) -> list[int]:
    return await asyncio.to_thread(save_leads, *args, **kwargs)


async def aget_lead(lead_id: int, user_id: int) -> dict | None:
    return await asyncio.to_thread(get_lead, lead_id, user_id)


async def alast_search_leads(user_id: int) -> list[dict]:
    return await asyncio.to_thread(last_search_leads, user_id)


async def aprune_leads(user_id: int, keep: int = 500) -> None:
    await asyncio.to_thread(prune_leads, user_id, keep)


async def acache_get(key: str) -> list[dict] | None:
    return await asyncio.to_thread(cache_get, key)


async def acache_put(key: str, places: list[dict]) -> None:
    await asyncio.to_thread(cache_put, key, places)


async def aset_reminder(note_id: int, user_id: int, when: datetime) -> bool:
    return await asyncio.to_thread(set_reminder, note_id, user_id, when)


async def apending_reminders() -> list[dict]:
    return await asyncio.to_thread(pending_reminders)


async def amark_reminded(note_id: int) -> None:
    await asyncio.to_thread(mark_reminded, note_id)
