"""Tests for SQLite history database with search and retention purge."""

import tempfile
from pathlib import Path
from just_talk.database.history import HistoryDatabase


def test_history_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_history.db"
        db = HistoryDatabase(db_path=db_path)

        # 1. Add records
        item1 = db.add(
            raw_transcription="hey can you send me the report",
            processed_text="Can you send me the report?",
            action="format",
            application="Slack",
            status="inserted",
            duration_ms=450,
        )
        assert item1.id is not None
        assert item1.action == "format"

        item2 = db.add(
            raw_transcription="translate this into Spanish hello friend",
            processed_text="Hola amigo",
            action="translate",
            application="Chrome",
            status="inserted",
            duration_ms=520,
        )

        # 2. Get recent
        recent = db.get_recent(limit=10)
        assert len(recent) == 2
        assert recent[0].id == item2.id  # Newest first

        # 3. Search
        search_res = db.search("Spanish")
        assert len(search_res) == 1
        assert search_res[0].id == item2.id

        # 4. Retention Purge (should keep recent records when retention is 30 days)
        deleted = db.purge_expired(retention_days=30)
        assert deleted == 0

        # 5. Clear
        db.clear()
        assert len(db.get_recent()) == 0
