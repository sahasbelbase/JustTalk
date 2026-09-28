"""Application configuration and persistent settings manager."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


def get_default_shortcut() -> str:
    """Return default trigger shortcut depending on operating system."""
    if sys.platform == "darwin":
        return "fn"  # macOS Function key
    return "right_alt"  # Windows default push-to-talk


def get_default_action_shortcut() -> str:
    """Return default action mode shortcut (e.g. translate, search)."""
    if sys.platform == "darwin":
        return "fn_shift"
    return "ctrl_shift_space"


def get_app_data_dir() -> Path:
    """Return platform-appropriate configuration and data directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            path = Path(base) / "JustTalk"
        else:
            path = Path.home() / ".justtalk"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "JustTalk"
    else:
        path = Path.home() / ".config" / "justtalk"

    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppConfig:
    """User-configurable desktop application settings."""

    # STT Model
    model_tier: str = "balanced"  # "fast", "balanced", "quality"
    language: str = "en"
    audio_device_index: Optional[int] = None
    push_to_talk: bool = True  # True: hold to speak, False: toggle on/off

    # Gemini Cloud Layer & Resilience
    gemini_enabled: bool = True
    offline_mode: bool = False
    gemini_model: str = "gemini-3.8-flash"
    prompt_style: str = "subtle"  # "subtle", "formal", "concise"
    formatting_budget_sec: float = 3.0  # Max time budget before raw text fallback

    # Shortcuts
    shortcut: str = field(default_factory=get_default_shortcut)
    action_shortcut: str = field(default_factory=get_default_action_shortcut)
    max_recording_sec: float = 60.0  # Stuck-key safety limit

    # Text Insertion & Clipboard
    restore_clipboard: bool = True  # Restore prior clipboard contents after paste

    # History & Retention
    history_retention_days: int = 30  # 0 means never delete

    # System, Appearance & Window Behavior
    appearance: str = "system"  # "system", "light", "dark"
    open_window_on_launch: bool = True
    show_in_dock: bool = False  # macOS: show dock icon even when main window is closed
    close_to_tray: bool = True  # Windows: hide window to tray instead of keeping taskbar button
    start_minimized: bool = False
    launch_at_startup: bool = False
    onboarding_completed: bool = False

    # Optional Pill Indicators
    show_idle_indicator: bool = False
    sound_effects: bool = False

    @classmethod
    def get_config_path(cls) -> Path:
        return get_app_data_dir() / "config.json"

    @classmethod
    def load(cls) -> AppConfig:
        """Load configuration from disk, with legacy API key migration and default creation."""
        path = cls.get_config_path()
        if not path.exists():
            config = cls()
            config.save()
            return config

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # MIGRATE LEGACY API KEY:
            # If an old config contains a plaintext API key, migrate it into the OS keychain
            # and purge it from config.json immediately!
            migrated_key = None
            for key_field in ("api_key", "gemini_api_key"):
                if key_field in data and data[key_field]:
                    migrated_key = data.pop(key_field)

            if migrated_key:
                from .security import CredentialManager

                CredentialManager.set_api_key(migrated_key)
                print("[Config] Migrated legacy plaintext API key to secure OS keychain.", file=sys.stderr)

            # Filter valid keys for forward compatibility
            valid_keys = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
            filtered = {k: v for k, v in data.items() if k in valid_keys}
            config = cls(**filtered)

            # Re-save if legacy keys were stripped
            if migrated_key:
                config.save()

            return config
        except Exception as e:
            print(f"[Config] Error loading config: {e}. Falling back to defaults.", file=sys.stderr)
            return cls()

    def save(self) -> None:
        """Persist current configuration to disk as JSON."""
        path = self.get_config_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2)
        except Exception as e:
            print(f"Warning: Failed to save config: {e}", file=sys.stderr)

    def update(self, **kwargs: Any) -> None:
        """Update multiple configuration values and persist immediately."""
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        self.save()
