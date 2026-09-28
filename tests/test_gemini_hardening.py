"""Comprehensive tests for Gemini client hardening, circuit breaker, key redaction, and fallback."""

import time
from unittest.mock import MagicMock, patch
import pytest

from just_talk.ai.gemini import CircuitBreaker, ConnectionTestResult, GeminiFormatter
from just_talk.security import CredentialManager


def test_key_redaction():
    secret_key = "AIzaSyTestSecretKey123456789"
    raw_error = f"Error calling endpoint with key {secret_key}: Invalid key."
    redacted = CredentialManager.redact(raw_error)
    assert secret_key not in redacted
    assert "[REDACTED_API_KEY]" in redacted


def test_circuit_breaker_tripping_and_cooldown():
    fake_time = 1000.0

    def time_now():
        return fake_time

    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=300.0, time_func=time_now)
    assert breaker.is_paused is False

    # Failures 1 and 2
    assert breaker.record_failure() is False
    assert breaker.is_paused is False
    assert breaker.record_failure() is False
    assert breaker.is_paused is False

    # Failure 3: trips the circuit breaker
    tripped = breaker.record_failure()
    assert tripped is True
    assert breaker.is_paused is True
    assert breaker.remaining_cooldown_sec == 300

    # Advance time 100 seconds (still paused)
    fake_time += 100.0
    assert breaker.is_paused is True
    assert breaker.remaining_cooldown_sec == 200

    # Advance past 300 seconds
    fake_time += 201.0
    assert breaker.is_paused is False
    assert breaker.remaining_cooldown_sec == 0


def test_circuit_breaker_success_resets_failures():
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=300.0)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.consecutive_failures == 2
    breaker.record_success()
    assert breaker.consecutive_failures == 0


def test_test_connection_granular_errors():
    formatter = GeminiFormatter(api_key="mock_key")

    # 400 Bad Request
    mock_resp_400 = MagicMock(status_code=400, text='{"error": {"message": "API_KEY_INVALID"}}')
    with patch("httpx.Client.post", return_value=mock_resp_400):
        result = formatter.test_connection()
        assert result.success is False
        assert result.status_code == 400
        assert "Key not accepted" in result.message

    # 404 Not Found
    mock_resp_404 = MagicMock(status_code=404, text='{"error": {"message": "Model not found"}}')
    with patch("httpx.Client.post", return_value=mock_resp_404):
        result = formatter.test_connection(model="invalid-model")
        assert result.success is False
        assert "not found" in result.message

    # 429 Rate limit
    mock_resp_429 = MagicMock(status_code=429, text='{"error": {"message": "Resource exhausted"}}')
    with patch("httpx.Client.post", return_value=mock_resp_429):
        result = formatter.test_connection()
        assert result.success is False
        assert "Quota or rate limit" in result.message

    # 503 Server error
    mock_resp_503 = MagicMock(status_code=503, text='{"error": {"message": "Service unavailable"}}')
    with patch("httpx.Client.post", return_value=mock_resp_503):
        result = formatter.test_connection()
        assert result.success is False
        assert "Google's service is having trouble" in result.message


def test_format_text_fallback_preserves_content_with_cleanup():
    formatter = GeminiFormatter(api_key="mock_key", timeout=1.0)

    # Simulate network timeout
    with patch("httpx.Client.post", side_effect=Exception("Connection refused")):
        raw = "um uh we need to ship the update today"
        out, success, msg = formatter.format_text(raw)
        # Speech is never lost:
        assert success is False
        assert "Network error" in msg or "error" in msg.lower()
        # Light local cleanup applied:
        assert out == "We need to ship the update today."


def test_format_text_circuit_breaker_instant_fallback():
    fake_time = 1000.0

    def time_now():
        return fake_time

    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=300.0, time_func=time_now)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.is_paused is True

    formatter = GeminiFormatter(api_key="mock_key", circuit_breaker=breaker, time_func=time_now)

    # When breaker is open, format_text should not even make an HTTP call
    with patch("httpx.Client.post") as mock_post:
        out, success, msg = formatter.format_text("um test speech")
        assert mock_post.called is False
        assert success is False
        assert "paused" in msg
        assert out == "Test speech."
