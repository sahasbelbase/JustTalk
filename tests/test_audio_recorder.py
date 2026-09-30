"""Unit tests for AudioRecorder input validation, multi-rate handling, and AGC."""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock
from just_talk.audio.recorder import AudioRecorder, AudioDeviceInfo


def test_get_input_devices_filters_phantoms_and_invalids():
    mock_devices = [
        {"name": "Realtek Microphone", "max_input_channels": 2, "default_samplerate": 48000.0, "hostapi": 0},
        {"name": "Stereo Mix (Realtek)", "max_input_channels": 2, "default_samplerate": 48000.0, "hostapi": 0},
        {"name": "Disconnected USB Mic", "max_input_channels": 1, "default_samplerate": 44100.0, "hostapi": 0},
        {"name": "Speakers (Realtek)", "max_input_channels": 0, "default_samplerate": 48000.0, "hostapi": 0},
    ]

    def mock_check_settings(device=None):
        if device == 2:  # Disconnected USB Mic
            raise Exception("Device unavailable")

    with patch("sounddevice.query_devices", return_value=mock_devices), \
         patch("sounddevice.default", MagicMock(device=[0, 1])), \
         patch("sounddevice.query_hostapis", return_value=[{"name": "MME"}]), \
         patch("sounddevice.check_input_settings", side_effect=mock_check_settings):

        devs = AudioRecorder.get_input_devices()
        names = [d.name for d in devs]

        assert "Realtek Microphone" in names
        assert "Stereo Mix (Realtek)" not in names
        assert "Disconnected USB Mic" not in names
        assert "Speakers (Realtek)" not in names


def test_audio_recorder_soft_speech_agc():
    rec = AudioRecorder()
    rec._actual_sample_rate = 16000

    # Simulate recorded frames with soft speech (peak = 0.05)
    soft_frame = np.ones(1600, dtype=np.float32) * 0.05
    rec._frames = [soft_frame]
    rec._is_recording = True

    with patch.object(rec, "_stream", None):
        result = rec.stop()

    assert result is not None
    boosted_peak = float(np.max(np.abs(result)))
    # AGC should have boosted it above the initial 0.05
    assert boosted_peak > 0.05
    assert boosted_peak <= 1.0
