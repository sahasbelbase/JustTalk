"""Unit tests for Phase 1 zero-login STT engines (GoogleWebSTTEngine, MacNativeSTTEngine, WindowsNativeSTTEngine)."""

import sys
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from just_talk.stt.google_web_engine import GoogleWebSTTEngine
from just_talk.stt.mac_native_engine import MacNativeSTTEngine
from just_talk.stt.windows_native_engine import WindowsNativeSTTEngine
from just_talk.stt import get_native_stt_engine, STTEngine


def test_google_web_engine_initialization_and_load():
    engine = GoogleWebSTTEngine()
    assert not engine.is_loaded()
    assert engine.load() is True
    assert engine.is_loaded() is True
    engine.unload()
    assert engine.is_loaded() is False


def test_google_web_engine_language_mapping():
    engine = GoogleWebSTTEngine()
    assert engine.map_language("en") == "en-US"
    assert engine.map_language("ne") == "ne-NP"
    assert engine.map_language("ne_en") == "ne-NP"
    assert engine.map_language("hi") == "hi-IN"
    assert engine.map_language("es") == "es-ES"
    assert engine.map_language(None) == "en-US"
    assert engine.map_language("auto") == "en-US"
    assert engine.map_language("en-GB") == "en-GB"


def test_google_web_engine_transcribe_empty_audio():
    engine = GoogleWebSTTEngine()
    assert engine.transcribe(np.array([], dtype=np.float32)) == ""
    assert engine.transcribe(None) == ""


def test_google_web_engine_transcribe_success():
    engine = GoogleWebSTTEngine()
    engine.load()

    mock_rec = MagicMock()
    mock_rec.recognize_google.return_value = "नमस्ते म साहश हुँ"
    engine._recognizer = mock_rec

    dummy_audio = np.zeros(16000, dtype=np.float32)
    res = engine.transcribe(dummy_audio, language="ne")
    assert res == "नमस्ते म साहश हुँ"
    mock_rec.recognize_google.assert_called_once()
    assert mock_rec.recognize_google.call_args[1]["language"] == "ne-NP"


def test_google_web_engine_graceful_error_handling():
    import speech_recognition as sr
    engine = GoogleWebSTTEngine()
    engine.load()

    # Test UnknownValueError (silence/unintelligible)
    mock_rec = MagicMock()
    mock_rec.recognize_google.side_effect = sr.UnknownValueError()
    engine._recognizer = mock_rec

    dummy_audio = np.zeros(16000, dtype=np.float32)
    assert engine.transcribe(dummy_audio, language="en") == ""

    # Test RequestError (network error/timeout)
    mock_rec.recognize_google.side_effect = sr.RequestError("Network timeout")
    assert engine.transcribe(dummy_audio, language="en") == ""


def test_mac_native_engine_initialization():
    engine = MacNativeSTTEngine()
    assert engine.load() is True
    assert engine.is_loaded() is True
    engine.unload()
    assert engine.is_loaded() is False


def test_mac_native_engine_nepali_routes_to_fallback():
    mock_fallback = MagicMock(spec=STTEngine)
    mock_fallback.transcribe.return_value = "नमस्ते काठमाडौं"

    engine = MacNativeSTTEngine(fallback_engine=mock_fallback)
    engine.load()

    dummy_audio = np.zeros(16000, dtype=np.float32)
    # Nepali is not supported by Apple SFSpeechRecognizer -> must delegate to Google Web fallback
    res = engine.transcribe(dummy_audio, language="ne")
    assert res == "नमस्ते काठमाडौं"
    mock_fallback.transcribe.assert_called_once_with(
        dummy_audio, language="ne", task="transcribe", initial_prompt=None
    )


def test_windows_native_engine_fallback():
    mock_fallback = MagicMock(spec=STTEngine)
    mock_fallback.transcribe.return_value = "Fallback transcription"

    engine = WindowsNativeSTTEngine(fallback_engine=mock_fallback)
    engine.load()

    dummy_audio = np.zeros(16000, dtype=np.float32)
    # On macOS or when Windows speech is unavailable, falls back
    res = engine.transcribe(dummy_audio, language="en")
    assert res == "Fallback transcription"
    mock_fallback.transcribe.assert_called_once()


def test_get_native_stt_engine_factory():
    engine = get_native_stt_engine()
    assert isinstance(engine, STTEngine)
    if sys.platform == "darwin":
        assert isinstance(engine, MacNativeSTTEngine)
    elif sys.platform == "win32":
        assert isinstance(engine, WindowsNativeSTTEngine)
