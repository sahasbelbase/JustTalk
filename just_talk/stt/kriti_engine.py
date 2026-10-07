"""Kriti offline Nepali speech engine (ONNX Runtime, no NeMo/PyTorch).

Model: Kriti by Naamche Labs (MIT), derived from the AI4Bharat Nepali IndicConformer (MIT).
The ONNX conversion is published at github.com/sahasbelbase/kriti (release KRITI_RELEASE_TAG)
and verified there against the original NeMo model before release.
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import numpy as np

from .engine import STTEngine

KRITI_RELEASE_TAG = "onnx-v1"
KRITI_RELEASE_URL = f"https://github.com/sahasbelbase/kriti/releases/download/{KRITI_RELEASE_TAG}"
KRITI_QUANTIZED = True
KRITI_FILES = (
    "encoder.int8.onnx",
    "decoder.int8.onnx",
    "joint.int8.onnx",
    "model_config.json",
    "tokens.json",
    "punctuation_head.json",
)
KRITI_DOWNLOAD_MB = 135


def kriti_model_dir(models_dir: Path) -> Path:
    return models_dir / f"kriti-{KRITI_RELEASE_TAG}"


def is_kriti_downloaded(models_dir: Path) -> bool:
    d = kriti_model_dir(models_dir)
    return all((d / f).exists() for f in KRITI_FILES)


def _parse_sha256sums(text: str) -> Dict[str, str]:
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def download_kriti(models_dir: Path, progress: Optional[Callable[[float], None]] = None) -> Tuple[bool, str]:
    """Download the release files into models_dir, verifying each against the release's SHA256SUMS."""
    import httpx

    target = kriti_model_dir(models_dir)
    target.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            sums = _parse_sha256sums(client.get(f"{KRITI_RELEASE_URL}/SHA256SUMS.txt").raise_for_status().text)
            missing = [f for f in KRITI_FILES if f not in sums]
            if missing:
                return False, f"Release is missing checksums for: {', '.join(missing)}"

            sizes = {}
            for f in KRITI_FILES:
                head = client.head(f"{KRITI_RELEASE_URL}/{f}")
                sizes[f] = int(head.headers.get("content-length") or 0)
            total = max(1, sum(sizes.values()))
            done = 0

            for f in KRITI_FILES:
                final = target / f
                if final.exists() and _sha256(final) == sums[f]:
                    done += sizes[f]
                    continue
                partial = final.with_suffix(final.suffix + ".part")
                digest = hashlib.sha256()
                with client.stream("GET", f"{KRITI_RELEASE_URL}/{f}") as resp:
                    resp.raise_for_status()
                    with open(partial, "wb") as out:
                        for chunk in resp.iter_bytes(1 << 16):
                            out.write(chunk)
                            digest.update(chunk)
                            done += len(chunk)
                            if progress:
                                progress(min(1.0, done / total))
                if digest.hexdigest() != sums[f]:
                    partial.unlink(missing_ok=True)
                    return False, f"{f} failed its integrity check. Please try again."
                os.replace(partial, final)
        return True, "Kriti Nepali model ready."
    except Exception as e:
        return False, f"Couldn't download the Kriti model: {e}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class KritiEngine(STTEngine):
    """Nepali-only offline transcription; output is Devanagari with Kriti's danda restoration."""

    def __init__(self, models_dir: Path):
        self.models_dir = Path(models_dir)
        self._model = None
        self._lock = threading.Lock()
        self.loading_status = ""

    def is_available(self) -> bool:
        return is_kriti_downloaded(self.models_dir)

    def load(self, model_identifier: str = "kriti") -> bool:
        with self._lock:
            if self._model is not None:
                return True
            if not self.is_available():
                self.loading_status = "Not downloaded"
                return False
            try:
                from .kriti_onnx import KritiOnnx

                self._model = KritiOnnx(kriti_model_dir(self.models_dir), quantized=KRITI_QUANTIZED)
                self.loading_status = "Ready"
                print("[Kriti] Offline Nepali model loaded (ONNX Runtime).", file=sys.stderr)
                return True
            except Exception as e:
                self.loading_status = f"Load error: {e}"
                print(f"[Kriti] Failed to load: {e}", file=sys.stderr)
                return False

    def is_loaded(self) -> bool:
        return self._model is not None

    def transcribe(
        self,
        audio: np.ndarray,
        language: Optional[str] = "ne",
        task: str = "transcribe",
        initial_prompt: Optional[str] = None,
    ) -> str:
        if audio is None or len(audio) == 0 or task != "transcribe":
            return ""  # Kriti only transcribes Nepali; translation is left to the other engines
        if not self.load():
            return ""
        try:
            return self._model.transcribe(np.asarray(audio, dtype=np.float32))
        except Exception as e:
            print(f"[Kriti] Transcription error: {e}", file=sys.stderr)
            return ""

    def unload(self) -> None:
        with self._lock:
            self._model = None
