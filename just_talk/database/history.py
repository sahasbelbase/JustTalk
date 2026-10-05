"""Local SQLite database manager for generation history with auto-retention."""

from __future__ import annotations

import numpy as np
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

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
    speaker: Optional[str] = None
    context: str = "text"       # "sql", "python", "javascript", "typescript", "java", "csharp", "go", "rust", "php", "text"
    word_count: int = 0         # Word count of processed_text
    duration_sec: float = 0.0   # Recording duration in seconds

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

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

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
                    duration_ms INTEGER DEFAULT 0,
                    speaker TEXT DEFAULT NULL
                )
                """
            )
            # Ensure speaker column exists in pre-existing databases
            try:
                conn.execute("ALTER TABLE history ADD COLUMN speaker TEXT DEFAULT NULL")
            except sqlite3.OperationalError:
                pass

            # Phase 3 migrations: context, word_count, duration_sec
            for col_def in [
                "context TEXT DEFAULT 'text'",
                "word_count INTEGER DEFAULT 0",
                "duration_sec REAL DEFAULT 0.0",
            ]:
                try:
                    conn.execute(f"ALTER TABLE history ADD COLUMN {col_def}")
                except sqlite3.OperationalError:
                    pass

            # Backfill word_count for existing rows where it is still 0 but processed_text is not empty
            conn.execute(
                """
                UPDATE history
                SET word_count = (
                    LENGTH(TRIM(processed_text))
                    - LENGTH(REPLACE(TRIM(processed_text), ' ', ''))
                    + 1
                )
                WHERE word_count = 0 AND TRIM(processed_text) != ''
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    embedding BLOB NOT NULL
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
        speaker: Optional[str] = None,
        context: str = "text",
        word_count: int = -1,
        duration_sec: float = 0.0,
    ) -> HistoryItem:
        """Insert a new history entry."""
        item_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        # Auto-compute word_count if not supplied
        if word_count < 0:
            text = (processed_text or "").strip()
            word_count = len(text.split()) if text else 0
        item = HistoryItem(
            id=item_id,
            timestamp=timestamp,
            action=action,
            raw_transcription=raw_transcription,
            processed_text=processed_text,
            application=application,
            status=status,
            duration_ms=duration_ms,
            speaker=speaker,
            context=context,
            word_count=word_count,
            duration_sec=duration_sec,
        )

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO history (id, timestamp, action, raw_transcription, processed_text,
                                     application, status, duration_ms, speaker,
                                     context, word_count, duration_sec)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id, item.timestamp, item.action,
                    item.raw_transcription, item.processed_text,
                    item.application, item.status, item.duration_ms, item.speaker,
                    item.context, item.word_count, item.duration_sec,
                ),
            )
            conn.commit()
        return item


    def _row_to_item(self, row: sqlite3.Row) -> HistoryItem:
        """Convert a sqlite3.Row to a HistoryItem, tolerating missing columns."""
        keys = row.keys()
        return HistoryItem(
            id=row["id"],
            timestamp=row["timestamp"],
            action=row["action"],
            raw_transcription=row["raw_transcription"],
            processed_text=row["processed_text"],
            application=row["application"],
            status=row["status"],
            duration_ms=row["duration_ms"] or 0,
            speaker=row["speaker"] if "speaker" in keys else None,
            context=row["context"] if "context" in keys else "text",
            word_count=row["word_count"] if "word_count" in keys else 0,
            duration_sec=row["duration_sec"] if "duration_sec" in keys else 0.0,
        )

    def get_recent(self, limit: int = 100) -> List[HistoryItem]:
        """Fetch the most recent history records ordered from newest to oldest."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, timestamp, action, raw_transcription, processed_text,
                       application, status, duration_ms, speaker,
                       context, word_count, duration_sec
                FROM history
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [self._row_to_item(row) for row in cursor.fetchall()]

    def get_by_date(self, date_str: str, limit: int = 500) -> List[HistoryItem]:
        """Fetch all history records for a given date (YYYY-MM-DD)."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, timestamp, action, raw_transcription, processed_text,
                       application, status, duration_ms, speaker,
                       context, word_count, duration_sec
                FROM history
                WHERE DATE(timestamp) = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (date_str, limit),
            )
            return [self._row_to_item(row) for row in cursor.fetchall()]

    def delete(self, item_id: str) -> bool:
        """Delete a single history entry by id. Returns True if a row was deleted."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM history WHERE id = ?", (item_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_daily_stats(self, days: int = 365) -> List[dict]:
        """
        Return per-day aggregates for the contribution graph.
        Each entry: {date, word_count, duration_min, top_app}
        Only returns days that have at least one record.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    DATE(timestamp) AS date,
                    SUM(word_count) AS total_words,
                    SUM(duration_sec) / 60.0 AS total_min,
                    application AS top_app
                FROM history
                WHERE timestamp >= DATE('now', ?)
                GROUP BY DATE(timestamp), application
                ORDER BY DATE(timestamp) DESC, total_words DESC
                """,
                (f"-{days} days",),
            )
            # Collapse multiple apps per day — keep the highest-word one
            by_date: dict[str, dict] = {}
            for row in cursor.fetchall():
                d = row["date"]
                if d not in by_date:
                    by_date[d] = {
                        "date": d,
                        "word_count": int(row["total_words"] or 0),
                        "duration_min": round(float(row["total_min"] or 0), 1),
                        "top_app": row["top_app"] or "Unknown",
                    }
                else:
                    # Accumulate words from other apps
                    by_date[d]["word_count"] += int(row["total_words"] or 0)
                    by_date[d]["duration_min"] += round(float(row["total_min"] or 0), 1)
            return sorted(by_date.values(), key=lambda x: x["date"])

    def get_stats_summary(self) -> dict:
        """
        Compute dashboard summary stats:
          total_words, today_words, streak_days
        """
        with self._get_connection() as conn:
            total_row = conn.execute("SELECT SUM(word_count) AS s FROM history").fetchone()
            total_words = int(total_row["s"] or 0)

            today_str = datetime.now().strftime("%Y-%m-%d")
            today_row = conn.execute(
                "SELECT SUM(word_count) AS s FROM history WHERE DATE(timestamp)=?",
                (today_str,),
            ).fetchone()
            today_words = int(today_row["s"] or 0)

            # Streak: count consecutive days backwards from today with at least 1 word
            streak = 0
            check_date = datetime.now().date()
            while True:
                ds = check_date.strftime("%Y-%m-%d")
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM history WHERE DATE(timestamp)=?", (ds,)
                ).fetchone()
                if row["c"] > 0:
                    streak += 1
                    check_date = (datetime.fromordinal(check_date.toordinal() - 1)).date()
                else:
                    break

        return {
            "total_words": total_words,
            "today_words": today_words,
            "streak_days": streak,
        }

    def search(self, query: str, limit: int = 50) -> List[HistoryItem]:
        """Search history records by raw transcription or processed text."""
        q = f"%{query}%"
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, timestamp, action, raw_transcription, processed_text,
                       application, status, duration_ms, speaker,
                       context, word_count, duration_sec
                FROM history
                WHERE raw_transcription LIKE ? OR processed_text LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (q, q, limit),
            )
            return [self._row_to_item(row) for row in cursor.fetchall()]


    def save_voice_profile(self, name: str, embedding: np.ndarray) -> str:
        """Save or update an enrolled speaker voice profile."""
        profile_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        blob = embedding.astype(np.float32).tobytes()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO voice_profiles (id, name, created_at, embedding)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    created_at = excluded.created_at,
                    embedding = excluded.embedding
                """,
                (profile_id, name.strip(), now, blob),
            )
            conn.commit()
        return profile_id

    def get_voice_profiles(self) -> Dict[str, np.ndarray]:
        """Load all enrolled speaker profiles as a mapping of name -> normalized embedding."""
        profiles = {}
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT name, embedding FROM voice_profiles ORDER BY created_at ASC")
            for row in cursor.fetchall():
                name = row["name"]
                blob = row["embedding"]
                if blob:
                    profiles[name] = np.frombuffer(blob, dtype=np.float32)
        return profiles

    def delete_voice_profile(self, name: str) -> bool:
        """Delete an enrolled voice profile by name."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM voice_profiles WHERE name = ?", (name.strip(),))
            conn.commit()
            return cur.rowcount > 0

    def list_voice_profiles(self) -> List[dict]:
        """List metadata for all enrolled voice profiles."""
        with self._get_connection() as conn:
            cur = conn.execute("SELECT id, name, created_at FROM voice_profiles ORDER BY created_at ASC")
            return [dict(row) for row in cur.fetchall()]

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
