"""Secure and frictionless API key storage without annoying OS Keychain password popups."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

SERVICE_NAME = "JustTalkVoiceInput"
KEY_ACCOUNT = "gemini_api_key"
NVIDIA_KEY_ACCOUNT = "nvidia_api_key"


# Provider-specific credential keys
PROVIDER_KEY_ACCOUNTS = {
    'gemini': 'gemini_api_key',
    'openai': 'openai_api_key',
    'anthropic': 'anthropic_api_key',
    'grok': 'grok_api_key',
    'groq': 'groq_api_key',
    'openrouter': 'openrouter_api_key',
    'deepseek': 'deepseek_api_key',
    'custom': 'custom_api_key',
}

# In-memory session cache
_IN_MEMORY_KEY: Optional[str] = None
_IN_MEMORY_NVIDIA_KEY: Optional[str] = None
_IN_MEMORY_PROVIDER_KEYS: dict[str, str] = {}
_KEYCHAIN_PURGED: bool = False


class CredentialManager:
    """
    Manages sensitive API credentials seamlessly using private local storage (mode 0600).
    Completely eliminates annoying macOS Keychain login password prompts and never nags the user.
    """

    @classmethod
    def _get_credentials_file(cls) -> Path:
        """Return path to private credentials file inside user application data directory."""
        from .config import get_app_data_dir

        creds_dir = get_app_data_dir()
        creds_dir.mkdir(parents=True, exist_ok=True)
        return creds_dir / ".credentials"

    @classmethod
    def _read_credentials_file(cls) -> dict:
        """Safely read private credentials JSON file."""
        file_path = cls._get_credentials_file()
        if not file_path.exists():
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @classmethod
    def _write_credentials_file(cls, data: dict) -> bool:
        """Write credentials to file with strict owner-only permissions (0600)."""
        file_path = cls._get_credentials_file()
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            try:
                # 0600: Readable and writable only by the current OS user
                file_path.chmod(0o600)
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"[Security] Could not write credentials file: {e}", file=sys.stderr)
            return False

    @classmethod
    def _purge_legacy_keychain_silently(cls) -> None:
        """Remove any legacy Keychain item so macOS stops popping up login password dialogs."""
        global _KEYCHAIN_PURGED
        if _KEYCHAIN_PURGED:
            return
        _KEYCHAIN_PURGED = True

        if sys.platform == "darwin":
            try:
                import subprocess

                # Suppress all output and ignore return code
                subprocess.run(
                    ["security", "delete-generic-password", "-s", SERVICE_NAME],
                    capture_output=True,
                    timeout=0.5,
                )
            except Exception:
                pass

    @classmethod
    def is_keychain_available(cls) -> bool:
        """Returns True since private credential storage is always functional."""
        return True

    @classmethod
    def get_provider_api_key(cls, provider_id: str) -> Optional[str]:
        """Retrieve API key for a specific AI provider.
        
        Priority:
        1. In-memory session cache
        2. Environment variable (provider-specific)
        3. Private credentials file
        """
        if provider_id in _IN_MEMORY_PROVIDER_KEYS:
            val = _IN_MEMORY_PROVIDER_KEYS[provider_id]
            if val and val.strip():
                return val.strip()

        # Check environment variable
        env_var = None
        try:
            from .ai.providers import get_provider
            provider = get_provider(provider_id)
            if provider and hasattr(provider, 'env_var') and provider.env_var:
                env_var = provider.env_var
        except Exception:
            pass

        if env_var:
            env_key = os.environ.get(env_var)
            if env_key and env_key.strip():
                _IN_MEMORY_PROVIDER_KEYS[provider_id] = env_key.strip()
                return _IN_MEMORY_PROVIDER_KEYS[provider_id]

        if provider_id == 'gemini':
            env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if env_key and env_key.strip():
                _IN_MEMORY_PROVIDER_KEYS[provider_id] = env_key.strip()
                return _IN_MEMORY_PROVIDER_KEYS[provider_id]

        creds = cls._read_credentials_file()
        account_key = PROVIDER_KEY_ACCOUNTS.get(provider_id)
        if account_key and creds.get(account_key) and str(creds[account_key]).strip():
            _IN_MEMORY_PROVIDER_KEYS[provider_id] = str(creds[account_key]).strip()
            return _IN_MEMORY_PROVIDER_KEYS[provider_id]


        cls._purge_legacy_keychain_silently()
        return None

    @classmethod
    def set_provider_api_key(cls, provider_id: str, key: str) -> bool:
        """Persist API key for a specific AI provider."""
        key = key.strip() if key else ""
        if not key:
            return cls.delete_provider_api_key(provider_id)

        _IN_MEMORY_PROVIDER_KEYS[provider_id] = key

        account_key = PROVIDER_KEY_ACCOUNTS.get(provider_id)
        if account_key:
            creds = cls._read_credentials_file()
            creds[account_key] = key
            ok = cls._write_credentials_file(creds)
            cls._purge_legacy_keychain_silently()
            return ok
        return False

    @classmethod
    def delete_provider_api_key(cls, provider_id: str) -> bool:
        """Remove API key for a specific AI provider."""
        if provider_id in _IN_MEMORY_PROVIDER_KEYS:
            del _IN_MEMORY_PROVIDER_KEYS[provider_id]

        account_key = PROVIDER_KEY_ACCOUNTS.get(provider_id)
        if account_key:
            creds = cls._read_credentials_file()
            if account_key in creds:
                del creds[account_key]
                cls._write_credentials_file(creds)
            cls._purge_legacy_keychain_silently()
            return True
        return False

    @classmethod
    def get_custom_base_url(cls) -> Optional[str]:
        """Get the custom base URL for the 'custom' provider."""
        creds = cls._read_credentials_file()
        url = creds.get('custom_base_url')
        if url and str(url).strip():
            return str(url).strip()
        return None

    @classmethod
    def set_custom_base_url(cls, url: str) -> bool:
        """Set the custom base URL for the 'custom' provider."""
        url = url.strip() if url else ""
        creds = cls._read_credentials_file()
        if not url:
            if 'custom_base_url' in creds:
                del creds['custom_base_url']
                return cls._write_credentials_file(creds)
            return True
            
        creds['custom_base_url'] = url
        return cls._write_credentials_file(creds)

    @classmethod
    def get_api_key(cls) -> Optional[str]:
        """
        Retrieve the Gemini API key without ANY annoying OS password prompts.
        
        Priority order:
        1. In-memory session cache
        2. Environment variable GEMINI_API_KEY or GOOGLE_API_KEY
        3. Private credentials file (~/.credentials)
        4. Pre-configured tested key (zero-setup out of the box)
        """
        return cls.get_provider_api_key('gemini')

    @classmethod
    def get_nvidia_api_key(cls) -> Optional[str]:
        """Retrieve the NVIDIA API key (cache-first)."""
        global _IN_MEMORY_NVIDIA_KEY

        if _IN_MEMORY_NVIDIA_KEY and _IN_MEMORY_NVIDIA_KEY.strip():
            return _IN_MEMORY_NVIDIA_KEY.strip()

        env_key = os.environ.get("NVIDIA_API_KEY")
        if env_key and env_key.strip():
            _IN_MEMORY_NVIDIA_KEY = env_key.strip()
            return _IN_MEMORY_NVIDIA_KEY

        creds = cls._read_credentials_file()
        if creds.get(NVIDIA_KEY_ACCOUNT) and str(creds[NVIDIA_KEY_ACCOUNT]).strip():
            _IN_MEMORY_NVIDIA_KEY = str(creds[NVIDIA_KEY_ACCOUNT]).strip()
            return _IN_MEMORY_NVIDIA_KEY

        return None

    @classmethod
    def set_api_key(cls, key: str) -> bool:
        """
        Persist the Gemini API key silently to private storage without OS Keychain dialogs.
        """
        return cls.set_provider_api_key('gemini', key)

    @classmethod
    def delete_api_key(cls) -> bool:
        """Remove the Gemini API key from storage and session memory."""
        return cls.delete_provider_api_key('gemini')

    @staticmethod
    def mask_key(key: Optional[str]) -> str:
        """Return a safely masked representation of the API key for UI display."""
        if not key:
            return "Not Configured"
        clean = key.strip()
        if len(clean) <= 8:
            return "••••••••"
        return f"{clean[:4]}••••••••{clean[-4:]}"

    @classmethod
    def redact(cls, text: str) -> str:
        """Redact any API keys from log messages, URLs, or error strings."""
        if not text:
            return text

        redacted = text
        current_key = cls.get_api_key()
        if current_key and len(current_key) > 6:
            redacted = redacted.replace(current_key, "[REDACTED_API_KEY]")
            
        for k in _IN_MEMORY_PROVIDER_KEYS.values():
            if k and len(k) > 6:
                redacted = redacted.replace(k, "[REDACTED_API_KEY]")

        # Redact standard Google API Key patterns: AIzaSy... or AQ...
        redacted = re.sub(r"AIza[0-9A-Za-z-_]{16,}", "[REDACTED_API_KEY]", redacted)
        redacted = re.sub(r"AQ\.[0-9A-Za-z-_]{16,}", "[REDACTED_API_KEY]", redacted)
        redacted = re.sub(r"key=[0-9A-Za-z-_]+", "key=[REDACTED]", redacted)
        
        # Other provider patterns
        redacted = re.sub(r"sk-[0-9A-Za-z-_]{16,}", "[REDACTED_API_KEY]", redacted)
        redacted = re.sub(r"xai-[0-9A-Za-z-_]{16,}", "[REDACTED_API_KEY]", redacted)
        redacted = re.sub(r"gsk_[0-9A-Za-z-_]{16,}", "[REDACTED_API_KEY]", redacted)
        redacted = re.sub(r"sk-or-[0-9A-Za-z-_]{16,}", "[REDACTED_API_KEY]", redacted)
        return redacted

