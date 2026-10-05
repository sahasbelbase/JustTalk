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
    try:
        home = Path.home()
    except Exception:
        home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")

    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            path = Path(base) / "JustTalk"
        else:
            path = home / ".justtalk"
    elif sys.platform == "darwin":
        path = home / "Library" / "Application Support" / "JustTalk"
    else:
        path = home / ".config" / "justtalk"

    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        path = Path(".") / ".justtalk"
        path.mkdir(parents=True, exist_ok=True)
    return path


SUPPORTED_LANGUAGES: list[tuple[str, str]] = [
    ("English (Default)", "en"),
    ("Mixed Nepali + English (Nepglish)", "ne_en"),
    ("Nepali (नेपाली)", "ne"),
    ("Spanish (Español)", "es"),
    ("French (Français)", "fr"),
    ("German (Deutsch)", "de"),
    ("Mandarin Chinese (中文)", "zh"),
    ("Auto-Detect All Languages", "auto"),
]

CORE_SPOKEN_LANGUAGES: list[dict[str, str]] = [
    {"code": "en", "name": "English", "native": "English", "flag": "🇬🇧 / 🇺🇸", "desc": "Default · Fast & lightweight"},
    {"code": "ne", "name": "Nepali & Nepglish", "native": "नेपाली", "flag": "🇳🇵", "desc": "Multilingual Whisper (100% Offline & Free)"},
    {"code": "de", "name": "German", "native": "Deutsch", "flag": "🇩🇪", "desc": "Multilingual model"},
    {"code": "fr", "name": "French", "native": "Français", "flag": "🇫🇷", "desc": "Multilingual model"},
    {"code": "es", "name": "Spanish", "native": "Español", "flag": "🇪🇸", "desc": "Multilingual model"},
    {"code": "zh", "name": "Mandarin Chinese", "native": "中文 (普通话)", "flag": "🇨🇳", "desc": "Multilingual model"},
]

ADDITIONAL_LANGUAGES: list[tuple[str, str]] = [
    ("Italian (Italiano)", "it"),
    ("Japanese (日本語)", "ja"),
    ("Korean (한국어)", "ko"),
    ("Hindi (हिन्दी)", "hi"),
    ("Portuguese (Português)", "pt"),
    ("Russian (Русский)", "ru"),
    ("Arabic (العربية)", "ar"),
    ("Dutch (Nederlands)", "nl"),
    ("Polish (Polski)", "pl"),
    ("Turkish (Türkçe)", "tr"),
    ("Swedish (Svenska)", "sv"),
    ("Vietnamese (Tiếng Việt)", "vi"),
]


@dataclass
class AppConfig:
    """User-configurable desktop application settings."""

    # Speech-to-Text Engine Provider
    # "os_native": Built-in Apple/Windows Dictation (zero download, zero login, instant on-device) [Default]
    # "google_web": Google Web Speech API (zero download, zero login, free cloud, first-class Nepali)
    # "whisper": Local faster-whisper / BYOM (offline, requires model download)
    stt_provider: str = "os_native"

    # STT Model & Spoken Languages (used when stt_provider == "whisper")
    model_tier: str = "quality"  # Default: "quality" (large-v3-turbo), "max" (large-v3), "balanced" (small), "fast" (base)
    language: str = "en"  # Active language: "en", "ne_en", "ne", "es", "fr", "de", "zh", "auto"
    spoken_languages: list[str] = field(default_factory=lambda: ["en"])  # Languages the user actively speaks
    nepali_asr_engine: str = "whisper"  # Default: "whisper" (100% out-of-the-box, no tokens needed) or "conformer"
    speech_mode: str = "transcribe"  # "transcribe" (write what I say) or "translate" (translate speech to English)
    audio_device_index: Optional[int] = None
    push_to_talk: bool = False  # False: Tap-to-Toggle (Tap to start, Tap to stop) [Default], True: hold to speak

    def get_required_model_tiers(self, for_current_provider: bool = False) -> list[str]:
        """Compute the minimal set of model tiers required for user's selected spoken languages."""
        # Non-whisper providers (os_native, google_web) require ZERO local models if checking active provider
        if for_current_provider and getattr(self, "stt_provider", "whisper") != "whisper":
            return []

        langs = set(self.spoken_languages or ["en"])
        models: list[str] = []
        needs_multilingual = False

        for lang in langs:
            if lang in ("de", "fr", "es", "zh") or lang in [code for _, code in ADDITIONAL_LANGUAGES]:
                needs_multilingual = True

        if "ne" in langs or "ne_en" in langs or self.language in ("ne", "ne_en"):
            if self.nepali_asr_engine == "conformer":
                models.append("nepali_conformer")
            else:
                needs_multilingual = True

        if needs_multilingual:
            models.append(self.model_tier if self.model_tier in ("quality", "balanced", "fast") else "quality")
        else:
            # English only
            if "en" in langs:
                models.append("small.en" if self.model_tier in ("quality", "balanced") else "base.en")

        return list(dict.fromkeys(models))


    # Custom Vocabulary (comma-separated words, personal names, product terms)
    custom_vocabulary: str = ""

    # Voice Isolation & Speaker Identification
    voice_isolation_enabled: bool = True  # DeepFilterNet v3 noise & laptop audio cancellation
    speaker_id_enabled: bool = True       # WeSpeaker CAM++ speaker recognition & tagging
    target_speaker_isolation: bool = False  # If True, ignore speech from unrecognized speakers
    two_phase_emission: bool = True       # Typeless-style: instant draft emission + AI polish
    mute_audio_while_recording: bool = True  # Mute computer sound (music, videos, Reels) while speaking

    # AI Formatting Layer & Resilience
    gemini_enabled: bool = True
    offline_mode: bool = False
    gemini_model: str = "gemini-3.8-flash"
    prompt_style: str = "subtle"  # "subtle", "formal", "concise"
    formatting_budget_sec: float = 2.0  # Max time budget before raw text fallback

    # Multi-Provider AI Configuration
    ai_provider: str = "gemini"  # Active provider ID: 'gemini', 'ollama', 'openai', 'anthropic', 'grok', 'groq', 'openrouter', 'deepseek', 'custom'
    ai_model: str = ""  # Model override (empty = use provider default)
    custom_api_base_url: str = ""  # Base URL for 'custom' or 'ollama' provider
    custom_model_name: str = ""  # Model name for 'custom' provider

    # Bring Your Own Model (BYOM) Configuration
    stt_model_source: str = "bundled"  # "bundled" or "custom"
    custom_stt_model_path: str = ""    # Hugging Face repo ID (e.g. Systran/faster-whisper-small) or local path
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""             # e.g. "qwen2.5-coder:7b", "llama3.2:3b"

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
    show_in_dock: bool = True  # macOS: show dock icon even when main window is closed
    close_to_tray: bool = True  # Windows: hide window to tray instead of keeping taskbar button
    start_minimized: bool = False
    launch_at_startup: bool = False
    onboarding_completed: bool = False

    # Optional Pill Indicators
    show_idle_indicator: bool = False
    sound_effects: bool = False

    # Words-saved formula speeds (editable in Settings)
    speaking_speed_wpm: int = 160  # Default: 160 wpm speaking rate
    typing_speed_wpm: int = 40     # Default: 40 wpm typing rate

    # Writing Conventions per context (context_label → {option: value})
    # Populated with sensible defaults on first use; user can override per context.
    conventions: dict = field(default_factory=lambda: {
        "sql": {
            "keyword_case": "upper",          # upper | lower | title
            "naming_style": "PascalCase",     # PascalCase | snake_case | camelCase
            "schema_prefix": True,            # add schema prefix (e.g. dbo.)
            "aliases": True,                  # add short table aliases
            "dialect": "tsql",                # tsql | mysql | postgres | sqlite | ansi
            "indent_width": 4,
        },
        "python": {
            "naming_style": "snake_case",     # PEP 8
            "indent_width": 4,
            "quote_style": "double",          # double | single
            "type_hints": True,
            "docstring_style": "google",      # google | numpy | sphinx
        },
        "javascript": {
            "naming_style": "camelCase",      # Google JS Style
            "indent_width": 2,
            "quote_style": "single",
            "semicolons": True,
            "trailing_commas": True,
        },
        "typescript": {
            "naming_style": "camelCase",
            "indent_width": 2,
            "quote_style": "single",
            "semicolons": True,
            "trailing_commas": True,
            "strict": True,
        },
        "java": {
            "naming_style": "camelCase",      # Oracle Code Conventions
            "indent_width": 4,
            "brace_style": "K&R",
        },
        "csharp": {
            "naming_style": "PascalCase",     # Microsoft .NET conventions
            "indent_width": 4,
            "var_keyword": True,
            "brace_style": "Allman",
        },
        "go": {
            "naming_style": "camelCase",      # gofmt standard
            "indent_width": 1,               # gofmt uses real tabs
            "indent_char": "tab",
        },
        "rust": {
            "naming_style": "snake_case",     # rustfmt standard
            "indent_width": 4,
        },
        "php": {
            "naming_style": "camelCase",      # PSR-12
            "indent_width": 4,
            "quote_style": "single",
        },
        "text": {
            "style": "plain",                 # plain | formal | casual | bullet
            "no_em_dash": True,
            "no_filler_openers": True,
        },
    })

    @property
    def has_completed_onboarding(self) -> bool:
        return self.onboarding_completed

    @has_completed_onboarding.setter
    def has_completed_onboarding(self, val: bool) -> None:
        self.onboarding_completed = val

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

            # If open_window_on_launch is True (default), ensure start_minimized is False
            # so the application window opens immediately when launched by the user.
            if filtered.get("open_window_on_launch", True):
                filtered["start_minimized"] = False

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
