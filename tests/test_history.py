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


def test_voice_profiles_crud():
    import numpy as np

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_profiles.db"
        db = HistoryDatabase(db_path=db_path)

        dummy_emb = np.random.randn(512).astype(np.float32)
        pid = db.save_voice_profile("Speaker 1", dummy_emb)
        assert pid is not None

        profiles = db.get_voice_profiles()
        assert "Speaker 1" in profiles
        assert np.allclose(profiles["Speaker 1"], dummy_emb, atol=1e-5)

        listing = db.list_voice_profiles()
        assert len(listing) == 1
        assert listing[0]["name"] == "Speaker 1"

        # Test adding history with speaker attribution
        item = db.add(
            raw_transcription="testing speaker tagging",
            processed_text="Testing speaker tagging.",
            speaker="Speaker 1",
        )
        assert item.speaker == "Speaker 1"
        recent = db.get_recent(limit=1)
        assert recent[0].speaker == "Speaker 1"

        # Delete profile
        deleted = db.delete_voice_profile("Speaker 1")
        assert deleted is True
        assert len(db.get_voice_profiles()) == 0
