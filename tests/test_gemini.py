"""Tests for GeminiFormatter with offline fallback and prompt verification."""

from unittest.mock import MagicMock, patch
from just_talk.ai.gemini import GeminiFormatter


def test_gemini_missing_key_fallback():
    # If API key is None, it must return raw text with failure flag so speech is never lost
    with patch("just_talk.security.CredentialManager.get_api_key", return_value=None):
        formatter = GeminiFormatter(api_key=None)
        raw = "um, hey send me the report tomorrow"
        out, success, msg = formatter.format_text(raw)
        assert out == "Hey send me the report tomorrow."
        assert success is False
        assert "missing" in msg.lower()


def test_gemini_empty_input():
    formatter = GeminiFormatter(api_key="mock_key")
    out, success, msg = formatter.format_text("")
    assert out == ""
    assert success is True


def test_gemini_successful_mock():
    formatter = GeminiFormatter(api_key="mock_key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Can you send me the report tomorrow?"}]
                }
            }
        ]
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        out, success, msg = formatter.format_text("hey can you send me the report tomorrow")
        assert out == "Can you send me the report tomorrow?"
        assert success is True
