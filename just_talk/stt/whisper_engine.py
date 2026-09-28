"""High-performance local Whisper speech-to-text inference engine."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from .engine import STTEngine
from .model_manager import ModelManager


class WhisperSTTEngine(STTEngine):
    """
    Local speech-to-text engine using faster-whisper (CTranslate2).
    Keeps the model resident in memory for low-latency transcription.
    """

    def __init__(self, model_manager: Optional[ModelManager] = None):
        self.model_manager = model_manager or ModelManager()
        self._model = None
        self._current_tier: Optional[str] = None
        self._lock = threading.Lock()

    def load(self, tier_id: str = "balanced") -> bool:
        """Load and warm up the selected model tier."""
        with self._lock:
            if self._model is not None and self._current_tier == tier_id:
                return True

            info = self.model_manager.get_tier_info(tier_id)
            model_path = self.model_manager.get_model_path(tier_id)
            model_target = str(model_path) if model_path.exists() else info.model_name

            try:
                from faster_whisper import WhisperModel

                # Select optimal compute type for current platform
                # On CPU, int8 utilizes AVX2/AVX-512/ARM NEON for 3x speedup and minimal RAM
                self._model = WhisperModel(
                    model_target,
                    device="auto",
                    compute_type="int8",
                    download_root=str(self.model_manager.models_dir),
                )
                self._current_tier = tier_id
                print(f"[STT] Loaded {info.display_name} successfully.")
                return True
            except Exception as e:
                print(f"[STT] Failed to load model {tier_id}: {e}", file=sys.stderr)
                return False

    def is_loaded(self) -> bool:
        with self._lock:
            return self._model is not None

    def transcribe(self, audio: np.ndarray, language: Optional[str] = "en") -> str:
        """
        Transcribe audio array to text.
        Args:
            audio: 1D float32 NumPy array at 16000 Hz.
            language: ISO 639-1 language code (e.g. "en", None for auto-detect).
        """
        if audio is None or len(audio) == 0:
            return ""

        with self._lock:
            if self._model is None:
                if not self.load("balanced"):
                    return ""

            try:
                # beam_size=1 (greedy search) provides real-time speed for dictation
                # vad_filter=True removes background noise/silence
                segments, info = self._model.transcribe(
                    audio,
                    beam_size=1,
                    language=language,
                    vad_filter=True,
                    condition_on_previous_text=False,
                )

                text_pieces = [segment.text.strip() for segment in segments]
                result = " ".join(t for t in text_pieces if t)
                return result
            except Exception as e:
                print(f"[STT] Transcription error: {e}", file=sys.stderr)
                return ""

    def unload(self) -> None:
        """Unload model from RAM."""
        with self._lock:
            self._model = None
            self._current_tier = None
