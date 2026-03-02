from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.schemas.domain import TripState


class Database:
    def __init__(self, settings: Settings) -> None:
        self.path = Path(settings.database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trips (
                    id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trip_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trip_id TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @contextmanager
    def connect(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def save_trip(self, trip: TripState, user_message: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        trip.updated_at = now
        payload = trip.model_dump_json()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trips (id, state_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (trip.trip_id, payload, trip.created_at, now),
            )
            conn.execute(
                "INSERT INTO trip_revisions (trip_id, user_message, state_json, created_at) VALUES (?, ?, ?, ?)",
                (trip.trip_id, user_message, payload, now),
            )
            conn.commit()

    def get_trip(self, trip_id: str) -> TripState | None:
        with self.connect() as conn:
            row = conn.execute("SELECT state_json FROM trips WHERE id = ?", (trip_id,)).fetchone()
        if row is None:
            return None
        return TripState.model_validate(json.loads(row["state_json"]))
