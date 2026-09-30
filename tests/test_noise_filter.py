"""Unit tests for NoiseFilter."""

import numpy as np
from just_talk.audio.noise_filter import NoiseFilter


def test_noise_filter_highpass():
    """Verify that DC offset and sub-rumble are attenuated."""
    audio = np.ones(16000, dtype=np.float32)  # pure DC offset
    filtered = NoiseFilter._highpass_filter(audio, cutoff=80, sr=16000)
    assert np.mean(np.abs(filtered[1000:])) < 0.05


def test_noise_filter_preserves_speech():
    """Verify that signal length and non-empty characteristics are preserved."""
    # Synthetic speech-like sinusoid
    t = np.linspace(0, 1, 16000, endpoint=False)
    speech = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    
    nf = NoiseFilter()
    cleaned = nf.filter(speech)
    assert len(cleaned) == len(speech)
    assert np.max(np.abs(cleaned)) > 0.1
