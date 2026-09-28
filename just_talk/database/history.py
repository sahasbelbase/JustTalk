"""Local SQLite database manager for generation history with auto-retention."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from ..config import get_app_data_dir


@dataclass
class HistoryItem:
    """Represents a single dictation history record."""

    id: str
    timestamp: str  # ISO 8601 string
    action: str  # "format", "translate", "rewrite", "raw", "action"
    raw_transcription: str
    processed_text: str
    application: str
    status: str  # "inserted", "clipboard", "failed"
    duration_ms: int = 0

    @property
    def formatted_time(self) -> str:
        """Display-friendly time format (e.g. 'Today, 20:31' or 'Sep 28, 14:15')."""
        try:
            dt = datetime.fromisoformat(self.timestamp)
            now = datetime.now(timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            local_dt = dt.astimezone()
            local_now = now.astimezone()

            if local_dt.date() == local_now.date():
                return f"Today, {local_dt.strftime('%H:%M')}"
            elif local_dt.date() == (local_now - timedelta(days=1)).date():
                return f"Yesterday, {local_dt.strftime('%H:%M')}"
            return local_dt.strftime("%b %d, %H:%M")
        except Exception:
            return self.timestamp[:16]


class HistoryDatabase:
    """Manages the local SQLite database for voice generations."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            self.db_path = get_app_data_dir() / "history.db"
        else:
            self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    raw_transcription TEXT NOT NULL,
                    processed_text TEXT NOT NULL,
                    application TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_ms INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_history_timestamp 
                ON history (timestamp DESC)
                """
            )
            conn.commit()

    def add(
        self,
        raw_transcription: str,
        processed_text: str,
        action: str = "format",
        application: str = "Unknown",
        status: str = "inserted",
        duration_ms: int = 0,
    ) -> HistoryItem:
        """Insert a new history entry."""
        item_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        item = HistoryItem(
            id=item_id,
            timestamp=timestamp,
            action=action,
            raw_transcription=raw_transcription,
            processed_text=processed_text,
            application=application,
            status=status,
            duration_ms=duration_ms,
        )

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO history (id, timestamp, action, raw_transcription, processed_text, application, status, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.timestamp,
                    item.action,
                    item.raw_transcription,
                    item.processed_text,
                    item.application,
                    item.status,
                    item.duration_ms,
                ),
            )
            conn.commit()
        return item

    def get_recent(self, limit: int = 100) -> List[HistoryItem]:
        """Fetch the most recent history records ordered from newest to oldest."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, timestamp, action, raw_transcription, processed_text, application, status, duration_ms
                FROM history
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [
                HistoryItem(
                    id=row["id"],
                    timestamp=row["timestamp"],
                    action=row["action"],
                    raw_transcription=row["raw_transcription"],
                    processed_text=row["processed_text"],
                    application=row["application"],
                    status=row["status"],
                    duration_ms=row["duration_ms"],
                )
                for row in rows
            ]

    def search(self, query: str, limit: int = 50) -> List[HistoryItem]:
        """Search history records by raw transcription or processed text."""
        q = f"%{query}%"
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, timestamp, action, raw_transcription, processed_text, application, status, duration_ms
                FROM history
                WHERE raw_transcription LIKE ? OR processed_text LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (q, q, limit),
            )
            rows = cursor.fetchall()
            return [
                HistoryItem(
                    id=row["id"],
                    timestamp=row["timestamp"],
                    action=row["action"],
                    raw_transcription=row["raw_transcription"],
                    processed_text=row["processed_text"],
                    application=row["application"],
                    status=row["status"],
                    duration_ms=row["duration_ms"],
                )
                for row in rows
            ]

    def clear(self) -> None:
        """Manually clear all history records."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM history")
            conn.commit()

    def purge_expired(self, retention_days: int) -> int:
        """
        Delete records older than retention_days.
        If retention_days is 0, retention is unlimited (no purge).
        Returns number of purged records.
        """
        if retention_days <= 0:
            return 0

        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM history WHERE timestamp < ?", (cutoff,))
            deleted = cursor.rowcount
            conn.commit()
            return deleted
