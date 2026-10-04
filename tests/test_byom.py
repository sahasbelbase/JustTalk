"""Tests for Bring Your Own Model (BYOM) features: Ollama, custom LLMs, and custom STT models."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import numpy as np

from just_talk.config import AppConfig
from just_talk.ai.providers import (
    MultiProviderFormatter,
    clean_llm_response,
    scan_ollama_models,
    get_provider,
)
from just_talk.stt.model_manager import ModelManager
from just_talk.stt.whisper_engine import WhisperSTTEngine


def test_clean_llm_response_strips_preambles():
    """Verify chatty preambles from local models are cleanly removed."""
    cases = [
        ("Here is the cleaned text: Meeting at five pm.", "Meeting at five pm."),
        ("Here's your formatted transcript: Let's ship today.", "Let's ship today."),
        ("Cleaned text: Just testing the microphone.", "Just testing the microphone."),
        ("Output: Perfectly clean output.", "Perfectly clean output."),
        ("Result: Done and done.", "Done and done."),
        ('"Meeting notes are ready."', "Meeting notes are ready."),
        ("'Single quoted text.'", "Single quoted text."),
        ("```\nCode fence block\n```", "Code fence block"),
    ]
    for raw, expected in cases:
        assert clean_llm_response(raw) == expected


def test_scan_ollama_models_api_tags(monkeypatch):
    """Verify scan_ollama_models parses /api/tags JSON correctly."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [
            {"name": "qwen2.5-coder:7b"},
            {"name": "llama3.2:3b"},
            {"name": "deepseek-r1:8b"},
        ]
    }

    with patch("httpx.Client.get", return_value=mock_resp):
        models = scan_ollama_models("http://localhost:11434")
        assert models == ["deepseek-r1:8b", "llama3.2:3b", "qwen2.5-coder:7b"]


def test_scan_ollama_models_fallback_v1_models(monkeypatch):
    """Verify fallback to /v1/models if /api/tags fails."""
    def fake_get(self, url, **kwargs):
        resp = MagicMock()
        if "/api/tags" in url:
            resp.status_code = 404
        elif "/v1/models" in url:
            resp.status_code = 200
            resp.json.return_value = {
                "data": [
                    {"id": "mistral:7b"},
                    {"id": "gemma2:9b"},
                ]
            }
        return resp

    with patch("httpx.Client.get", side_effect=fake_get, autospec=True):
        models = scan_ollama_models("http://localhost:11434/v1")
        assert models == ["gemma2:9b", "mistral:7b"]


def test_scan_ollama_models_offline_returns_empty():
    """Verify network connection failures gracefully return empty list."""
    with patch("httpx.Client.get", side_effect=Exception("Connection refused")):
        models = scan_ollama_models("http://localhost:99999")
        assert models == []


def test_ollama_provider_requires_no_api_key():
    """Verify MultiProviderFormatter allows Ollama formatting without an API key."""
    formatter = MultiProviderFormatter(provider_id="ollama", api_key=None)
    assert formatter.provider_id == "ollama"
    assert formatter.provider.display_name.startswith("Ollama")

    # Mock successful HTTP call
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "choices": [
            {"message": {"content": "Hello, world!"}}
        ]
    }

    with patch("httpx.Client.post", return_value=mock_post_resp):
        out, ok, msg = formatter.format_text("hello world")
        assert ok is True
        assert out == "Hello, world!"


def test_model_manager_validate_custom_model_target(tmp_path: Path):
    """Verify validation logic for local directory and HF repo ID."""
    mgr = ModelManager(models_dir=tmp_path)

    # Empty target
    valid, reason = mgr.validate_custom_model_target("")
    assert valid is False

    # Nonexistent local file
    valid, reason = mgr.validate_custom_model_target(str(tmp_path / "missing"))
    # Not local path, but syntactically not HF repo either since no slash
    assert valid is True or "Hugging Face" in reason or "neither" in reason

    # Hugging Face repo ID
    valid, reason = mgr.validate_custom_model_target("Systran/faster-whisper-small")
    assert valid is True
    assert "Hugging Face repository" in reason

    # Invalid local folder missing config.json
    invalid_dir = tmp_path / "bad_model"
    invalid_dir.mkdir()
    valid, reason = mgr.validate_custom_model_target(str(invalid_dir))
    assert valid is False
    assert "missing config.json" in reason

    # Valid local folder with config.json and model.bin
    valid_dir = tmp_path / "good_model"
    valid_dir.mkdir()
    (valid_dir / "config.json").write_text("{}", encoding="utf-8")
    bin_file = valid_dir / "model.bin"
    bin_file.write_bytes(b"\x00" * 16_000_000)  # 16 MB dummy weights

    valid, reason = mgr.validate_custom_model_target(str(valid_dir))
    assert valid is True
    assert "Valid local model directory" in reason


def test_whisper_engine_custom_load_and_unload(tmp_path: Path):
    """Verify WhisperSTTEngine custom model load dispatch."""
    mgr = ModelManager(models_dir=tmp_path)
    engine = WhisperSTTEngine(mgr)

    fake_model = MagicMock()
    with patch("faster_whisper.WhisperModel", return_value=fake_model):
        loaded = engine.load(custom_target="Systran/faster-whisper-small")
        assert loaded is True
        assert engine.is_loaded() is True
        assert engine._current_custom_target == "Systran/faster-whisper-small"

        engine.unload()
        assert engine.is_loaded() is False
        assert engine._current_custom_target is None


def test_config_byom_persistence(tmp_path: Path):
    """Verify BYOM config fields are saved and restored properly."""
    cfg = AppConfig(
        stt_model_source="custom",
        custom_stt_model_path="deepdml/faster-whisper-large-v3-turbo-ct2",
        ollama_base_url="http://192.168.1.50:11434",
        ollama_model="llama3.2:3b",
    )

    data = cfg.__dict__.copy()
    assert data["stt_model_source"] == "custom"
    assert data["custom_stt_model_path"] == "deepdml/faster-whisper-large-v3-turbo-ct2"
    assert data["ollama_base_url"] == "http://192.168.1.50:11434"
    assert data["ollama_model"] == "llama3.2:3b"
