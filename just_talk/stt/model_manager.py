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
        display_name="Fast / Small",
        model_name="base.en",
        disk_size_mb=140,
        ram_mb=200,
        speed_factor="~250ms latency",
        accuracy_rating="Good",
        description="Instantaneous inference on CPU. Optimal for older laptops.",
    ),
    "balanced": ModelTierInfo(
        tier_id="balanced",
        display_name="Balanced (Recommended)",
        model_name="small.en",
        disk_size_mb=460,
        ram_mb=450,
        speed_factor="~400ms latency",
        accuracy_rating="High",
        description="Exceptional accuracy, excellent punctuation, and handles technical jargon.",
    ),
    "quality": ModelTierInfo(
        tier_id="quality",
        display_name="High Quality / Multilingual",
        model_name="large-v3-turbo",
        disk_size_mb=809,
        ram_mb=850,
        speed_factor="~650ms latency",
        accuracy_rating="Maximum",
        description="State-of-the-art multilingual recognition across 99+ languages.",
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
        """Check if model weights exist locally in the models cache."""
        model_path = self.get_model_path(tier_id)
        if not model_path.exists():
            # Also check if huggingface-style directory or faster-whisper cached directory exists
            candidates = list(self.models_dir.glob(f"*{self.get_tier_info(tier_id).model_name}*"))
            return any(c.is_dir() and any(c.iterdir()) for c in candidates)
        return any(model_path.iterdir())

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
            progress_callback(10.0, f"Preparing to download {info.display_name}...")

        try:
            from faster_whisper import download_model

            if progress_callback:
                progress_callback(25.0, f"Downloading {info.model_name} (~{info.disk_size_mb} MB)...")

            download_model(
                info.model_name,
                output_dir=str(self.get_model_path(tier_id)),
            )

            if progress_callback:
                progress_callback(100.0, f"{info.display_name} ready!")
            return True
        except Exception as e:
            print(f"[ModelManager] Model download error: {e}", file=sys.stderr)
            if progress_callback:
                progress_callback(-1.0, f"Download failed: {e}")
            return False
