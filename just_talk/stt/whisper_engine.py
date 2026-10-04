"""High-performance local Whisper speech-to-text inference engine."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from .engine import STTEngine
from .model_manager import ModelManager


class WhisperSTTEngine(STTEngine):
    """
    Local speech-to-text engine using faster-whisper (CTranslate2).
    Keeps the model resident in memory for low-latency transcription.
    """

    def __init__(self, model_manager: Optional[ModelManager] = None):
        self.model_manager = model_manager or ModelManager()
        self._model = None
        self._current_tier: Optional[str] = None
        self._current_custom_target: Optional[str] = None
        self._lock = threading.Lock()
        self._is_loading = False
        self._loading_status = "Not initialized"

    @property
    def is_loading(self) -> bool:
        return self._is_loading

    @property
    def loading_status(self) -> str:
        return self._loading_status

    def load(self, tier_id: str = "quality", custom_target: Optional[str] = None) -> bool:
        """Load and warm up the selected model tier or custom model."""
        with self._lock:
            # Handle custom model target
            if custom_target:
                if self._model is not None and self._current_custom_target == custom_target:
                    return True

                self._is_loading = True
                self._loading_status = f"Loading custom model: {custom_target}..."

                try:
                    from faster_whisper import WhisperModel

                    self._model = WhisperModel(
                        custom_target,
                        device="auto",
                        compute_type="int8",
                        download_root=str(self.model_manager.models_dir),
                    )
                    self._current_tier = "custom"
                    self._current_custom_target = custom_target
                    self._is_loading = False
                    self._loading_status = "Ready (Custom)"
                    print(f"[STT] Loaded custom model '{custom_target}' successfully.")
                    return True
                except Exception as e:
                    self._is_loading = False
                    self._loading_status = f"Load error: {e}"
                    print(f"[STT] Failed to load custom model '{custom_target}': {e}", file=sys.stderr)
                    return False

            if self._model is not None and self._current_tier == tier_id and self._current_custom_target is None:
                return True

            info = self.model_manager.get_tier_info(tier_id)
            self._is_loading = True
            self._loading_status = f"Preparing {info.display_name}..."

            # Ensure model is fully downloaded first
            if not self.model_manager.is_model_downloaded(tier_id):
                self._loading_status = f"Downloading {info.display_name} (~{info.disk_size_mb} MB)..."

                def on_progress(pct: float, msg: str):
                    self._loading_status = msg

                success = self.model_manager.download_model(tier_id, progress_callback=on_progress)
                if not success:
                    self._is_loading = False
                    self._loading_status = "Download failed"
                    return False

            self._loading_status = f"Loading {info.display_name} into memory..."
            model_path = self.model_manager.get_model_path(tier_id)
            model_target = str(model_path) if model_path.exists() else info.model_name

            try:
                from faster_whisper import WhisperModel

                # Select optimal compute type for current platform
                # On CPU, int8 utilizes AVX2/AVX-512/ARM NEON for 3x speedup and minimal RAM
                self._model = WhisperModel(
                    model_target,
                    device="auto",
                    compute_type="int8",
                    download_root=str(self.model_manager.models_dir),
                )
                self._current_tier = tier_id
                self._current_custom_target = None
                self._is_loading = False
                self._loading_status = "Ready"
                print(f"[STT] Loaded {info.display_name} successfully.")
                return True
            except Exception as e:
                self._is_loading = False
                self._loading_status = f"Load error: {e}"
                print(f"[STT] Failed to load model {tier_id}: {e}", file=sys.stderr)
                return False

    def validate_custom_model(self, model_target: str) -> tuple[bool, str, float]:
        """
        Validate whether a custom Hugging Face repo ID or local directory can be loaded
        and used for transcription.
        Returns:
            (is_valid, message, latency_ms)
        """
        target = (model_target or "").strip()
        if not target:
            return False, "Model path or Hugging Face repo ID cannot be empty.", 0.0

        valid_struct, reason = self.model_manager.validate_custom_model_target(target)
        if not valid_struct:
            return False, reason, 0.0

        import time
        start = time.time()
        try:
            from faster_whisper import WhisperModel

            test_model = WhisperModel(
                target,
                device="auto",
                compute_type="int8",
                download_root=str(self.model_manager.models_dir),
            )
            # Run 0.1s dummy inference to verify model weights and pipeline execution
            dummy_audio = np.zeros(1600, dtype=np.float32)
            list(test_model.transcribe(dummy_audio, beam_size=1)[0])
            elapsed_ms = (time.time() - start) * 1000.0
            return True, f"Verified successfully ({elapsed_ms:.0f}ms test run)", elapsed_ms
        except Exception as e:
            return False, f"Load error: {e}", 0.0

    def is_loaded(self) -> bool:
        with self._lock:
            return self._model is not None

    def transcribe(
        self,
        audio: np.ndarray,
        language: Optional[str] = None,
        task: str = "transcribe",
        initial_prompt: Optional[str] = None,
    ) -> str:
        """
        Transcribe or translate audio array to text.
        Args:
            audio: 1D float32 NumPy array at 16000 Hz.
            language: ISO 639-1 language code (e.g. "ne", "en", "de", None or "auto" for auto-detect).
            task: "transcribe" (keep spoken language) or "translate" (translate speech to English).
            initial_prompt: Context or custom vocabulary prompt to prime the decoder.
        """
        if audio is None or len(audio) == 0:
            return ""

        # Normalize language
        if language in ("auto", "none", "", "None"):
            lang_param = None
        else:
            lang_param = language

        # Normalize task
        task_param = "translate" if task == "translate" else "transcribe"

        # Automatic gain normalization: boosts low-volume recordings for reliable transcription
        peak = float(np.max(np.abs(audio)))
        if 0.0003 < peak < 0.15:
            gain = min(0.25 / peak, 25.0)
            audio = (audio * gain).astype(np.float32)

        with self._lock:
            if self._model is None:
                if not self.load("quality"):
                    return ""

            try:
                try:
                    # beam_size=1 (greedy search) provides real-time speed for dictation
                    # vad_filter=True removes background noise/silence
                    segments, info = self._model.transcribe(
                        audio,
                        beam_size=1,
                        language=lang_param,
                        task=task_param,
                        vad_filter=True,
                        initial_prompt=initial_prompt,
                        condition_on_previous_text=False,
                    )
                    text_pieces = [segment.text.strip() for segment in segments]
                    result = " ".join(t for t in text_pieces if t)
                except Exception as vad_err:
                    print(f"[STT] VAD filter error ({vad_err}), falling back to direct transcription...", file=sys.stderr)
                    result = ""

                # Fallback: if VAD was overly aggressive, failed, or returned empty, transcribe directly
                if not result:
                    segments_raw, _ = self._model.transcribe(
                        audio,
                        beam_size=1,
                        language=lang_param,
                        task=task_param,
                        vad_filter=False,
                        initial_prompt=initial_prompt,
                        condition_on_previous_text=False,
                    )
                    fallback_pieces = [s.text.strip() for s in segments_raw]
                    result = " ".join(t for t in fallback_pieces if t)

                return result
            except Exception as e:
                print(f"[STT] Transcription error: {e}", file=sys.stderr)
                return ""

    def unload(self) -> None:
        """Unload model from RAM."""
        with self._lock:
            self._model = None
            self._current_tier = None
            self._current_custom_target = None
            self._is_loading = False
            self._loading_status = "Unloaded"
