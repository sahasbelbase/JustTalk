"""Tests for STT ModelManager and Whisper engine interfaces."""

from just_talk.stt.model_manager import ModelManager, TIERS


def test_model_manager_tiers():
    mm = ModelManager()
    fast_info = mm.get_tier_info("fast")
    assert fast_info.model_name == "base"
    assert fast_info.disk_size_mb > 0

    balanced_info = mm.get_tier_info("balanced")
    assert balanced_info.model_name == "small"

    quality_info = mm.get_tier_info("quality")
    assert quality_info.model_name == "large-v3-turbo"


def test_model_manager_paths():
    mm = ModelManager()
    p = mm.get_model_path("fast")
    assert "base" in str(p)
