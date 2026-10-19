"""Speech engines the voice setup compares, and how to switch the app to the one that wins.

Only engines that are already on the computer are used: nothing is downloaded, and no audio is
sent anywhere the user isn't already sending it (Google is compared only when it is already their
engine). Whisper instances created here are separate from the app's and freed by release().
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import numpy as np

from .scripts import EN, MIXED, NE, vocabulary_terms

WHISPER_LABELS = {
    "quality": "Whisper Turbo",
    "max": "Whisper Large",
    "balanced": "Whisper Small",
    "fast": "Whisper Base",
    "small.en": "Whisper Small",
    "base.en": "Whisper Base",
}
ENGLISH_ONLY_TIERS = ("small.en", "base.en")
LIVE_WHISPER_TIERS = ("small.en", "base.en")  # fast enough to re-run every half second


@dataclass
class EngineCandidate:
    id: str
    label: str
    transcribe: Callable[[np.ndarray, str], str]  # (16 kHz audio, language) -> text
    local: bool = True


def engine_label(engine_id: str) -> str:
    if engine_id.startswith("whisper:"):
        return WHISPER_LABELS.get(engine_id.split(":", 1)[1], "Whisper")
    return {"kriti": "Kriti", "apple": "Apple", "google": "Google", "windows": "Windows"}.get(engine_id, engine_id)


def current_engine_id(config, language: str, kriti_available: bool) -> str:
    """The engine the app would use for this language right now."""
    provider = getattr(config, "stt_provider", "os_native") or "os_native"
    if language in (NE, MIXED) and getattr(config, "nepali_asr_engine", "kriti") == "kriti" and kriti_available:
        return "kriti"
    if provider == "whisper":
        if getattr(config, "stt_model_source", "bundled") == "custom":
            return "whisper:custom"
        return f"whisper:{getattr(config, 'model_tier', 'quality')}"
    if provider == "google_web":
        return "google"
    if sys.platform == "darwin" and language == EN:
        return "apple"
    # Apple has no Nepali, and the Windows engine starts with Google when online
    return "google"


def can_apply(config, language: str, engine_id: str) -> bool:
    if engine_id in ("", "whisper:custom"):
        return False
    if language == EN:
        if engine_id.startswith("whisper:") and engine_id.split(":", 1)[1] in ENGLISH_ONLY_TIERS:
            # An English-only Whisper can't also serve Nepali; fine only when Kriti covers Nepali.
            speaks_nepali = "ne" in (getattr(config, "spoken_languages", None) or [])
            return not speaks_nepali or getattr(config, "nepali_asr_engine", "kriti") == "kriti"
        return engine_id in ("apple", "google") or engine_id.startswith("whisper:")
    if engine_id == "kriti":
        return True
    # Whisper for Nepali only means "use the main engine", so it must already be that Whisper
    return engine_id == current_engine_id(config, EN, False) and engine_id.startswith("whisper:")


def apply_choice(config, language: str, engine_id: str) -> bool:
    """Point the app at engine_id for this language. Returns True if the main engine changed."""
    if not can_apply(config, language, engine_id):
        return False
    if language in (NE, MIXED):
        config.nepali_asr_engine = "kriti" if engine_id == "kriti" else "whisper"
        return False
    before = (config.stt_provider, getattr(config, "model_tier", ""))
    if engine_id == "apple":
        config.stt_provider = "os_native"
    elif engine_id == "google":
        config.stt_provider = "google_web"
    else:
        config.stt_provider = "whisper"
        config.stt_model_source = "bundled"
        config.model_tier = engine_id.split(":", 1)[1]
    return (config.stt_provider, getattr(config, "model_tier", "")) != before


class ProfileEngines:
    def __init__(self, config, model_manager, kriti=None):
        self.config = config
        self.model_manager = model_manager
        self.kriti = kriti
        self._whisper: Dict[str, object] = {}
        self._apple = None
        self._google = None
        self._lock = threading.Lock()

    # ── Building blocks ──────────────────────────────────────────────────────

    def kriti_available(self) -> bool:
        try:
            return bool(self.kriti and self.kriti.is_available())
        except Exception:
            return False

    def _downloaded(self, tier: str) -> bool:
        try:
            return bool(self.model_manager and self.model_manager.is_model_downloaded(tier))
        except Exception:
            return False

    def _whisper_engine(self, tier: str):
        with self._lock:
            engine = self._whisper.get(tier)
            if engine is None:
                from ..stt.whisper_engine import WhisperSTTEngine

                engine = WhisperSTTEngine(self.model_manager)
                self._whisper[tier] = engine
        return engine

    def _whisper_candidate(self, tier: str) -> EngineCandidate:
        def run(audio: np.ndarray, language: str) -> str:
            engine = self._whisper_engine(tier)
            if not engine.is_loaded() and not engine.load(tier):
                return ""
            lang = None if language == MIXED else language
            return engine.transcribe(audio, language=lang)

        return EngineCandidate(f"whisper:{tier}", WHISPER_LABELS.get(tier, "Whisper"), run)

    def _kriti_candidate(self) -> EngineCandidate:
        return EngineCandidate("kriti", "Kriti", lambda audio, _lang: self.kriti.transcribe(audio, language="ne"))

    def _apple_candidate(self) -> EngineCandidate:
        def run(audio: np.ndarray, language: str) -> str:
            if self._apple is None:
                from ..stt.mac_native_engine import MacNativeSTTEngine

                self._apple = MacNativeSTTEngine(offline_mode=True)  # never falls back to Google here
                self._apple.load()
            self._apple.vocabulary = vocabulary_terms(self.config)
            return self._apple.transcribe(audio, language=language)

        return EngineCandidate("apple", "Apple", run)

    def _google_candidate(self) -> EngineCandidate:
        def run(audio: np.ndarray, language: str) -> str:
            if self._google is None:
                from ..stt.google_web_engine import GoogleWebSTTEngine

                self._google = GoogleWebSTTEngine()
                self._google.load()
            return self._google.transcribe(audio, language="ne" if language == MIXED else language)

        return EngineCandidate("google", "Google", run, local=False)

    def _build(self, engine_id: str) -> Optional[EngineCandidate]:
        if engine_id == "kriti":
            return self._kriti_candidate() if self.kriti_available() else None
        if engine_id == "apple":
            return self._apple_candidate() if sys.platform == "darwin" else None
        if engine_id == "google":
            return None if getattr(self.config, "offline_mode", False) else self._google_candidate()
        if engine_id.startswith("whisper:"):
            tier = engine_id.split(":", 1)[1]
            return self._whisper_candidate(tier) if tier != "custom" and self._downloaded(tier) else None
        return None

    # ── What setup uses ──────────────────────────────────────────────────────

    def current(self, language: str) -> str:
        return current_engine_id(self.config, language, self.kriti_available())

    def live_id(self, language: str) -> Optional[str]:
        """Engine re-run on the growing recording to light up words as they're said."""
        if language in (NE, MIXED):
            return "kriti" if self.kriti_available() else None
        for tier in LIVE_WHISPER_TIERS:
            if self._downloaded(tier):
                return f"whisper:{tier}"
        return "apple" if sys.platform == "darwin" else None

    def candidate_ids(self, language: str) -> List[str]:
        ids: List[str] = []
        current = self.current(language)
        if current != "google" or not getattr(self.config, "offline_mode", False):
            ids.append(current)
        live = self.live_id(language)
        if live:
            ids.append(live)
        if language in (NE, MIXED):
            ids.append("kriti")
            tier = getattr(self.config, "model_tier", "quality")
            if tier not in ENGLISH_ONLY_TIERS:
                ids.append(f"whisper:{tier}")
        else:
            ids.append(f"whisper:{getattr(self.config, 'model_tier', 'quality')}")
        return [i for i in dict.fromkeys(ids) if i != "whisper:custom"]

    def candidates(self, language: str) -> List[EngineCandidate]:
        return [c for c in (self._build(i) for i in self.candidate_ids(language)) if c is not None]

    def get(self, engine_id: str) -> Optional[EngineCandidate]:
        return self._build(engine_id)

    def release(self) -> None:
        with self._lock:
            engines = list(self._whisper.values())
            self._whisper.clear()
        for engine in engines:
            try:
                engine.unload()
            except Exception:
                pass
