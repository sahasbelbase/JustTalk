"""Tests for CredentialManager seamless private storage and key redaction."""

import os
from unittest.mock import patch
from just_talk.security import CredentialManager, DEFAULT_TESTED_KEY


def test_default_key_security():
    """Ensure no hardcoded API keys are bundled by default for security."""
    assert DEFAULT_TESTED_KEY is None


def test_set_and_get_key():
    """Test setting, getting, and deleting provider API keys."""
    mock_key = "AQ.MockSampleTestKey12345678901234567890"
    CredentialManager.set_provider_api_key("gemini", mock_key)
    assert CredentialManager.get_provider_api_key("gemini") == mock_key
    CredentialManager.delete_provider_api_key("gemini")


def test_redaction():
    """Ensure API keys are automatically scrubbed from logs."""
    mock_key = "AQ.MockSampleTestKey12345678901234567890"
    sample = f"Connecting with key {mock_key} failed"
    redacted = CredentialManager.redact(sample)
    assert "[REDACTED_API_KEY]" in redacted
    assert mock_key not in redacted


def test_mask_key():
    """Test safe UI masking of API keys."""
    assert CredentialManager.mask_key(None) == "Not Configured"
    assert CredentialManager.mask_key("") == "Not Configured"
    mock_key = "AQ.MockSampleTestKey12345678901234567890"
    masked = CredentialManager.mask_key(mock_key)
    assert masked.startswith("AQ.M")
    assert masked.endswith("7890")
    assert "••••" in masked
