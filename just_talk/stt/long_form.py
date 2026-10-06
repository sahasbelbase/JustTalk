"""Helpers that keep long dictations intact across pauses."""

from __future__ import annotations

import threading
from typing import Callable, Iterable

import numpy as np

from ..audio.vad import VoiceActivityDetector


def join_segments(parts: Iterable[str]) -> str:
    """Join transcript pieces with single spaces, skipping empties."""
    return " ".join(p.strip() for p in parts if p and p.strip())


class IncrementalTranscriber:
    """
    Live-partial helper that never forgets earlier speech.

    Only the most recent ``window_sec`` of audio is re-decoded on every poll (fast).
    Once the live tail grows past the window, the oldest part is cut at a natural
    pause, transcribed once, and cached, so the partial shown to the user is always
    ``committed text + live tail`` instead of only the last few seconds.
    """

    def __init__(
        self,
        transcribe_fn: Callable[..., str],
        window_sec: float = 8.0,
        sample_rate: int = 16000,
    ) -> None:
        self._transcribe_fn = transcribe_fn
        self._window = int(window_sec * sample_rate)
        self._sample_rate = sample_rate
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self._committed_samples = 0
        self._committed_parts: list = []

    def update(self, audio: np.ndarray, **kwargs) -> str:
        if audio is None or len(audio) == 0:
            return ""

        with self._lock:
            # A shorter buffer than what we've committed means a new recording started.
            if len(audio) < self._committed_samples:
                self.reset()

            tail = audio[self._committed_samples :]
            if len(tail) > self._window:
                cut = VoiceActivityDetector.find_pause_cut(
                    tail[: self._window], sample_rate=self._sample_rate
                )
                committed = self._transcribe_fn(tail[:cut], **kwargs)
                if committed and committed.strip():
                    self._committed_parts.append(committed.strip())
                self._committed_samples += cut
                tail = audio[self._committed_samples :]

            live = self._transcribe_fn(tail, **kwargs) if len(tail) else ""
            return join_segments([*self._committed_parts, live])
