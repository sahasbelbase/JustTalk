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

    max_info = mm.get_tier_info("max")
    assert max_info.model_name == "large-v3"

    # Default fallback should be quality (large-v3-turbo)
    default_info = mm.get_tier_info("nonexistent_tier")
    assert default_info.model_name == "large-v3-turbo"


def test_model_manager_paths():
    mm = ModelManager()
    p = mm.get_model_path("fast")
    assert "base" in str(p)


def test_whisper_engine_transcribe_initial_prompt():
    from unittest.mock import MagicMock
    import numpy as np
    from just_talk.stt.whisper_engine import WhisperSTTEngine

    engine = WhisperSTTEngine()
    mock_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = "JustTalk is running"
    mock_model.transcribe.return_value = ([mock_segment], None)
    engine._model = mock_model

    fake_audio = np.ones(16000, dtype=np.float32) * 0.05
    res = engine.transcribe(fake_audio, initial_prompt="Custom vocabulary: JustTalk")

    assert res == "JustTalk is running"
    # Ensure initial_prompt was passed to faster-whisper transcribe
    mock_model.transcribe.assert_called()
    call_kwargs = mock_model.transcribe.call_args[1]
    assert call_kwargs.get("initial_prompt") == "Custom vocabulary: JustTalk"
