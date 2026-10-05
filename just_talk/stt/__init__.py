"""Speech-to-text inference engines and model management."""

from __future__ import annotations

import sys
from typing import Optional, TYPE_CHECKING

from .engine import STTEngine
from .google_web_engine import GoogleWebSTTEngine
from .mac_native_engine import MacNativeSTTEngine
from .model_manager import ModelManager, ModelTierInfo
from .nepali_conformer import NepaliConformerEngine
from .whisper_engine import WhisperSTTEngine
from .windows_native_engine import WindowsNativeSTTEngine

if TYPE_CHECKING:
    from ..config import AppConfig


def get_native_stt_engine() -> STTEngine:
    """Return the optimal zero-download OS-native engine with cloud fallback."""
    if sys.platform == "darwin":
        return MacNativeSTTEngine()
    elif sys.platform == "win32":
        return WindowsNativeSTTEngine()
    return GoogleWebSTTEngine()


def create_stt_engine_for_config(config: AppConfig, model_manager: Optional[ModelManager] = None) -> STTEngine:
    """
    Factory function that creates the appropriate STTEngine based on user configuration.
    Guarantees zero-download, instant startup for 'os_native' and 'google_web'.
    """
    provider = getattr(config, "stt_provider", "whisper") or "whisper"

    if provider == "google_web":
        return GoogleWebSTTEngine()
    elif provider == "os_native":
        return get_native_stt_engine()
    else:
        # Default: "whisper"
        return WhisperSTTEngine(model_manager or ModelManager())


__all__ = [
    "STTEngine",
    "ModelManager",
    "ModelTierInfo",
    "WhisperSTTEngine",
    "NepaliConformerEngine",
    "GoogleWebSTTEngine",
    "MacNativeSTTEngine",
    "WindowsNativeSTTEngine",
    "get_native_stt_engine",
    "create_stt_engine_for_config",
]
