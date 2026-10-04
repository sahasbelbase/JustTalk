"""Tests for application configuration and persistence."""

import tempfile
from pathlib import Path
from just_talk.config import AppConfig


def test_default_config():
    config = AppConfig()
    assert config.model_tier == "quality"
    assert config.language == "en"
    assert config.custom_vocabulary == ""
    assert config.gemini_enabled is True
    assert config.offline_mode is False
    assert config.history_retention_days == 30
    assert config.push_to_talk is True


def test_supported_languages():
    from just_talk.config import SUPPORTED_LANGUAGES
    codes = [code for _, code in SUPPORTED_LANGUAGES]
    assert "en" in codes
    assert "ne_en" in codes
    assert "ne" in codes
    assert "es" in codes
    assert "fr" in codes
    assert "de" in codes
    assert "zh" in codes
    assert "auto" in codes


def test_config_save_and_load(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "config.json"
        monkeypatch.setattr(AppConfig, "get_config_path", classmethod(lambda cls: tmp_path))

        config = AppConfig(
            model_tier="fast",
            history_retention_days=15,
            gemini_model="gemini-3.5-flash-lite",
        )
        config.save()
        assert tmp_path.exists()

        loaded = AppConfig.load()
        assert loaded.model_tier == "fast"
        assert loaded.history_retention_days == 15
        assert loaded.gemini_model == "gemini-3.5-flash-lite"
