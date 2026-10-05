"""macOS Native Speech-to-Text Engine — Apple SFSpeechRecognizer integration."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import wave
from typing import Optional, Set

import numpy as np

from .engine import STTEngine
from .google_web_engine import GoogleWebSTTEngine


class MacNativeSTTEngine(STTEngine):
    """
    On-device speech-to-text inference engine using Apple's native SFSpeechRecognizer.
    Zero download, zero login, hardware-accelerated via Apple Silicon Neural Engine.

    Gracefully degrades to GoogleWebSTTEngine for languages unsupported by Apple
    (such as Nepali 'ne-NP') or if microphone/speech permissions are denied.
    """

    # Language mapping from JustTalk short codes to macOS BCP-47 locale tags
    LOCALE_MAP = {
        "en": "en-US",
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

    def __init__(self, fallback_engine: Optional[STTEngine] = None) -> None:
        self.fallback_engine = fallback_engine or GoogleWebSTTEngine()
        self._is_loaded = False
        self._supported_locales: Set[str] = set()
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        """Check if native macOS speech recognition is available on this system."""
        if sys.platform != "darwin":
            return False
        try:
            import Speech
            return True
        except ImportError:
            return False

    def load(self, model_identifier: str = "") -> bool:
        """Initialize and cache supported macOS speech locales."""
        with self._lock:
            if not self.is_available():
                print("[MacNativeSTT] macOS Speech framework not available, enabling fallback.", file=sys.stderr)
                self.fallback_engine.load()
                self._is_loaded = True
                return True

            try:
                import Speech
                from Foundation import NSLocale

                # Query supported locales
                locales = Speech.SFSpeechRecognizer.supportedLocales()
                if locales:
                    self._supported_locales = {str(loc.localeIdentifier()) for loc in locales}
                print(f"[MacNativeSTT] Initialized with {len(self._supported_locales)} native macOS speech locales.")
                self.fallback_engine.load()
                self._is_loaded = True
                return True
            except Exception as e:
                print(f"[MacNativeSTT] Error initializing macOS Speech: {e}", file=sys.stderr)
                self.fallback_engine.load()
                self._is_loaded = True
                return True

    def is_loaded(self) -> bool:
        return self._is_loaded

    def unload(self) -> None:
        with self._lock:
            self._supported_locales.clear()
            self._is_loaded = False
            if self.fallback_engine:
                self.fallback_engine.unload()

    def _resolve_locale(self, language: Optional[str]) -> Optional[str]:
        """Resolve app language code to a supported Apple SFSpeechRecognizer locale, or None if unsupported."""
        if not language or language in ("auto", "none", ""):
            return "en-US" if "en-US" in self._supported_locales else None

        lang_lower = language.lower().strip()

        # Nepali is not supported in Apple's speech catalog -> return None to trigger fallback
        if lang_lower in ("ne", "ne_en", "ne-np"):
            return None

        # Check mapping
        if lang_lower in self.LOCALE_MAP:
            cand = self.LOCALE_MAP[lang_lower]
            if cand in self._supported_locales:
                return cand

        # Check exact BCP-47 match
        if language in self._supported_locales:
            return language

        # Search for language prefix in supported locales (e.g. "en" in "en-US")
        prefix = lang_lower.split("-")[0]
        for loc in self._supported_locales:
            if loc.lower().startswith(prefix):
                return loc

        return None

    def transcribe(
        self,
        audio: np.ndarray,
        language: Optional[str] = None,
        task: str = "transcribe",
        initial_prompt: Optional[str] = None,
        partial_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Transcribe 16kHz float32 audio.
        If native speech is unavailable, denied, or language unsupported,
        automatically falls back to GoogleWebSTTEngine.
        """
        if audio is None or len(audio) == 0:
            return ""

        if not self._is_loaded:
            self.load()

        # 1. Check if language is supported by macOS native speech
        target_locale = self._resolve_locale(language)
        if not target_locale or not self.is_available():
            # Graceful degradation for Nepali or unsupported languages
            return self.fallback_engine.transcribe(
                audio, language=language, task=task, initial_prompt=initial_prompt
            )

        # 2. Check authorization
        try:
            import Speech
            from Foundation import NSLocale, NSURL

            auth_status = Speech.SFSpeechRecognizer.authorizationStatus()
            # 0 = NotDetermined, 1 = Denied, 2 = Restricted, 3 = Authorized
            if auth_status in (1, 2):
                # User previously denied Speech Recognition permission -> degrade to Google Web
                return self.fallback_engine.transcribe(
                    audio, language=language, task=task, initial_prompt=initial_prompt
                )

            ns_locale = NSLocale.localeWithLocaleIdentifier_(target_locale)
            recognizer = Speech.SFSpeechRecognizer.alloc().initWithLocale_(ns_locale)
            if not recognizer or not recognizer.isAvailable():
                # Recognizer not ready or network offline for this locale
                return self.fallback_engine.transcribe(
                    audio, language=language, task=task, initial_prompt=initial_prompt
                )

        except Exception as init_err:
            print(f"[MacNativeSTT] SFSpeechRecognizer setup failed ({init_err}), falling back...", file=sys.stderr)
            return self.fallback_engine.transcribe(
                audio, language=language, task=task, initial_prompt=initial_prompt
            )

        # 3. Create temporary WAV file for SFSpeechURLRecognitionRequest
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
            try:
                pcm_bytes = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                with wave.open(wav_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(pcm_bytes)
            except Exception as write_err:
                print(f"[MacNativeSTT] WAV write error: {write_err}", file=sys.stderr)
                if os.path.exists(wav_path):
                    os.remove(wav_path)
                return self.fallback_engine.transcribe(audio, language=language, task=task, initial_prompt=initial_prompt)

        try:
            url = NSURL.fileURLWithPath_(wav_path)
            req = Speech.SFSpeechURLRecognitionRequest.alloc().initWithURL_(url)
            req.setShouldReportPartialResults_(True)

            done_event = threading.Event()
            transcription_text = []
            had_error = False

            def handler(result, error):
                nonlocal had_error
                if error:
                    had_error = True
                    done_event.set()
                    return
                if result:
                    text = result.bestTranscription().formattedString()
                    text_str = str(text)
                    transcription_text.append(text_str)
                    if partial_callback and text_str:
                        try:
                            partial_callback(text_str)
                        except Exception:
                            pass
                    if result.isFinal():
                        done_event.set()

            task_obj = recognizer.recognitionTaskWithRequest_resultHandler_(req, handler)
            # Wait up to 5.0 seconds for on-device recognition
            completed = done_event.wait(timeout=5.0)

            if not completed or had_error or not transcription_text:
                if not completed and task_obj:
                    try:
                        task_obj.cancel()
                    except Exception:
                        pass
                # If native recognition produced nothing or timed out, fall back
                fallback_res = self.fallback_engine.transcribe(
                    audio, language=language, task=task, initial_prompt=initial_prompt
                )
                if fallback_res:
                    return fallback_res

            final_str = transcription_text[-1].strip() if transcription_text else ""
            return final_str
        except Exception as run_err:
            print(f"[MacNativeSTT] Native execution error ({run_err}), falling back...", file=sys.stderr)
            return self.fallback_engine.transcribe(
                audio, language=language, task=task, initial_prompt=initial_prompt
            )
        finally:
            if os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception:
                    pass
