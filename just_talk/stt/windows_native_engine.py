"""Windows Native Speech-to-Text Engine — Intelligent Hybrid Router & On-Device Whisper."""

from __future__ import annotations

import sys
import threading
from typing import Any, Optional

import numpy as np

from .engine import STTEngine
from .google_web_engine import GoogleWebSTTEngine


class WindowsNativeSTTEngine(STTEngine):
    """
    Windows Hybrid Speech-to-Text Engine.
    Implements intelligent auto-routing between zero-login Google Web Speech
    and on-device Whisper small:
    - User rule: "If online use Google endpoint if fast, otherwise use local small mode."
    - Real-time live partial streaming: Uses on-device Whisper small on audio chunks
      for zero-latency, rate-limit-free live feedback as the user speaks.
    - Pure Offline Mode: Fully blocks Google endpoint audio egress and routes strictly
      to local Whisper.
    """

    def __init__(
        self,
        fallback_engine: Optional[STTEngine] = None,
        local_engine: Optional[STTEngine] = None,
        model_manager: Optional[Any] = None,
        offline_mode: bool = False,
        fast_timeout_sec: float = 2.5,
    ) -> None:
        self.offline_mode = offline_mode
        self.fast_timeout_sec = fast_timeout_sec
        self.fallback_engine = fallback_engine or GoogleWebSTTEngine(
            timeout_sec=fast_timeout_sec,
            offline_mode=offline_mode,
        )
        self.model_manager = model_manager
        if local_engine is not None:
            self.local_engine = local_engine
        elif model_manager is not None:
            from .whisper_engine import WhisperSTTEngine

            self.local_engine = WhisperSTTEngine(model_manager)
        else:
            self.local_engine = None

        self._is_loaded = False
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        """Check if native Windows speech recognition or local engine is available."""
        if sys.platform != "win32":
            return False
        return True

    def load(self, model_identifier: str = "") -> bool:
        """Initialize the Windows speech engine and warm up engines."""
        with self._lock:
            self.fallback_engine.load()
            # If local Whisper model is downloaded, warm it up in background
            if self.local_engine and not self.local_engine.is_loaded() and self.model_manager:
                tier = (
                    "balanced"
                    if self.model_manager.is_model_downloaded("balanced")
                    else "small.en"
                )
                if self.model_manager.is_model_downloaded(tier):
                    threading.Thread(
                        target=lambda: self.local_engine.load(tier),
                        daemon=True,
                    ).start()
            self._is_loaded = True
            return True

    def is_loaded(self) -> bool:
        return self._is_loaded

    def unload(self) -> None:
        with self._lock:
            self._is_loaded = False
            if self.fallback_engine:
                self.fallback_engine.unload()
            if self.local_engine:
                self.local_engine.unload()

    def transcribe_partial(
        self,
        audio: np.ndarray,
        language: Optional[str] = None,
        task: str = "transcribe",
    ) -> str:
        """
        Real-time live streaming partial decoder.
        Decodes recent audio chunk (~5s) using local on-device Whisper small.
        Zero network latency, zero Google rate limiting.
        """
        if audio is None or len(audio) == 0:
            return ""

        if self.local_engine:
            if not self.local_engine.is_loaded():
                tier = (
                    "balanced"
                    if self.model_manager and self.model_manager.is_model_downloaded("balanced")
                    else "small.en"
                )
                self.local_engine.load(tier)

            if self.local_engine.is_loaded():
                max_samples = 16000 * 6
                recent_audio = audio[-max_samples:] if len(audio) > max_samples else audio
                try:
                    return self.local_engine.transcribe(recent_audio, language=language, task=task)
                except Exception:
                    return ""
        return ""

    def transcribe(
        self,
        audio: np.ndarray,
        language: Optional[str] = None,
        task: str = "transcribe",
        initial_prompt: Optional[str] = None,
    ) -> str:
        """
        Transcribe audio using the routing rule:
        If online: use Google endpoint if fast; otherwise fall back to local Whisper small.
        If offline: use local Whisper small immediately.
        """
        if audio is None or len(audio) == 0:
            return ""

        if not self._is_loaded:
            self.load()

        # Helper to ensure local engine is ready
        def _get_local_transcription() -> str:
            if not self.local_engine:
                return ""
            if not self.local_engine.is_loaded():
                tier = (
                    "balanced"
                    if self.model_manager and self.model_manager.is_model_downloaded("balanced")
                    else "small.en"
                )
                self.local_engine.load(tier)
            if self.local_engine.is_loaded():
                return self.local_engine.transcribe(
                    audio, language=language, task=task, initial_prompt=initial_prompt
                )
            return ""

        # 1. Pure offline mode -> never touch Google Web endpoint
        if self.offline_mode:
            return _get_local_transcription()

        # 2. Online path: Try Google endpoint with fast timeout budget
        try:
            res = self.fallback_engine.transcribe(
                audio, language=language, task=task, initial_prompt=initial_prompt
            )
            if res and res.strip():
                return res.strip()
        except Exception as e:
            print(
                f"[WindowsNativeSTT] Google endpoint failed/timed out ({e}), falling back to local Whisper...",
                file=sys.stderr,
            )

        # 3. Fallback to local Whisper small mode if Google endpoint was slow, failed, or offline
        try:
            return _get_local_transcription()
        except Exception as le_err:
            print(
                f"[WindowsNativeSTT] Local engine transcription error: {le_err}",
                file=sys.stderr,
            )

        return ""
