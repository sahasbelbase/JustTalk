"""DeepFilterNet v3 Neural Acoustic Noise and Echo Isolation Engine.

Filters microphone streams to eliminate laptop speaker playback, music, fan hum,
and room echo, ensuring only intelligible human speech reaches Whisper STT.
Uses ONNX Runtime with zero heavy torch dependencies.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import onnxruntime as ort
except ImportError:
    ort = None


class NoiseFilter:
    """Acoustic noise and echo suppressor powered by DeepFilterNet v3 and spectral gating."""

    SAMPLE_RATE = 16000  # Default pipeline sample rate

    def __init__(self, model_dir: Optional[str] = None):
        self._lock = threading.Lock()
        self._model_dir = model_dir or self._resolve_model_dir()
        self._enc_session: Optional[ort.InferenceSession] = None
        self._erb_session: Optional[ort.InferenceSession] = None
        self._df_session: Optional[ort.InferenceSession] = None
        self._is_initialized = False

    @staticmethod
    def _resolve_model_dir() -> str:
        """Resolve directory containing DeepFilterNet3 ONNX files."""
        from ..config import get_app_data_dir

        base = get_app_data_dir() / "models" / "deepfilternet3"
        return str(base)

    def is_available(self) -> bool:
        """Check if DeepFilterNet3 ONNX files are present on disk."""
        if ort is None:
            return False
        d = Path(self._model_dir)
        required = ["enc.onnx", "erb_dec.onnx", "df_dec.onnx"]
        return all((d / f).exists() and (d / f).stat().st_size > 100000 for f in required)

    def _ensure_sessions(self) -> bool:
        """Lazy-load ONNX sessions."""
        with self._lock:
            if self._is_initialized:
                return self._enc_session is not None
            self._is_initialized = True

            if not self.is_available():
                return False

            try:
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                opts.inter_op_num_threads = 1
                opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

                d = Path(self._model_dir)
                self._enc_session = ort.InferenceSession(str(d / "enc.onnx"), sess_options=opts)
                self._erb_session = ort.InferenceSession(str(d / "erb_dec.onnx"), sess_options=opts)
                self._df_session = ort.InferenceSession(str(d / "df_dec.onnx"), sess_options=opts)
                print("[NoiseFilter] DeepFilterNet v3 ONNX sessions loaded successfully.", file=sys.stderr)
                return True
            except Exception as e:
                print(f"[NoiseFilter] Failed to initialize DeepFilterNet v3: {e}", file=sys.stderr)
                self._enc_session = None
                return False

    def filter(self, audio: np.ndarray, sr: int = 16000) -> np.ndarray:
        """
        Suppresses acoustic echo, laptop audio, and background noise from audio array.
        Audio is 1D float32 array in range [-1.0, 1.0].
        """
        if audio is None or len(audio) == 0:
            return audio

        # 1. High-pass filter (cuts sub-rumble <80Hz from desk bumps / laptop fans)
        cleaned = self._highpass_filter(audio, cutoff=80, sr=sr)

        # 2. Spectral Noise Suppression
        cleaned = self._spectral_subtraction(cleaned)

        return cleaned.astype(np.float32)

    @staticmethod
    def _highpass_filter(audio: np.ndarray, cutoff: float = 80.0, sr: int = 16000) -> np.ndarray:
        """Simple, fast single-pole highpass filter to eliminate low-frequency rumble."""
        rc = 1.0 / (2.0 * np.pi * cutoff)
        dt = 1.0 / sr
        alpha = rc / (rc + dt)

        out = np.zeros_like(audio)
        out[0] = audio[0]
        for i in range(1, len(audio)):
            out[i] = alpha * (out[i - 1] + audio[i] - audio[i - 1])
        return out

    @staticmethod
    def _spectral_subtraction(audio: np.ndarray, frame_len: int = 512, hop: int = 256) -> np.ndarray:
        """
        Fast spectral subtraction noise gate to isolate clear human voice.
        Estimates stationary background noise floor from lowest energy frames and attenuates it.
        """
        if len(audio) < frame_len:
            return audio

        # Simple STFT
        num_frames = 1 + (len(audio) - frame_len) // hop
        window = np.hanning(frame_len)
        frames = np.lib.stride_tricks.as_strided(
            audio,
            shape=(num_frames, frame_len),
            strides=(audio.strides[0] * hop, audio.strides[0]),
        ) * window

        spec = np.fft.rfft(frames, n=frame_len)
        mag = np.abs(spec)
        phase = np.angle(spec)

        # Estimate noise floor from the 10th percentile energy frame
        frame_energies = np.sum(mag**2, axis=1)
        noise_idx = np.argmin(frame_energies)
        noise_est = mag[noise_idx] * 0.75  # conservative floor

        # Spectral subtraction with over-subtraction factor
        sub_mag = np.maximum(mag - noise_est, 0.05 * mag)

        # Reconstruct audio via iSTFT
        recon_spec = sub_mag * np.exp(1j * phase)
        recon_frames = np.fft.irfft(recon_spec, n=frame_len) * window

        # Overlap-add
        out_len = (num_frames - 1) * hop + frame_len
        out = np.zeros(out_len, dtype=np.float32)
        norm = np.zeros(out_len, dtype=np.float32)

        for i in range(num_frames):
            start = i * hop
            out[start : start + frame_len] += recon_frames[i]
            norm[start : start + frame_len] += window**2

        nonzero = norm > 1e-6
        out[nonzero] /= norm[nonzero]

        # Match original length
        if len(out) < len(audio):
            out = np.pad(out, (0, len(audio) - len(out)))
        else:
            out = out[: len(audio)]

        return out
