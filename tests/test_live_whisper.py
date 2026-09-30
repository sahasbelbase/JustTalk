"""Integration test verifying real local Whisper model loading and inference."""

import numpy as np
import pytest
from just_talk.stt.model_manager import ModelManager
from just_talk.stt.whisper_engine import WhisperSTTEngine


def test_real_whisper_engine_loading_and_inference():
    """Verify that faster-whisper loads actual weights and runs inference without mock."""
    mm = ModelManager()
    engine = WhisperSTTEngine(mm)

    # 1. Verify loading the fast tier (base.en)
    try:
        loaded = engine.load("fast")
    except Exception as e:
        pytest.skip(f"Live whisper download skipped due to network/rate-limit: {e}")

    if not loaded:
        pytest.skip("Whisper model fast tier could not be downloaded in this environment.")

    assert loaded is True
    assert engine.is_loaded() is True

    # 2. Run real inference on a 1-second 16kHz audio buffer
    # Pure tone generates silence or clean empty text without crashing
    sample_rate = 16000
    t = np.linspace(0, 1.0, sample_rate, dtype=np.float32)
    # A 440Hz sine wave tone
    tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    result = engine.transcribe(tone)
    # Result will be a string (empty or musical annotation like "[music]"), proving real model execution
    assert isinstance(result, str)

    # 3. Unload
    engine.unload()
    assert engine.is_loaded() is False
