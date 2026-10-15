"""The saved voice profile: per-language results, learned mishearings, personal words, clips.

Everything stays in the app-data folder. The clips are the user's personal test set, so later
engine or model changes can be re-measured on their own voice.
"""

from __future__ import annotations

import json
import shutil
import sys
import wave
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from ..config import get_app_data_dir

PROFILE_VERSION = 1


def profile_dir() -> Path:
    return get_app_data_dir() / "voice_profile"


@dataclass
class VoiceProfile:
    version: int = PROFILE_VERSION
    updated: str = ""
    # language -> {"engine": id, "label": str, "accuracy": {engine id: 0..1}, "takes": int}
    languages: Dict[str, dict] = field(default_factory=dict)
    # [{"heard": "bery", "meant": "very", "language": "en", "count": 2}]
    mishearings: List[dict] = field(default_factory=list)
    words: List[str] = field(default_factory=list)
    role: str = ""  # scripts.ROLES id, e.g. "software"
    # [{"id", "file", "text", "language", "heard": {engine id: text}}]
    clips: List[dict] = field(default_factory=list)

    def accuracy(self, language: str) -> Optional[float]:
        info = self.languages.get(language)
        if not info:
            return None
        return (info.get("accuracy") or {}).get(info.get("engine"))

    def save(self, base: Optional[Path] = None) -> None:
        base = base or profile_dir()
        base.mkdir(parents=True, exist_ok=True)
        self.updated = datetime.now().isoformat(timespec="seconds")
        tmp = base / "profile.json.tmp"
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(base / "profile.json")

    @classmethod
    def load(cls, base: Optional[Path] = None) -> Optional["VoiceProfile"]:
        path = (base or profile_dir()) / "profile.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**known)
        except Exception as e:
            print(f"[VoiceProfile] Couldn't read {path}: {e}", file=sys.stderr)
            return None


def save_clip(audio: np.ndarray, clip_id: str, base: Optional[Path] = None, sample_rate: int = 16000) -> str:
    """Write a 16-bit mono WAV and return its path relative to the profile folder."""
    base = base or profile_dir()
    clips = base / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(clips / f"{clip_id}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return f"clips/{clip_id}.wav"


def delete_profile(base: Optional[Path] = None) -> None:
    shutil.rmtree(base or profile_dir(), ignore_errors=True)
