"""macOS Native Speech-to-Text Engine — Apple SFSpeechRecognizer integration."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import wave
from typing import Callable, List, Optional, Set, Tuple

import numpy as np

from ..audio.vad import VoiceActivityDetector
from .engine import STTEngine
from .long_form import IncrementalTranscriber, join_segments
from .google_web_engine import GoogleWebSTTEngine


class UtteranceTracker:
    """
    Builds one transcript from SFSpeechRecognizer results.

    Within one request Apple may revise an utterance, start a new one after a pause
    (the new result then holds only the new words), and re-send an utterance it already
    finished. Each result is stored with the span of audio it covers; a result replaces
    every stored one it overlaps, so revisions and re-sends never duplicate text and
    earlier utterances are never dropped.
    """

    _TOLERANCE_SEC = 0.05

    def __init__(self) -> None:
        self._spans: List[Tuple[float, float, str]] = []
        # Results without word timings fall back to text heuristics
        self._committed: List[str] = []
        self._latest = ""

    def add(self, text: str, span: Optional[Tuple[float, float]]) -> None:
        text = text.strip()
        if not text:
            return
        lowered = text.lower()
        if span is None:
            if any(lowered in t.lower() for _, _, t in self._spans):
                return  # already have this text with timings
            self._latest = MacNativeSTTEngine.merge_utterances(self._committed, self._latest, text)
            return
        # Partial results may arrive without timings and the final one with them:
        # the timed result supersedes any untimed text it contains.
        self._committed = [c for c in self._committed if c.lower() not in lowered]
        if self._latest and (
            self._latest.lower() in lowered or lowered.split()[0] == self._latest.lower().split()[0]
        ):
            self._latest = ""
        start, end = span
        tol = self._TOLERANCE_SEC
        self._spans = [
            (s, e, t) for (s, e, t) in self._spans if e <= start + tol or s >= end - tol
        ]
        self._spans.append((start, end, text))
        self._spans.sort(key=lambda x: x[0])

    def text(self) -> str:
        return join_segments([t for _, _, t in self._spans] + self._committed + [self._latest])


class MacNativeSTTEngine(STTEngine):
    """
    On-device speech-to-text inference engine using Apple's native SFSpeechRecognizer.
    Zero download, zero login, hardware-accelerated via Apple Silicon Neural Engine.

    Gracefully degrades to GoogleWebSTTEngine for languages unsupported by Apple
    (such as Nepali 'ne-NP') or if microphone/speech permissions are denied.
    """

    # Longest audio handed to one recognition request; longer dictation is split at pauses.
    MAX_CHUNK_SEC = 15.0

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

    def __init__(self, fallback_engine: Optional[STTEngine] = None, offline_mode: bool = False) -> None:
        self.fallback_engine = fallback_engine or GoogleWebSTTEngine(offline_mode=offline_mode)
        self.offline_mode = offline_mode
        self._is_loaded = False
        self._supported_locales: Set[str] = set()
        self._lock = threading.Lock()
        self._partial = IncrementalTranscriber(self.transcribe)

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

    def reset_partial(self) -> None:
        """Forget cached live-partial state at the start of a new recording."""
        self._partial.reset()

    def transcribe_partial(
        self,
        audio: np.ndarray,
        language: Optional[str] = None,
        task: str = "transcribe",
    ) -> str:
        """Live partial for the HUD: caches earlier speech and only re-decodes the recent tail."""
        return self._partial.update(audio, language=language, task=task)

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
            if self.offline_mode:
                print(f"[MacNativeSTT] Offline mode is active; skipping cloud fallback for {language}.", file=sys.stderr)
                return ""
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
                if self.offline_mode:
                    print("[MacNativeSTT] macOS Speech denied in offline mode; aborting.", file=sys.stderr)
                    return ""
                return self.fallback_engine.transcribe(
                    audio, language=language, task=task, initial_prompt=initial_prompt
                )

            ns_locale = NSLocale.localeWithLocaleIdentifier_(target_locale)
            recognizer = Speech.SFSpeechRecognizer.alloc().initWithLocale_(ns_locale)
            if not recognizer or not recognizer.isAvailable():
                if self.offline_mode:
                    print(f"[MacNativeSTT] Recognizer unavailable for {target_locale} in offline mode; aborting.", file=sys.stderr)
                    return ""
                return self.fallback_engine.transcribe(
                    audio, language=language, task=task, initial_prompt=initial_prompt
                )

        except Exception as init_err:
            print(f"[MacNativeSTT] SFSpeechRecognizer setup failed ({init_err}), falling back...", file=sys.stderr)
            if self.offline_mode:
                return ""
            return self.fallback_engine.transcribe(
                audio, language=language, task=task, initial_prompt=initial_prompt
            )

        # 3. Recognize pause-aligned chunks. Apple's recognizer ends an utterance on a long
        # pause and starts a fresh transcript, so long dictation must be stitched together.
        chunks = VoiceActivityDetector.split_on_pauses(audio, max_chunk_sec=self.MAX_CHUNK_SEC)
        parts = []
        for chunk in chunks:
            prefix = join_segments(parts)

            def chunk_callback(text: str, _prefix: str = prefix) -> None:
                if partial_callback:
                    partial_callback(join_segments([_prefix, text]))

            text, ok = self._recognize_native_chunk(recognizer, chunk, target_locale, chunk_callback)
            if not ok and not self.offline_mode:
                # Native recognition failed or was cut short; prefer the fallback's full
                # result, but keep whatever native text we got if the fallback has nothing.
                fallback_text = self.fallback_engine.transcribe(
                    chunk, language=language, task=task, initial_prompt=initial_prompt
                )
                if fallback_text and fallback_text.strip():
                    text = fallback_text
            parts.append(text)
        return join_segments(parts)

    @staticmethod
    def merge_utterances(committed: List[str], previous: str, current: str) -> str:
        """
        Fold a new partial result into the running transcript.

        After a pause, SFSpeechRecognizer (macOS 14+) starts a new utterance and its
        bestTranscription only contains the words spoken *after* the pause. When the
        new text no longer extends the previous one, the previous utterance is final
        and gets appended to ``committed`` so it is not lost. Used when Apple gives no word
        timings; otherwise UtteranceTracker matches results by audio span.
        """
        prev = previous.strip()
        cur = current.strip()
        if not prev or not cur:
            return cur or prev
        if cur in committed:
            # Apple re-sent an utterance it already finished; keep the current one going
            return prev

        # No timestamps: a revision keeps the opening words (or at worst re-hears just the
        # first word); a new utterance starts with different words, whatever its length.
        prev_words = prev.lower().split()
        cur_words = cur.lower().split()
        if cur_words[0] == prev_words[0]:
            is_new_utterance = len(cur) < len(prev) * 0.5
        else:
            prev_next = prev_words[1:3]
            is_new_utterance = not prev_next or cur_words[1 : 1 + len(prev_next)] != prev_next
        if is_new_utterance:
            committed.append(prev)
        return cur

    @staticmethod
    def _audio_span(transcription) -> Optional[Tuple[float, float]]:
        """(start, end) in seconds of the audio a transcription covers, if Apple gave word timings."""
        try:
            segments = transcription.segments()
            if segments and len(segments):
                first, last = segments[0], segments[len(segments) - 1]
                start = float(first.timestamp())
                end = float(last.timestamp()) + float(last.duration())
                if end > 0:
                    return start, end
        except Exception:
            pass
        return None

    def _recognize_native_chunk(
        self,
        recognizer,
        audio: np.ndarray,
        target_locale: str,
        partial_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, bool]:
        """Run SFSpeechRecognizer on one chunk. Returns (text, ok)."""
        import Speech
        from Foundation import NSURL

        # Create temporary WAV file for SFSpeechURLRecognitionRequest
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        try:
            pcm_bytes = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(pcm_bytes)

            url = NSURL.fileURLWithPath_(wav_path)
            req = Speech.SFSpeechURLRecognitionRequest.alloc().initWithURL_(url)
            req.setShouldReportPartialResults_(True)

            # Enforce on-device recognition if supported by Apple Speech for this locale
            supports_on_device = False
            if hasattr(recognizer, "supportsOnDeviceRecognition"):
                try:
                    supports_on_device = bool(recognizer.supportsOnDeviceRecognition())
                except Exception:
                    supports_on_device = False

            if supports_on_device and hasattr(req, "setRequiresOnDeviceRecognition_"):
                try:
                    req.setRequiresOnDeviceRecognition_(True)
                except Exception:
                    pass
            elif self.offline_mode and not supports_on_device:
                # In strict offline mode, if Apple on-device recognition is not available, block audio from cloud
                print(f"[MacNativeSTT] Offline mode is active and Apple on-device speech is unsupported for {target_locale}; blocking egress.", file=sys.stderr)
                return "", True

            done_event = threading.Event()
            tracker = UtteranceTracker()
            had_error = False

            def handler(result, error):
                nonlocal had_error
                if error:
                    had_error = True
                    done_event.set()
                    return
                if result:
                    best = result.bestTranscription()
                    tracker.add(str(best.formattedString()), self._audio_span(best))
                    if partial_callback:
                        try:
                            text_so_far = tracker.text()
                            if text_so_far:
                                partial_callback(text_so_far)
                        except Exception:
                            pass
                    if result.isFinal():
                        done_event.set()

            task_obj = recognizer.recognitionTaskWithRequest_resultHandler_(req, handler)
            # On-device recognition is usually faster than real time, but never cut it short:
            # giving up early is exactly what truncated long dictation before.
            timeout = 10.0 + 2.0 * len(audio) / 16000
            completed = done_event.wait(timeout=timeout)
            if not completed and task_obj:
                try:
                    task_obj.cancel()
                except Exception:
                    pass

            text = tracker.text()
            if not completed:
                print(f"[MacNativeSTT] Recognition timed out after {timeout:.0f}s for a "
                      f"{len(audio) / 16000:.1f}s chunk (partial: '{text}')", file=sys.stderr)
            # An error or timeout means `text` may be truncated: report failure (with the
            # partial text) so the caller can try the fallback engine for this chunk.
            return text, completed and not had_error
        except Exception as run_err:
            print(f"[MacNativeSTT] Native execution error ({run_err}), falling back...", file=sys.stderr)
            return "", False
        finally:
            if os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception:
                    pass
