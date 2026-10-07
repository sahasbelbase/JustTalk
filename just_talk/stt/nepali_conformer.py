"""Ampixa NepaliConformer offline speech recognition engine.

Reference: https://ampixa.com/#work & https://github.com/Ampixa/nepaliconformer
Trained on ~1,655 hours of conversational Nepali speech.
Benchmark: 36.3% WER on NepTel real call-centre audio (vs 96.3% for zero-shot Whisper Large-V3),
as measured by Ampixa on the released weights. Model weights: CC BY-NC 4.0.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from .engine import STTEngine
from .model_manager import ModelManager


class NepaliConformerEngine(STTEngine):
    """
    Offline Nepali speech-to-text inference engine powered by Ampixa Labs' NepaliConformer.
    Designed for spontaneous conversational Nepali, Nepglish code-switching, and phone audio.
    """

    def __init__(self, model_manager: Optional[ModelManager] = None):
        self.model_manager = model_manager or ModelManager()
        self._model = None
        self._lock = threading.Lock()
        self._is_loaded = False
        self._is_loading = False
        self._loading_status = "Not initialized"
        self._model_path: Optional[Path] = None

    @property
    def is_loading(self) -> bool:
        return self._is_loading

    @property
    def loading_status(self) -> str:
        return self._loading_status

    def load(self, model_identifier: str = "nepali_conformer") -> bool:
        """Load and initialize Ampixa NepaliConformer offline weights."""
        with self._lock:
            if self._is_loaded:
                return True

            self._is_loading = True
            self._loading_status = "Locating Ampixa NepaliConformer weights..."

            # Ensure model exists in cache — never trigger download here;
            # NepaliConformer must be explicitly downloaded from Settings.
            # If weights are missing, fall back immediately to Whisper.
            if not self.model_manager.is_model_downloaded("nepali_conformer"):
                self._is_loading = False
                self._loading_status = "Not downloaded — using Whisper Nepali fallback"
                print(
                    "[NepaliConformer] Ampixa weights not found locally; "
                    "falling back to Whisper multilingual for Nepali.",
                    file=sys.stderr,
                )
                return False

            base_dir = self.model_manager.get_model_path("nepali_conformer")
            nemo_candidates = list(base_dir.glob("*.nemo"))
            if not nemo_candidates:
                # Check directly in models_dir
                nemo_candidates = list(self.model_manager.models_dir.glob("**/nepali_conformer_offline.nemo"))

            if not nemo_candidates:
                self._is_loading = False
                self._loading_status = "Missing .nemo model checkpoint"
                return False

            self._model_path = nemo_candidates[0]
            self._loading_status = f"Loading NepaliConformer ({self._model_path.name})..."

            try:
                # Try loading via NeMo if installed
                import nemo.collections.asr as nemo_asr  # type: ignore

                print(f"[NepaliConformer] Restoring weights from {self._model_path}...", file=sys.stderr)
                self._model = nemo_asr.models.EncDecCTCModel.restore_from(str(self._model_path))
                self._model.eval()
                self._is_loaded = True
                self._is_loading = False
                self._loading_status = "Ready (NeMo CTC Engine)"
                print("[NepaliConformer] Ampixa 121M offline conformer initialized successfully.", file=sys.stderr)
                return True
            except ImportError:
                # Without NeMo the checkpoint cannot run; report that instead of pretending
                # to be ready and quietly transcribing with Whisper.
                self._is_loading = False
                self._loading_status = "Unavailable — needs the NeMo runtime (not bundled)"
                print(
                    "[NepaliConformer] NeMo toolkit not installed; the .nemo checkpoint cannot run. "
                    "Nepali uses Whisper.",
                    file=sys.stderr,
                )
                return False
            except Exception as e:
                self._is_loading = False
                self._loading_status = f"Load error: {e}"
                print(f"[NepaliConformer] Error loading weights: {e}", file=sys.stderr)
                return False

    def is_loaded(self) -> bool:
        with self._lock:
            return self._is_loaded

    def transcribe(
        self,
        audio: np.ndarray,
        language: Optional[str] = "ne",
        task: str = "transcribe",
        initial_prompt: Optional[str] = None,
    ) -> str:
        """
        Transcribe 16kHz audio array using Ampixa NepaliConformer.
        Falls back seamlessly to high-accuracy prompt-primed Whisper if NeMo runtime is not resident.
        """
        if audio is None or len(audio) == 0:
            return ""

        with self._lock:
            if not self._is_loaded:
                if not self.load():
                    return ""

        # Normalize audio amplitude
        peak = float(np.max(np.abs(audio)))
        if 0.0003 < peak < 0.15:
            gain = min(0.25 / peak, 25.0)
            audio = (audio * gain).astype(np.float32)

        # If native NeMo model is resident
        if self._model is not None and self._model != "fallback_bridge":
            try:
                import tempfile
                import soundfile as sf  # type: ignore

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name

                try:
                    sf.write(tmp_path, audio, 16000)
                    transcriptions = self._model.transcribe(paths2audio_files=[tmp_path])
                    if transcriptions and len(transcriptions) > 0:
                        raw_text = transcriptions[0]
                        if isinstance(raw_text, str):
                            return raw_text.strip()
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
            except Exception as e:
                print(f"[NepaliConformer] NeMo transcription error: {e}", file=sys.stderr)

        # Fallback to high-bias Nepglish acoustic transcription via Whisper
        from .whisper_engine import WhisperSTTEngine

        nepali_prompt = (
            "साह्रै राम्रो, नमस्कार, हजुर, ठिक छ, धन्यवाद, के छ, कस्तो छ, "
            "हामी, आज, काम, code, update, system, let's go. "
            + (initial_prompt or "")
        )

        whisper = WhisperSTTEngine(self.model_manager)
        return whisper.transcribe(
            audio=audio,
            language="ne",
            task=task,
            initial_prompt=nepali_prompt,
        )

    def unload(self) -> None:
        """Free memory."""
        with self._lock:
            self._model = None
            self._is_loaded = False
            self._is_loading = False
            self._loading_status = "Unloaded"
