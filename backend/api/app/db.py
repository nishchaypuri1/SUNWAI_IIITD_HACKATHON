"""SQLite persistence (stdlib sqlite3). One shared connection, serialised by a lock.

Tables mirror the master prompt's data model. Rich objects (steps, drafts, packets) are stored as JSON
so the API layer can rebuild contract objects without a mapping layer.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS forums (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rules (
  id TEXT PRIMARY KEY, forum_id TEXT NOT NULL, version INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  data TEXT NOT NULL, fetched_at TEXT, created_at TEXT NOT NULL, last_refresh_failed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_rules_forum ON rules(forum_id, active);
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, state TEXT NOT NULL,
  language TEXT NOT NULL, text_masked TEXT NOT NULL, case_json TEXT NOT NULL, questions_json TEXT NOT NULL,
  warnings_json TEXT NOT NULL, timeline_json TEXT NOT NULL, meta_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steps (
  case_id TEXT NOT NULL, ordinal INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (case_id, ordinal)
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, case_id TEXT, step_ordinal INTEGER, kind TEXT NOT NULL, status TEXT NOT NULL,
  portal_mode TEXT, portal_url TEXT, portal_key TEXT, tinyfish_run_id TEXT, streaming_url TEXT, video_url TEXT,
  started_at TEXT, ended_at TEXT, raw_events_count INTEGER NOT NULL DEFAULT 0, error_json TEXT,
  screenshots_json TEXT, result_json TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_runs_case ON runs(case_id);
CREATE TABLE IF NOT EXISTS run_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, seq INTEGER NOT NULL, tf_type TEXT NOT NULL,
  message TEXT NOT NULL, raw_json TEXT, at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_run_events_run ON run_events(run_id, seq);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, type TEXT NOT NULL, payload_json TEXT NOT NULL, at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_case ON events(case_id, id);
CREATE TABLE IF NOT EXISTS sandbox_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, kind TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grievance_cache (key TEXT PRIMARY KEY, route_json TEXT NOT NULL, checked_at TEXT NOT NULL);
"""

_conn: sqlite3.Connection | None = None
_lock = threading.RLock()


def _connect() -> sqlite3.Connection:
    path = get_settings().sqlite_path
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL" if path != ":memory:" else "PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = _connect()
            _conn.executescript(SCHEMA)
        return _conn


def init_db() -> None:
    """Create tables and seed static data. Safe to call repeatedly."""
    conn()
    from .seed import seed_all  # local import to avoid a cycle

    seed_all()


def close_db() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    c = conn()
    with _lock:
        c.execute("BEGIN")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise


def q(sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
    with _lock:
        return list(conn().execute(sql, params).fetchall())


def q1(sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
    with _lock:
        return conn().execute(sql, params).fetchone()


def ex(sql: str, params: tuple | list = ()) -> int:
    """Execute a write; returns lastrowid."""
    with _lock:
        cur = conn().execute(sql, params)
        return int(cur.lastrowid or 0)


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def loads(v: str | None, default: Any = None) -> Any:
    if v is None or v == "":
        return default
    return json.loads(v)


# ---------- settings ----------
def get_setting(key: str, default: str | None = None) -> str | None:
    row = q1("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    ex("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
       (key, value))
