"""SQLite helpers. Connection-per-request via contextmanager.

WAL + foreign_keys ON. No ORM. Schema initialised at startup.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_DB_PATH: Path | None = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  mac         TEXT NOT NULL,
  hostname    TEXT NOT NULL,
  last_ip     TEXT,
  token       TEXT NOT NULL UNIQUE,
  first_seen  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(mac, hostname)
);
CREATE INDEX IF NOT EXISTS idx_devices_token ON devices(token);

CREATE TABLE IF NOT EXISTS commands (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id         INTEGER NOT NULL REFERENCES devices(id),
  name              TEXT NOT NULL,
  payload           TEXT NOT NULL DEFAULT '',
  status            TEXT NOT NULL DEFAULT 'pending',
  output            TEXT NOT NULL DEFAULT '',
  input_file_path   TEXT,
  output_file_path  TEXT,
  created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  taken_at          TIMESTAMP,
  completed_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_commands_device_status ON commands(device_id, status);
CREATE INDEX IF NOT EXISTS idx_commands_device_created ON commands(device_id, created_at DESC);

CREATE TABLE IF NOT EXISTS uploads (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  filename        TEXT NOT NULL,
  stored_path     TEXT NOT NULL UNIQUE,
  size_bytes      INTEGER NOT NULL,
  uploaded_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def configure(db_path: Path) -> None:
    global _DB_PATH
    _DB_PATH = db_path


def _connect() -> sqlite3.Connection:
    if _DB_PATH is None:
        raise RuntimeError("db.configure() must be called before _connect()")
    conn = sqlite3.connect(
        str(_DB_PATH),
        detect_types=sqlite3.PARSE_DECLTYPES,
        isolation_level=None,  # manual transaction control
        check_same_thread=False,
        timeout=30.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(mode: str = "DEFERRED") -> Iterator[sqlite3.Connection]:
    """Open connection and run inside an explicit transaction.

    mode: DEFERRED | IMMEDIATE | EXCLUSIVE
    """
    conn = _connect()
    try:
        conn.execute(f"BEGIN {mode}")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def init_schema() -> None:
    with get_conn() as c:
        c.executescript(SCHEMA)
