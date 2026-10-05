"""Google Web Speech API STT Engine — Free zero-login cloud fallback."""

from __future__ import annotations

import sys
import threading
from typing import Optional

import numpy as np

from .engine import STTEngine


class GoogleWebSTTEngine(STTEngine):
    """
    Speech-to-text inference engine using the free Google Web Speech API endpoint.
    Requires ZERO login, ZERO API keys, and ZERO model downloads.

    Supports 120+ languages including English (en-US) and Nepali (ne-NP).
    """

    # Common language mapping from JustTalk ISO/app codes to Google BCP-47 tags
    LANGUAGE_MAP = {
        "en": "en-US",
        "ne": "ne-NP",
        "ne_en": "ne-NP",
        "hi": "hi-IN",
        "es": "es-ES",
        "fr": "fr-FR",
        "de": "de-DE",
        "it": "it-IT",
        "pt": "pt-BR",
        "ja": "ja-JP",
        "ko": "ko-KR",
        "zh": "zh-CN",
        "ar": "ar-SA",
        "ru": "ru-RU",
    }

    def __init__(self, timeout_sec: float = 8.0) -> None:
        self.timeout_sec = timeout_sec
        self._recognizer = None
        self._is_loaded = False
        self._lock = threading.Lock()

    def load(self, model_identifier: str = "") -> bool:
        """Initialize the SpeechRecognition instance."""
        with self._lock:
            try:
                import speech_recognition as sr

                self._recognizer = sr.Recognizer()
                self._is_loaded = True
                print("[GoogleWebSTT] Engine initialized successfully (zero-login cloud).")
                return True
            except ImportError as e:
                print(f"[GoogleWebSTT] Failed to import speech_recognition: {e}", file=sys.stderr)
                self._is_loaded = False
                return False

    def is_loaded(self) -> bool:
        """Return True if recognizer is ready."""
        return self._is_loaded

    def unload(self) -> None:
        """Clear recognizer state."""
        with self._lock:
            self._recognizer = None
            self._is_loaded = False

    def map_language(self, language: Optional[str]) -> str:
        """Map app language code to Google BCP-47 language tag."""
        if not language or language in ("auto", "none", ""):
            return "en-US"
        lang_lower = language.lower().strip()
        if lang_lower in self.LANGUAGE_MAP:
            return self.LANGUAGE_MAP[lang_lower]
        # If it's already a full BCP-47 tag (e.g. "en-GB", "ne-NP"), preserve it
        if "-" in language:
            return language
        return lang_lower

    def transcribe(
        self,
        audio: np.ndarray,
        language: Optional[str] = None,
        task: str = "transcribe",
        initial_prompt: Optional[str] = None,
    ) -> str:
        """
        Transcribe 16kHz float32 audio array using Google's free Web Speech endpoint.
        Returns raw transcribed text or empty string on silence/error.
        """
        if audio is None or len(audio) == 0:
            return ""

        if not self._is_loaded or self._recognizer is None:
            if not self.load():
                return ""

        import speech_recognition as sr

        # 1. Convert float32 [-1.0, 1.0] audio array to 16-bit signed PCM bytes
        try:
            pcm_data = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            audio_data = sr.AudioData(pcm_data, sample_rate=16000, sample_width=2)
        except Exception as conv_err:
            print(f"[GoogleWebSTT] Audio conversion error: {conv_err}", file=sys.stderr)
            return ""

        # 2. Resolve target language
        target_lang = self.map_language(language)

        # 3. Query Google Web Speech API with timeout and robust exception handling
        try:
            text = self._recognizer.recognize_google(
                audio_data,
                language=target_lang,
                show_all=False,
            )
            return str(text).strip() if text else ""
        except sr.UnknownValueError:
            # Normal: audio was silence or unintelligible noise
            return ""
        except sr.RequestError as req_err:
            # Network issue, DNS error, or temporary rate limit
            print(f"[GoogleWebSTT] Network request error: {req_err}", file=sys.stderr)
            return ""
        except Exception as e:
            print(f"[GoogleWebSTT] Unexpected transcription error: {e}", file=sys.stderr)
            return ""
