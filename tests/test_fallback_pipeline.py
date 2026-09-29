"""Tests for formatting fallback pipeline and log key redaction."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from just_talk.ai.gemini import GeminiFormatter
from just_talk.database.history import HistoryDatabase
from just_talk.security import CredentialManager


def test_fallback_light_local_cleanup():
    """Verify light local cleanup strips fillers and capitalizes."""
    raw = "um uh we need to submit the report today"
    cleaned = GeminiFormatter.light_local_cleanup(raw)
    assert cleaned == "We need to submit the report today."

    raw2 = "like ah this is ready"
    cleaned2 = GeminiFormatter.light_local_cleanup(raw2)
    assert cleaned2 == "This is ready."


def test_formatting_fallback_inserts_raw_and_saves_history():
    """When Gemini formatting fails, fallback text is used and history records 'inserted (offline)'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_history.db"
        db = HistoryDatabase(db_path=db_path)

        formatter = GeminiFormatter(api_key="mock_key", timeout=0.1)

        # Simulate Gemini connection failure
        with patch("httpx.Client.post", side_effect=Exception("API Error")):
            raw_speech = "um we should meet at five pm"
            cleaned, success, msg = formatter.format_text(raw_speech)

            assert success is False
            assert cleaned == "We should meet at five pm."
            # Verify status and history record
            status_to_save = "inserted (offline)"
            record = db.add(
                raw_transcription=raw_speech,
                processed_text=cleaned,
                action="dictation",
                application="Terminal",
                status=status_to_save,
                duration_ms=120,
            )

            # Ensure raw transcription was preserved unaltered in DB
            assert record.raw_transcription == raw_speech
            assert record.processed_text == "We should meet at five pm."
            assert record.status == "inserted (offline)"

            # Verify it's retrieved in recent items
            recent = db.get_recent(limit=1)
            assert len(recent) == 1
            assert recent[0].raw_transcription == raw_speech
            assert recent[0].status == "inserted (offline)"


def test_key_redaction_in_logs_and_errors():
    """Verify that credentials in exception messages or log strings are redacted."""
    gemini_key = "AQ.MockTestKey0123456789abcdefghij"
    google_key = "AIzaSyD-mockTestKey9876543210ABCDEFGH"

    log_entry_1 = f"Failed to post to https://generativelanguage.googleapis.com with key={gemini_key}"
    log_entry_2 = f"HTTP 401 Unauthorized for client key: {google_key} in request"

    redacted_1 = CredentialManager.redact(log_entry_1)
    redacted_2 = CredentialManager.redact(log_entry_2)

    assert gemini_key not in redacted_1
    assert "[REDACTED_API_KEY]" in redacted_1

    assert google_key not in redacted_2
    assert "[REDACTED_API_KEY]" in redacted_2
