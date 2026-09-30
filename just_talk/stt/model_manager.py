"""Whisper model catalogue, cache directory manager, and downloader."""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

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
        disk_size_mb=1546,
        ram_mb=850,
        speed_factor="~450ms latency",
        accuracy_rating="State-of-the-Art",
        description="OpenAI's latest 809M flagship turbo model. 8x faster than large-v3 with virtually zero word mismatches.",
    ),
    "max": ModelTierInfo(
        tier_id="max",
        display_name="Large V3 (Maximum Depth)",
        model_name="large-v3",
        disk_size_mb=3090,
        ram_mb=1600,
        speed_factor="~1.4s latency",
        accuracy_rating="Deepest",
        description="Full 32-decoder-layer 3.0GB model for maximum deep-context multilingual audio.",
    ),
    "balanced": ModelTierInfo(
        tier_id="balanced",
        display_name="Balanced (Small - Lightweight)",
        model_name="small",
        disk_size_mb=488,
        ram_mb=450,
        speed_factor="~350ms latency",
        accuracy_rating="Standard",
        description="Lightweight 244M model for low-resource or battery-saving systems.",
    ),
    "fast": ModelTierInfo(
        tier_id="fast",
        display_name="Fast (Base - Legacy Low Spec)",
        model_name="base",
        disk_size_mb=145,
        ram_mb=200,
        speed_factor="~200ms latency",
        accuracy_rating="Basic",
        description="Minimal 74M model for legacy hardware with low RAM.",
    ),
}


# Exact HuggingFace repositories and deterministic file manifests for instant error-free streaming
TIER_REPOS: Dict[str, Tuple[str, list[Tuple[str, int]]]] = {
    "quality": (
        "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        [
            ("config.json", 2263),
            ("preprocessor_config.json", 340),
            ("tokenizer.json", 2710337),
            ("vocabulary.json", 1068114),
            ("model.bin", 1617884929),
        ],
    ),
    "max": (
        "Systran/faster-whisper-large-v3",
        [
            ("config.json", 2394),
            ("preprocessor_config.json", 340),
            ("tokenizer.json", 2480617),
            ("vocabulary.json", 1068114),
            ("model.bin", 3087284237),
        ],
    ),
    "balanced": (
        "Systran/faster-whisper-small",
        [
            ("config.json", 2370),
            ("tokenizer.json", 2203239),
            ("vocabulary.txt", 459861),
            ("model.bin", 483546902),
        ],
    ),
    "fast": (
        "Systran/faster-whisper-base",
        [
            ("config.json", 2309),
            ("tokenizer.json", 2203239),
            ("vocabulary.txt", 459861),
            ("model.bin", 145217532),
        ],
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
        self._download_threads: Dict[str, threading.Thread] = {}
        self._progress_listeners: Dict[str, list[Callable[[float, str], None]]] = {}
        self._active_progress: Dict[str, Tuple[float, str]] = {}
        self._cancel_flags: Dict[str, bool] = {}
        self._download_lock = threading.Lock()

    def is_downloading(self, tier_id: str) -> bool:
        with self._download_lock:
            thread = self._download_threads.get(tier_id)
            return thread is not None and thread.is_alive()

    def get_active_progress(self, tier_id: str) -> Optional[Tuple[float, str]]:
        with self._download_lock:
            return self._active_progress.get(tier_id)

    def cancel_download(self, tier_id: str) -> None:
        with self._download_lock:
            self._cancel_flags[tier_id] = True

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
        force_redownload: bool = False,
    ) -> bool:
        """
        Download Whisper model weights using high-speed streaming chunk HTTP requests with
        per-byte progress calculation, transfer rate speed, ETA, and resume support.
        If a download for this tier is already in progress, registers the callback to receive live updates.
        """
        info = self.get_tier_info(tier_id)

        # 1. Check if download is already in progress
        with self._download_lock:
            if tier_id in self._download_threads and self._download_threads[tier_id].is_alive():
                if progress_callback:
                    if tier_id not in self._progress_listeners:
                        self._progress_listeners[tier_id] = []
                    self._progress_listeners[tier_id].append(progress_callback)
                    if tier_id in self._active_progress:
                        pct, msg = self._active_progress[tier_id]
                        try:
                            progress_callback(pct, msg)
                        except Exception:
                            pass
                thread = self._download_threads[tier_id]
            else:
                thread = None

        if thread is not None:
            thread.join()
            return self.is_model_downloaded(tier_id)

        # 2. Register current thread and listeners
        self._cancel_flags[tier_id] = False
        with self._download_lock:
            self._download_threads[tier_id] = threading.current_thread()
            if tier_id not in self._progress_listeners:
                self._progress_listeners[tier_id] = []
            if progress_callback and progress_callback not in self._progress_listeners[tier_id]:
                self._progress_listeners[tier_id].append(progress_callback)

        def notify(pct: float, text: str):
            with self._download_lock:
                self._active_progress[tier_id] = (pct, text)
                listeners = list(self._progress_listeners.get(tier_id, []))
            for cb in listeners:
                try:
                    cb(pct, text)
                except Exception:
                    pass

        target_dir = self.models_dir / info.model_name
        target_dir.mkdir(parents=True, exist_ok=True)

        # If user explicitly requested Re-download, purge old destination files
        if force_redownload:
            notify(2.0, f"Clearing existing cache for {info.display_name}...")
            try:
                for old_f in target_dir.glob("*"):
                    if old_f.is_file():
                        old_f.unlink(missing_ok=True)
            except Exception as e:
                print(f"[ModelManager] Note: cache clear warning: {e}", file=sys.stderr)

        notify(1.0, f"Connecting to repository for {info.display_name}...")

        try:
            import time
            import httpx

            # Resolve repository ID and file manifest
            if tier_id in TIER_REPOS:
                repo_id, files_meta = TIER_REPOS[tier_id]
            else:
                # Generic fallback
                repo_id = f"Systran/faster-whisper-{info.model_name}"
                files_meta = [
                    ("config.json", 2400),
                    ("tokenizer.json", 2500000),
                    ("vocabulary.txt", 460000),
                    ("model.bin", int(info.disk_size_mb * 1024 * 1024 * 0.98)),
                ]

            total_bytes = sum(sz for _, sz in files_meta)
            total_mb = total_bytes / (1024 * 1024)

            # Check files already completely downloaded
            downloaded_bytes = 0
            files_to_fetch = []
            for fn, expected_sz in files_meta:
                dest_file = target_dir / fn
                if not force_redownload and dest_file.exists() and dest_file.stat().st_size > 0:
                    actual_sz = dest_file.stat().st_size
                    # Small metadata files (<10MB) must match exact or non-zero size
                    # Big weights files must be within 1% of expected size
                    if expected_sz > 15_000_000:
                        is_complete = abs(actual_sz - expected_sz) < 100_000 or actual_sz >= expected_sz
                    else:
                        is_complete = actual_sz > 0
                    if is_complete:
                        downloaded_bytes += actual_sz
                        continue
                files_to_fetch.append((fn, expected_sz))

            if not files_to_fetch and self._verify_directory_integrity(target_dir):
                notify(100.0, f"✓ {info.display_name} ready in cache ({total_mb:.0f} MB)!")
                return True

            start_time = time.time()
            session_start_bytes = downloaded_bytes
            last_notify_time = 0.0

            # Use dedicated HTTP timeouts: 15s connect, 45s read
            timeout_cfg = httpx.Timeout(connect=15.0, read=45.0, write=30.0, pool=30.0)

            with httpx.Client(follow_redirects=True, timeout=timeout_cfg) as client:
                for fn, expected_sz in files_to_fetch:
                    if self._cancel_flags.get(tier_id, False):
                        notify(-1.0, "Download cancelled by user.")
                        return False

                    dest_file = target_dir / fn
                    part_file = target_dir / f"{fn}.part"
                    file_url = f"https://huggingface.co/{repo_id}/resolve/main/{fn}"

                    # Up to 3 automatic resume retries per file on transient network disconnects
                    max_file_retries = 3
                    file_done = False

                    for retry_idx in range(max_file_retries):
                        if self._cancel_flags.get(tier_id, False):
                            notify(-1.0, "Download cancelled.")
                            return False

                        existing_bytes = part_file.stat().st_size if part_file.exists() else 0
                        headers = {"User-Agent": "JustTalk-Desktop/1.0"}
                        file_mode = "wb"
                        bytes_added_to_overall = 0

                        if existing_bytes > 0:
                            headers["Range"] = f"bytes={existing_bytes}-"
                            file_mode = "ab"
                            bytes_added_to_overall = existing_bytes
                            downloaded_bytes += existing_bytes

                        try:
                            with client.stream("GET", file_url, headers=headers) as resp:
                                if resp.status_code == 416:
                                    # Requested range not satisfiable (part already complete)
                                    pass
                                elif resp.status_code not in (200, 206):
                                    resp.raise_for_status()
                                else:
                                    if resp.status_code == 200 and existing_bytes > 0:
                                        # Server did not accept Range header, restart file
                                        downloaded_bytes -= existing_bytes
                                        bytes_added_to_overall = 0
                                        file_mode = "wb"
                                        existing_bytes = 0

                                    with open(part_file, file_mode) as f:
                                        for chunk in resp.iter_bytes(chunk_size=524288):  # 512 KB chunks
                                            if self._cancel_flags.get(tier_id, False):
                                                notify(-1.0, "Download cancelled.")
                                                return False
                                            if not chunk:
                                                continue
                                            f.write(chunk)
                                            downloaded_bytes += len(chunk)

                                            now = time.time()
                                            if now - last_notify_time >= 0.10:  # 10 Hz UI updates
                                                last_notify_time = now
                                                curr_mb = downloaded_bytes / (1024 * 1024)
                                                pct = min(99.0, max(2.0, (downloaded_bytes / max(1, total_bytes)) * 100.0))
                                                elapsed = max(0.4, now - start_time)
                                                rate_mb = max(0.01, (downloaded_bytes - session_start_bytes) / (1024 * 1024) / elapsed)
                                                speed_str = f"{rate_mb:.1f} MB/s" if rate_mb >= 1.0 else f"{int(rate_mb * 1024)} KB/s"
                                                rem_mb = max(0.0, total_mb - curr_mb)
                                                if rate_mb > 0.05 and rem_mb > 0:
                                                    rem_sec = int(rem_mb / rate_mb)
                                                    if rem_sec >= 60:
                                                        eta_str = f"~{rem_sec // 60}m {rem_sec % 60:02d}s left"
                                                    else:
                                                        eta_str = f"~{rem_sec}s left"
                                                else:
                                                    eta_str = "calculating time..."

                                                notify(
                                                    pct,
                                                    f"Downloading {info.display_name}: {curr_mb:.1f} MB / {total_mb:.0f} MB ({pct:.0f}%) • {speed_str} • {eta_str}",
                                                )

                            # Atomically promote .part to final destination
                            if part_file.exists():
                                part_file.replace(dest_file)
                            file_done = True
                            break

                        except Exception as file_err:
                            print(f"[ModelManager] Retry {retry_idx + 1}/{max_file_retries} for {fn} after error: {file_err}", file=sys.stderr)
                            # Roll back overall counter to avoid double counting on next loop
                            downloaded_bytes -= bytes_added_to_overall
                            if retry_idx + 1 < max_file_retries:
                                time.sleep(1.5)
                            else:
                                raise file_err

                    if not file_done:
                        raise RuntimeError(f"Failed to download {fn} after {max_file_retries} attempts.")

            if not self._verify_directory_integrity(target_dir):
                raise ValueError("Model download completed but files failed integrity verification.")

            notify(100.0, f"✓ {info.display_name} ready ({total_mb:.0f} MB)!")
            print(f"[ModelManager] {info.display_name} downloaded and verified successfully.", file=sys.stderr)
            return True

        except Exception as e:
            print(f"[ModelManager] Streaming download error: {e}", file=sys.stderr)
            notify(-1.0, f"Download failed: {e}")
            return False
        finally:
            with self._download_lock:
                self._download_threads.pop(tier_id, None)
                self._progress_listeners.pop(tier_id, None)
                self._active_progress.pop(tier_id, None)

