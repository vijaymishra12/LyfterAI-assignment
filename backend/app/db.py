"""SQLite storage for session history (no external services)."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import settings


def db_path() -> str:
    url = settings.database_url
    prefix = "sqlite:///"  # sqlite:////data/app.db -> /data/app.db
    return url[len(prefix):] if url.startswith(prefix) else url


@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    parent = os.path.dirname(db_path())
    if parent:
        os.makedirs(parent, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                system_prompt TEXT,
                created_at TEXT NOT NULL
            )"""
        )


def ping() -> bool:
    with connect() as conn:
        conn.execute("SELECT 1").fetchone()
    return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_system_prompt(session_id: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return row["system_prompt"] if row else None


def get_history(session_id: str) -> list[dict]:
    """Plain {role, content} dicts, oldest first, ready to send to the LLM."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def get_messages(session_id: str) -> list[dict] | None:
    """History for the API (with metadata on assistant messages). None if unknown."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    if not rows:
        return None
    out = []
    for r in rows:
        item = {"role": r["role"], "content": r["content"]}
        if r["role"] == "assistant" and r["metadata"]:
            item["metadata"] = json.loads(r["metadata"])
        out.append(item)
    return out


def add_exchange(
    session_id: str,
    user_message: str,
    reply: str,
    metadata: dict,
    system_prompt: str | None,
) -> None:
    """Persist one successful turn atomically. Failed requests never reach this."""
    with connect() as conn:
        if system_prompt is not None:
            conn.execute(
                """INSERT INTO sessions (session_id, system_prompt, created_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET system_prompt = excluded.system_prompt""",
                (session_id, system_prompt, _now()),
            )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, 'user', ?, NULL, ?)",
            (session_id, user_message, _now()),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, 'assistant', ?, ?, ?)",
            (session_id, reply, json.dumps(metadata), _now()),
        )
