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
    "nepali_conformer": ModelTierInfo(
        tier_id="nepali_conformer",
        display_name="Ampixa NepaliConformer (Offline · 121M)",
        model_name="nepali-conformer-offline",
        disk_size_mb=462,
        ram_mb=350,
        speed_factor="~180ms latency",
        accuracy_rating="33.8% WER (Call-Center Tested)",
        description="Ampixa Labs' specialized offline Nepali ASR trained on 1,655 hours conversational speech (33.8% WER vs 96.3% Whisper).",
    ),
    "small.en": ModelTierInfo(
        tier_id="small.en",
        display_name="English Balanced (small.en · 461 MB)",
        model_name="small.en",
        disk_size_mb=461,
        ram_mb=450,
        speed_factor="~250ms latency",
        accuracy_rating="High English Accuracy",
        description="Dedicated English-only model. Faster than multilingual, minimal memory, zero foreign character hallucinations.",
    ),
    "base.en": ModelTierInfo(
        tier_id="base.en",
        display_name="English Fast (base.en · 142 MB)",
        model_name="base.en",
        disk_size_mb=142,
        ram_mb=200,
        speed_factor="~150ms latency",
        accuracy_rating="Standard English",
        description="Ultralight English-only model. Instant download for fast dictation and minimal laptop resource usage.",
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
    "nepali_conformer": (
        "ampixa/nepali-conformer-offline",
        [
            ("README.md", 3127),
            ("nepali_conformer_offline.nemo", 484669440),
        ],
    ),
    "small.en": (
        "Systran/faster-whisper-small.en",
        [
            ("config.json", 2657),
            ("tokenizer.json", 2128466),
            ("vocabulary.txt", 422309),
            ("model.bin", 483545366),
        ],
    ),
    "base.en": (
        "Systran/faster-whisper-base.en",
        [
            ("config.json", 2227),
            ("tokenizer.json", 2128466),
            ("vocabulary.txt", 422309),
            ("model.bin", 145216508),
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
        self._global_listeners: list[Callable[[str, float, str], None]] = []
        self._active_progress: Dict[str, Tuple[float, str]] = {}
        self._cancel_flags: Dict[str, bool] = {}
        self._download_lock = threading.Lock()

    def register_global_listener(self, callback: Callable[[str, float, str], None]) -> None:
        """Register a callback (tier_id, pct, msg) invoked on any model download progress or status change."""
        with self._download_lock:
            if callback not in self._global_listeners:
                self._global_listeners.append(callback)
            # Replay active downloads immediately so new UI components catch up
            for tid, prog in list(self._active_progress.items()):
                try:
                    callback(tid, prog[0], prog[1])
                except Exception:
                    pass

    def unregister_global_listener(self, callback: Callable[[str, float, str], None]) -> None:
        with self._download_lock:
            if callback in self._global_listeners:
                self._global_listeners.remove(callback)

    def is_downloading(self, tier_id: Optional[str] = None) -> bool:
        with self._download_lock:
            if tier_id is not None:
                thread = self._download_threads.get(tier_id)
                return thread is not None and thread.is_alive()
            # If tier_id is None, check if ANY download is currently active
            return any(t is not None and t.is_alive() for t in self._download_threads.values())

    def get_any_active_download(self) -> Optional[Tuple[str, float, str]]:
        """Return (tier_id, pct, msg) for the first active download in progress, if any."""
        with self._download_lock:
            for tid, thread in self._download_threads.items():
                if thread and thread.is_alive() and tid in self._active_progress:
                    pct, msg = self._active_progress[tid]
                    return tid, pct, msg
            return None

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
        """Verify that a directory contains a valid Whisper or Conformer model."""
        if not dir_path.exists() or not dir_path.is_dir():
            return False

        # 1. Check for NeMo offline model archive (Ampixa NepaliConformer)
        nemo_files = list(dir_path.glob("*.nemo"))
        if nemo_files:
            return any(f.stat().st_size > 20_000_000 for f in nemo_files)

        # 2. Check for Whisper CTranslate2/faster-whisper models
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

    def validate_custom_model_target(self, target: str) -> tuple[bool, str]:
        """
        Validate whether target is a valid local CTranslate2 directory or syntactically valid Hugging Face repo ID.
        """
        if not target or not target.strip():
            return False, "Model path or repo ID is empty."
        clean = target.strip()
        local_p = Path(clean)
        if local_p.exists():
            if not local_p.is_dir():
                return False, f"Path '{clean}' is a file, but a model directory is required."
            if not self._verify_directory_integrity(local_p):
                return False, f"Directory '{clean}' is missing config.json or valid model weights (model.bin / model.safetensors)."
            return True, f"Valid local model directory ({local_p.name})"

        # If not a local path, verify it matches standard Hugging Face repo pattern (e.g. org/repo or repo-name)
        if "/" in clean or len(clean.split()) == 1:
            return True, f"Hugging Face repository: {clean}"

        return False, f"Target '{clean}' is neither an existing directory nor a valid Hugging Face repository."

    def get_models_for_languages(
        self,
        spoken_languages: list[str],
        tier_preference: str = "quality",
        nepali_engine: str = "whisper",
    ) -> list[str]:
        """Return the minimal list of model tier IDs required for the selected spoken languages."""
        langs = set(spoken_languages or ["en"])
        models: list[str] = []
        needs_multilingual = False

        for lang in langs:
            if lang in ("de", "fr", "es", "zh", "it", "ja", "ko", "hi", "pt", "ru", "ar", "nl", "pl", "tr", "sv", "vi"):
                needs_multilingual = True

        if "ne" in langs or "ne_en" in langs:
            if nepali_engine == "conformer":
                models.append("nepali_conformer")
            else:
                needs_multilingual = True

        if needs_multilingual:
            models.append(tier_preference if tier_preference in ("quality", "balanced", "fast") else "quality")
        else:
            # English only
            if "en" in langs and not ("ne" in langs and len(langs) == 1 and nepali_engine == "conformer"):
                models.append("small.en" if tier_preference in ("quality", "balanced") else "base.en")

        return list(dict.fromkeys(models))

    def are_required_models_downloaded(
        self,
        spoken_languages: list[str],
        tier_preference: str = "quality",
        nepali_engine: str = "whisper",
    ) -> tuple[bool, list[str]]:
        """Check if all models needed for the spoken languages are downloaded."""
        required = self.get_models_for_languages(spoken_languages, tier_preference, nepali_engine=nepali_engine)
        missing = [t for t in required if not self.is_model_downloaded(t)]
        return len(missing) == 0, missing

    def get_total_download_size_mb(self, tier_ids: list[str]) -> int:
        """Return combined total MB required for downloading given tier IDs."""
        total = 0
        for tid in tier_ids:
            info = self.get_tier_info(tid)
            total += info.disk_size_mb
        return total


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
                globals_list = list(self._global_listeners)
            for cb in listeners:
                try:
                    cb(pct, text)
                except Exception:
                    pass
            for gcb in globals_list:
                try:
                    gcb(tier_id, pct, text)
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
                        import os
                        hf_tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
                        if not hf_tok:
                            tok_file = Path.home() / ".cache" / "huggingface" / "token"
                            if tok_file.exists():
                                try:
                                    hf_tok = tok_file.read_text().strip()
                                except Exception:
                                    pass
                        if hf_tok:
                            headers["Authorization"] = f"Bearer {hf_tok}"
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
                                elif resp.status_code in (401, 403):
                                    if tier_id == "nepali_conformer":
                                        err_msg = (
                                            f"Ampixa NepaliConformer is a gated model on Hugging Face (HTTP {resp.status_code}). "
                                            "Request access at https://huggingface.co/ampixa/nepali-conformer-offline or use OpenAI Whisper for Nepali."
                                        )
                                    else:
                                        err_msg = f"Repository '{repo_id}' requires authentication or is gated (HTTP {resp.status_code})."
                                    print(f"[ModelManager] {err_msg}", file=sys.stderr)
                                    notify(-1.0, err_msg)
                                    return False
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

