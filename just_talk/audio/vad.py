"""Fast Voice Activity Detection (VAD) and silence filtering."""

from __future__ import annotations

import numpy as np


class VoiceActivityDetector:
    """Lightweight energy-based VAD to filter out background silence and accidental taps."""

    def __init__(self, energy_threshold: float = 0.0003, min_speech_duration_sec: float = 0.1):
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

        # Peak absolute amplitude check: only reject true flatline / zero-filled buffer
        peak_amp = float(np.max(np.abs(audio)))
        if peak_amp < 0.0003:
            return False

        # Global RMS check
        rms = self.calculate_rms(audio)
        if rms >= self.energy_threshold:
            return True

        # Sliding window check: detects speech even if diluted by pauses/silence
        chunk_size = int(sample_rate * 0.1)  # 100ms
        if len(audio) >= chunk_size:
            hop = chunk_size // 2
            for i in range(0, len(audio) - chunk_size + 1, hop):
                chunk_rms = self.calculate_rms(audio[i : i + chunk_size])
                if chunk_rms >= self.energy_threshold:
                    return True

        return peak_amp >= max(0.004, self.energy_threshold * 2)

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
