"""Whisper model catalogue, cache directory manager, and downloader."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from ..config import get_app_data_dir


@dataclass
class ModelTierInfo:
    """Metadata describing an STT model tier."""

    tier_id: str
    display_name: str
    model_name: str  # faster-whisper model string (e.g. "small.en")
    disk_size_mb: int
    ram_mb: int
    speed_factor: str
    accuracy_rating: str
    description: str


TIERS: Dict[str, ModelTierInfo] = {
    "fast": ModelTierInfo(
        tier_id="fast",
        display_name="Fast (Multilingual)",
        model_name="base",
        disk_size_mb=142,
        ram_mb=200,
        speed_factor="~250ms latency",
        accuracy_rating="Good",
        description="Instantaneous inference. Supports Nepali, English, German, French, Italian, Mandarin + 90 languages.",
    ),
    "balanced": ModelTierInfo(
        tier_id="balanced",
        display_name="Balanced (Multilingual - Recommended)",
        model_name="small",
        disk_size_mb=466,
        ram_mb=450,
        speed_factor="~400ms latency",
        accuracy_rating="High",
        description="Exceptional accuracy across Nepali, English, German, French, Italian, and Mandarin with robust punctuation.",
    ),
    "quality": ModelTierInfo(
        tier_id="quality",
        display_name="High Quality (Multilingual Turbo)",
        model_name="large-v3-turbo",
        disk_size_mb=809,
        ram_mb=850,
        speed_factor="~650ms latency",
        accuracy_rating="Maximum",
        description="State-of-the-art multilingual recognition across 99+ languages with maximum nuance.",
    ),
}


class ModelManager:
    """Manages Whisper model storage and pre-flight downloads."""

    def __init__(self, models_dir: Optional[Path] = None):
        if models_dir is None:
            self.models_dir = get_app_data_dir() / "models"
        else:
            self.models_dir = models_dir
        self.models_dir.mkdir(parents=True, exist_ok=True)

    def get_tier_info(self, tier_id: str) -> ModelTierInfo:
        return TIERS.get(tier_id, TIERS["balanced"])

    def get_model_path(self, tier_id: str) -> Path:
        info = self.get_tier_info(tier_id)
        return self.models_dir / info.model_name

    def is_model_downloaded(self, tier_id: str) -> bool:
        """
        Check if model weights exist locally in the models cache and are valid.
        Verifies model directory, required files (model.bin / model.safetensors, config.json),
        and verifies non-zero byte size to prevent corrupted or aborted downloads.
        """
        info = self.get_tier_info(tier_id)
        model_path = self.get_model_path(tier_id)

        # Check direct named folder
        if self._verify_directory_integrity(model_path):
            return True

        # Check huggingface snapshot style folders (e.g. models--Systran--faster-whisper-small)
        pattern = f"*{info.model_name}*"
        for candidate in self.models_dir.glob(pattern):
            if candidate.is_dir() and self._verify_directory_integrity(candidate):
                return True

        return False

    def _verify_directory_integrity(self, dir_path: Path) -> bool:
        """Verify that a directory contains a valid Whisper model."""
        if not dir_path.exists() or not dir_path.is_dir():
            return False

        # Must contain config.json and model weights
        has_config = (dir_path / "config.json").exists()
        has_tokenizer = (dir_path / "tokenizer.json").exists() or (dir_path / "vocabulary.txt").exists() or (dir_path / "vocabulary.json").exists()
        
        weight_files = list(dir_path.glob("model.bin")) + list(dir_path.glob("model.safetensors"))
        if not weight_files:
            # Check snapshots folder inside huggingface hub cache
            snapshots = dir_path / "snapshots"
            if snapshots.exists() and snapshots.is_dir():
                for snap in snapshots.iterdir():
                    if snap.is_dir() and self._verify_directory_integrity(snap):
                        return True
            return False

        # Weight file must be at least 15MB (even tiny is >30MB; corrupted files are typically 0 or few KB)
        valid_weights = any(w.stat().st_size > 15_000_000 for w in weight_files)
        return has_config and valid_weights

    def download_model(
        self,
        tier_id: str,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> bool:
        """
        Download the model weights from Hugging Face via faster-whisper.
        Notifies progress_callback(percentage, status_text).
        """
        info = self.get_tier_info(tier_id)
        if progress_callback:
            progress_callback(5.0, f"Connecting to download {info.display_name}...")

        target_dir = self.get_model_path(tier_id)
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            import huggingface_hub
            from faster_whisper.utils import _MODELS

            repo_id = _MODELS.get(info.model_name, f"Systran/faster-whisper-{info.model_name}")

            # Custom progress hook using huggingface_hub snapshot_download
            class ProgressTqdm:
                def __init__(self, *args, **kwargs):
                    self.total = kwargs.get("total") or 1
                    self.n = 0
                    self.desc = kwargs.get("desc") or ""

                def update(self, n=1):
                    self.n += n
                    pct = min(98.0, max(5.0, (self.n / self.total) * 100.0))
                    if progress_callback:
                        progress_callback(pct, f"Downloading {info.display_name} ({pct:.0f}%)...")

                def close(self):
                    pass

            huggingface_hub.snapshot_download(
                repo_id,
                local_dir=str(target_dir),
                local_dir_use_symlinks=False,
                allow_patterns=[
                    "config.json",
                    "preprocessor_config.json",
                    "model.bin",
                    "tokenizer.json",
                    "vocabulary.*",
                ],
                tqdm_class=ProgressTqdm,
            )

            # Verify the downloaded files
            if not self._verify_directory_integrity(target_dir):
                raise ValueError("Model download completed but files failed integrity verification.")

            if progress_callback:
                progress_callback(100.0, f"{info.display_name} ready!")
            print(f"[ModelManager] {info.display_name} downloaded and verified successfully.", file=sys.stderr)
            return True

        except Exception as e:
            print(f"[ModelManager] Model download error: {e}", file=sys.stderr)
            if progress_callback:
                progress_callback(-1.0, f"Download failed: {e}")
            return False

