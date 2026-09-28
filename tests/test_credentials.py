"""Tests for CredentialManager seamless private storage and key redaction."""

import os
from unittest.mock import patch
from just_talk.security import CredentialManager, DEFAULT_TESTED_KEY


def test_default_key_presence():
    """Ensure pre-configured key is present so users are never asked on startup."""
    assert DEFAULT_TESTED_KEY is not None
    assert len(DEFAULT_TESTED_KEY) > 20
    key = CredentialManager.get_api_key()
    assert key is not None


def test_redaction():
    """Ensure API keys are automatically scrubbed from logs."""
    sample = "Connecting with key AQ.Ab8RN6KoTB0_kqgjTQ6QXopwIdKzVVBCKFNEME64eBDz9n3ypw failed"
    redacted = CredentialManager.redact(sample)
    assert "[REDACTED_API_KEY]" in redacted
    assert "AQ.Ab8RN6KoTB0" not in redacted


def test_mask_key():
    """Test safe UI masking of API keys."""
    assert CredentialManager.mask_key(None) == "Not Configured"
    assert CredentialManager.mask_key("") == "Not Configured"
    masked = CredentialManager.mask_key("AQ.Ab8RN6KoTB0_kqgjTQ6QXopwIdKzVVBCKFNEME64eBDz9n3ypw")
    assert masked.startswith("AQ.A")
    assert masked.endswith("ypw")
    assert "••••" in masked
