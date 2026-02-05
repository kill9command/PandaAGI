"""
SQLite-backed session ledger for the shared-state backbone.

The ledger keeps an append-only record of key events so we can reconstruct the
conversation state, replay tool runs, and audit sourced answers.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    session_id: str
    turn_id: Optional[str]
    ticket_id: Optional[str]
    kind: str
    payload: Dict[str, Any]
    created_at: float


class SessionLedger:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._ensure_tables()

    # ------------------------------------------------------------------ #
    # Public API

    def log_event(
        self,
        *,
        session_id: str,
        kind: str,
        payload: Optional[Dict[str, Any]] = None,
        turn_id: Optional[str] = None,
        ticket_id: Optional[str] = None,
        event_id: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> LedgerEvent:
        """Append an event to the ledger and return the canonical record."""
        if not session_id:
            raise ValueError("session_id is required")
        if not kind:
            raise ValueError("event kind is required")
        event_id = event_id or uuid.uuid4().hex
        created_at = float(created_at if created_at is not None else time.time())
        blob = json.dumps(payload or {}, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO events (event_id, session_id, turn_id, ticket_id, kind, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, session_id, turn_id, ticket_id, kind, blob, created_at),
            )
            self._conn.commit()
        return LedgerEvent(event_id, session_id, turn_id, ticket_id, kind, payload or {}, created_at)

    def iter_events(
        self,
        *,
        session_id: Optional[str] = None,
        kind: Optional[str] = None,
        limit: Optional[int] = None,
        reverse: bool = False,
    ) -> Iterable[LedgerEvent]:
        """Yield events filtered by session/kind."""
        clauses = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "DESC" if reverse else "ASC"
        limit_sql = f"LIMIT {int(limit)}" if limit else ""
        query = f"""
            SELECT event_id, session_id, turn_id, ticket_id, kind, payload, created_at
            FROM events
            {where}
            ORDER BY created_at {order}
            {limit_sql}
        """
        cursor = self._conn.execute(query, params)
        rows = cursor.fetchall()
        for row in rows:
            payload = json.loads(row[5]) if row[5] else {}
            yield LedgerEvent(
                event_id=row[0],
                session_id=row[1],
                turn_id=row[2],
                ticket_id=row[3],
                kind=row[4],
                payload=payload,
                created_at=float(row[6]),
            )

    def latest_event(
        self,
        *,
        session_id: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> Optional[LedgerEvent]:
        """Return the most recent event matching the filters."""
        events = list(self.iter_events(session_id=session_id, kind=kind, limit=1, reverse=True))
        return events[0] if events else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ #
    # Internal helpers

    def _ensure_tables(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id TEXT,
                    ticket_id TEXT,
                    kind TEXT NOT NULL,
                    payload TEXT,
                    created_at REAL NOT NULL
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ticket ON events(ticket_id)")
            self._conn.commit()

