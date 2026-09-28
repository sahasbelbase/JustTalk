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
    def transcribe(self, audio: np.ndarray, language: Optional[str] = "en") -> str:
        """
        Transcribe a 16kHz 1D float32 audio array into raw text.
        Returns the transcribed text or an empty string on silence/error.
        """
        pass

    @abstractmethod
    def unload(self) -> None:
        """Free model resources from memory."""
        pass
