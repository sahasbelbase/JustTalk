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
    "quality": ModelTierInfo(
        tier_id="quality",
        display_name="Large V3 Turbo (Recommended - Best Accuracy & Speed)",
        model_name="large-v3-turbo",
        disk_size_mb=809,
        ram_mb=850,
        speed_factor="~450ms latency",
        accuracy_rating="State-of-the-Art",
        description="OpenAI's latest 809M flagship turbo model. 8x faster than large-v3 with virtually zero word mismatches.",
    ),
    "max": ModelTierInfo(
        tier_id="max",
        display_name="Large V3 (Maximum Depth)",
        model_name="large-v3",
        disk_size_mb=1550,
        ram_mb=1600,
        speed_factor="~1.4s latency",
        accuracy_rating="Deepest",
        description="Full 32-decoder-layer 1.55GB model for maximum deep-context multilingual audio.",
    ),
    "balanced": ModelTierInfo(
        tier_id="balanced",
        display_name="Balanced (Small - Lightweight)",
        model_name="small",
        disk_size_mb=466,
        ram_mb=450,
        speed_factor="~350ms latency",
        accuracy_rating="Standard",
        description="Lightweight 244M model for low-resource or battery-saving systems.",
    ),
    "fast": ModelTierInfo(
        tier_id="fast",
        display_name="Fast (Base - Legacy Low Spec)",
        model_name="base",
        disk_size_mb=142,
        ram_mb=200,
        speed_factor="~200ms latency",
        accuracy_rating="Basic",
        description="Minimal 74M model for legacy hardware with low RAM.",
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
        return TIERS.get(tier_id, TIERS["quality"])

    def get_model_path(self, tier_id: str) -> Path:
        info = self.get_tier_info(tier_id)
        user_path = self.models_dir / info.model_name
        if self._verify_directory_integrity(user_path):
            return user_path

        # Check bundled models directory (e.g. packaged by installer next to executable)
        candidates = []
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).parent / "models" / info.model_name)
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "models" / info.model_name)
        candidates.append(Path(__file__).resolve().parent.parent.parent / "models" / info.model_name)

        for candidate in candidates:
            if self._verify_directory_integrity(candidate):
                return candidate

        return user_path

    def is_model_downloaded(self, tier_id: str) -> bool:
        """
        Check if model weights exist locally in the models cache or bundled installer directory and are valid.
        Verifies model directory, required files (model.bin / model.safetensors, config.json),
        and verifies non-zero byte size to prevent corrupted or aborted downloads.
        """
        info = self.get_tier_info(tier_id)
        model_path = self.get_model_path(tier_id)

        # Check resolved path (user cache or bundled)
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
            tqdm_cls = None
            if progress_callback:
                import time
                from tqdm.auto import tqdm

                download_start_time = time.time()
                last_callback_time = 0.0

                class ProgressTqdm(tqdm):
                    def __init__(self, *args, **kwargs):
                        kwargs.pop("name", None)
                        super().__init__(*args, **kwargs)
                        self._expected_total = kwargs.get("total") or (info.disk_size_mb * 1024 * 1024)

                    def update(self, n=1):
                        super().update(n)
                        nonlocal last_callback_time
                        now = time.time()
                        # Throttle UI callback to max 10 updates/sec for smooth rendering
                        if now - last_callback_time < 0.1 and self.n < (self.total or self._expected_total):
                            return
                        last_callback_time = now

                        total_bytes = self.total if (self.total and self.total > 1_000_000) else self._expected_total
                        current_bytes = min(total_bytes, self.n)
                        pct = min(99.0, max(2.0, (current_bytes / max(1, total_bytes)) * 100.0))

                        current_mb = current_bytes / (1024 * 1024)
                        total_mb = total_bytes / (1024 * 1024)
                        elapsed = max(0.4, now - download_start_time)
                        rate_mb = current_mb / elapsed if current_mb > 0 else 0.0

                        speed_str = f"{rate_mb:.1f} MB/s" if rate_mb >= 1.0 else f"{int(rate_mb * 1024)} KB/s"
                        remaining_mb = max(0.0, total_mb - current_mb)
                        if rate_mb > 0.05 and remaining_mb > 0:
                            rem_sec = int(remaining_mb / rate_mb)
                            if rem_sec >= 60:
                                eta_str = f"~{rem_sec // 60}m {rem_sec % 60}s remaining"
                            else:
                                eta_str = f"~{rem_sec}s remaining"
                        else:
                            eta_str = "calculating time..."

                        progress_callback(
                            pct,
                            f"Downloading {info.display_name}: {current_mb:.1f} MB / {total_mb:.0f} MB ({pct:.0f}%) • {speed_str} • {eta_str}",
                        )

                tqdm_cls = ProgressTqdm

            huggingface_hub.snapshot_download(
                repo_id,
                local_dir=str(target_dir),
                allow_patterns=[
                    "config.json",
                    "preprocessor_config.json",
                    "model.bin",
                    "tokenizer.json",
                    "vocabulary.*",
                ],
                tqdm_class=tqdm_cls,
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

