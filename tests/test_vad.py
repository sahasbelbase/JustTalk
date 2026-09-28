"""Tests for Voice Activity Detector and silence filtering."""

import numpy as np
from just_talk.audio.vad import VoiceActivityDetector


def test_silence_detection():
    vad = VoiceActivityDetector(energy_threshold=0.01, min_speech_duration_sec=0.2)

    # Empty array
    assert vad.is_speech_present(np.array([], dtype=np.float32)) is False

    # Short tap (< 0.2s = 3200 samples at 16kHz)
    short_tap = np.ones(1000, dtype=np.float32) * 0.1
    assert vad.is_speech_present(short_tap, sample_rate=16000) is False

    # Ambient room noise / pure silence
    silence = np.random.normal(0, 0.001, 16000).astype(np.float32)
    assert vad.is_speech_present(silence, sample_rate=16000) is False

    # Real simulated speech signal
    speech = np.random.normal(0, 0.05, 16000).astype(np.float32)
    assert vad.is_speech_present(speech, sample_rate=16000) is True


def test_trim_silence():
    vad = VoiceActivityDetector()

    # Prepend and append 0.5s of silence around 0.5s of signal
    lead_silence = np.zeros(8000, dtype=np.float32)
    signal = np.ones(8000, dtype=np.float32) * 0.1
    trail_silence = np.zeros(8000, dtype=np.float32)

    full = np.concatenate([lead_silence, signal, trail_silence])
    trimmed = vad.trim_silence(full, threshold=0.05, pad_samples=500)

    assert len(trimmed) < len(full)
    assert len(trimmed) >= len(signal)
