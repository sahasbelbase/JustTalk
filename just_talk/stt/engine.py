"""Abstract base class for speech-to-text inference engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np


class STTEngine(ABC):
    """Abstract interface for local speech-to-text engines."""

    @abstractmethod
    def load(self, model_identifier: str) -> bool:
        """Initialize and warm up the model."""
        pass

    @abstractmethod
    def is_loaded(self) -> bool:
        """Check if model is currently resident in memory and ready."""
        pass

    @abstractmethod
    def transcribe(
        self,
        audio: np.ndarray,
        language: Optional[str] = None,
        task: str = "transcribe",
        initial_prompt: Optional[str] = None,
    ) -> str:
        """
        Transcribe or translate a 16kHz 1D float32 audio array into raw text.
        Args:
            audio: 16kHz float32 audio samples.
            language: ISO-639-1 code (e.g. "ne", "en", "de") or None for auto-detect.
            task: "transcribe" (speech to text in spoken language) or "translate" (speech to English).
            initial_prompt: Optional context or vocabulary prompt to bias acoustic decoding.
        Returns the transcribed/translated text or an empty string on silence/error.
        """
        pass

    @abstractmethod
    def unload(self) -> None:
        """Free model resources from memory."""
        pass
