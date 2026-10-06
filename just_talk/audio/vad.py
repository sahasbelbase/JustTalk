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

    @staticmethod
    def find_pause_cut(
        audio: np.ndarray,
        sample_rate: int = 16000,
        min_offset_sec: float = 2.0,
        frame_sec: float = 0.03,
        pause_sec: float = 0.3,
    ) -> int:
        """
        Return the sample index at the centre of the quietest ~pause_sec region of
        ``audio`` (ignoring the first ``min_offset_sec``), i.e. the most natural place
        to cut between words. Returns len(audio) if the audio is too short to cut.
        """
        frame = max(1, int(sample_rate * frame_sec))
        n_frames = len(audio) // frame
        min_frame = int(min_offset_sec / frame_sec)
        if n_frames <= min_frame + 1:
            return len(audio)

        frames = audio[: n_frames * frame].reshape(n_frames, frame)
        frame_rms = np.sqrt(np.mean(np.square(frames), axis=1))
        win = max(1, int(pause_sec / frame_sec))
        if n_frames > win:
            frame_rms = np.convolve(frame_rms, np.ones(win) / win, mode="same")

        best = min_frame + int(np.argmin(frame_rms[min_frame:]))
        return min(len(audio), best * frame + frame // 2)

    @classmethod
    def split_on_pauses(
        cls,
        audio: np.ndarray,
        sample_rate: int = 16000,
        max_chunk_sec: float = 15.0,
        min_chunk_sec: float = 2.0,
        silence_peak: float = 0.002,
    ) -> list:
        """
        Split long dictation into chunks of at most ``max_chunk_sec``, cutting at the
        quietest moment (natural pauses) so no word is sliced in half. Near-silent
        chunks (long thinking pauses) are dropped from multi-chunk results.

        Streaming recognizers (Apple Speech, Google Web Speech) end the utterance on a
        long pause and drop or reset everything before it, so long recordings must be
        recognized chunk by chunk and stitched back together.
        """
        if audio is None or len(audio) == 0:
            return []

        max_samples = int(max_chunk_sec * sample_rate)
        chunks = []
        start = 0
        while len(audio) - start > max_samples:
            window = audio[start : start + max_samples]
            cut = cls.find_pause_cut(window, sample_rate=sample_rate, min_offset_sec=min_chunk_sec)
            chunks.append(window[:cut])
            start += cut
        chunks.append(audio[start:])
        if len(chunks) == 1:
            return chunks

        return [c for c in chunks if len(c) and float(np.max(np.abs(c))) >= silence_peak]
