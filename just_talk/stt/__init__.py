"""Local speech-to-text inference engines and model management."""

from .engine import STTEngine
from .model_manager import ModelManager, ModelTierInfo
from .nepali_conformer import NepaliConformerEngine
from .whisper_engine import WhisperSTTEngine

__all__ = [
    "STTEngine",
    "ModelManager",
    "ModelTierInfo",
    "WhisperSTTEngine",
    "NepaliConformerEngine",
]

