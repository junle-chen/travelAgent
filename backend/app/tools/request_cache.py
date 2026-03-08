from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_DB_PATH = Path(__file__).resolve().parents[2] / "tool_cache.sqlite3"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_cache (
            namespace TEXT NOT NULL,
            cache_key TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY(namespace, cache_key)
        )
        """
    )
    return conn


def get_cached_json(namespace: str, cache_key: str, *, max_age_seconds: int) -> Any | None:
    now = int(time.time())
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT payload, updated_at FROM tool_cache WHERE namespace=? AND cache_key=?",
                (namespace, cache_key),
            ).fetchone()
            if not row:
                return None
            payload_text, updated_at = row
            if now - int(updated_at) > max_age_seconds:
                conn.execute(
                    "DELETE FROM tool_cache WHERE namespace=? AND cache_key=?",
                    (namespace, cache_key),
                )
                conn.commit()
                return None
            return json.loads(str(payload_text))
        finally:
            conn.close()


def set_cached_json(namespace: str, cache_key: str, payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    now = int(time.time())
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO tool_cache(namespace, cache_key, payload, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(namespace, cache_key)
                DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (namespace, cache_key, serialized, now),
            )
            conn.commit()
        finally:
            conn.close()
