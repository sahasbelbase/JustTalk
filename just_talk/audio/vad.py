"""Fast Voice Activity Detection (VAD) and silence filtering."""

from __future__ import annotations

import numpy as np


class VoiceActivityDetector:
    """Lightweight energy-based VAD to filter out background silence and accidental taps."""

    def __init__(self, energy_threshold: float = 0.005, min_speech_duration_sec: float = 0.25):
        self.energy_threshold = energy_threshold
        self.min_speech_duration_sec = min_speech_duration_sec

    @staticmethod
    def calculate_rms(audio: np.ndarray) -> float:
        """Compute Root Mean Square (RMS) energy of an audio frame."""
        if audio.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(audio))))

    def is_speech_present(self, audio: np.ndarray, sample_rate: int = 16000) -> bool:
        """
        Determine whether the audio contains meaningful human speech
        or is just ambient room silence / an accidental key tap.
        """
        if audio.size == 0:
            return False

        duration = len(audio) / sample_rate
        if duration < self.min_speech_duration_sec:
            return False

        rms = self.calculate_rms(audio)
        return rms >= self.energy_threshold

    @staticmethod
    def trim_silence(audio: np.ndarray, threshold: float = 0.008, pad_samples: int = 1600) -> np.ndarray:
        """
        Trim leading and trailing silence from speech while keeping a small padding buffer.
        """
        if audio.size == 0:
            return audio

        abs_audio = np.abs(audio)
        indices = np.where(abs_audio > threshold)[0]
        if indices.size == 0:
            return audio

        start = max(0, indices[0] - pad_samples)
        end = min(len(audio), indices[-1] + pad_samples)
        return audio[start:end]
