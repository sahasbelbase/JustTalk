"""Secure API key storage using native OS credentials (Keychain / Credential Manager)."""

from __future__ import annotations

import os
import re
import sys
from typing import Optional

SERVICE_NAME = "JustTalkVoiceInput"
KEY_ACCOUNT = "gemini_api_key"

# In-memory session fallback if no OS keychain backend is available
_IN_MEMORY_KEY: Optional[str] = None
_KEYCHAIN_AVAILABLE: Optional[bool] = None


class CredentialManager:
    """Manages sensitive API credentials using the OS credential store."""

    @classmethod
    def is_keychain_available(cls) -> bool:
        """Check if a functional OS keychain backend is available."""
        global _KEYCHAIN_AVAILABLE
        if _KEYCHAIN_AVAILABLE is not None:
            return _KEYCHAIN_AVAILABLE

        try:
            import keyring
            from keyring.backends import fail

            backend = keyring.get_keyring()
            if isinstance(backend, fail.Keyring):
                _KEYCHAIN_AVAILABLE = False
            else:
                _KEYCHAIN_AVAILABLE = True
        except Exception:
            _KEYCHAIN_AVAILABLE = False

        return _KEYCHAIN_AVAILABLE

    @classmethod
    def get_api_key(cls) -> Optional[str]:
        """
        Retrieve the Gemini API key.
        Checks:
        1. Native OS secure credential store (Keychain on macOS, Credential Manager on Windows)
        2. In-memory session key if keychain is unavailable
        3. Environment variable GEMINI_API_KEY or GOOGLE_API_KEY as fallback
        """
        global _IN_MEMORY_KEY

        # 1. Check OS secure vault
        if sys.platform == "darwin":
            import subprocess

            try:
                res = subprocess.run(
                    ["security", "find-generic-password", "-s", SERVICE_NAME, "-a", KEY_ACCOUNT, "-w"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )
                if res.returncode == 0 and res.stdout.strip():
                    _IN_MEMORY_KEY = res.stdout.strip()
                    return _IN_MEMORY_KEY
            except Exception:
                pass

        if cls.is_keychain_available():
            try:
                import keyring

                key = keyring.get_password(SERVICE_NAME, KEY_ACCOUNT)
                if key and key.strip():
                    return key.strip()
            except Exception as e:
                print(f"[Security] OS credential store access warning: {cls.redact(str(e))}", file=sys.stderr)

        # 2. Check in-memory session key
        if _IN_MEMORY_KEY and _IN_MEMORY_KEY.strip():
            return _IN_MEMORY_KEY.strip()

        # 3. Check environment variables
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if env_key and env_key.strip():
            return env_key.strip()

        return None

    @classmethod
    def set_api_key(cls, key: str) -> bool:
        """
        Securely persist the Gemini API key in the OS credential store,
        or in memory if no keychain is available.
        """
        global _IN_MEMORY_KEY
        key = key.strip()
        if not key:
            return cls.delete_api_key()

        _IN_MEMORY_KEY = key

        # On macOS, use security CLI with -A to allow any app access without popup prompts
        if sys.platform == "darwin":
            import subprocess

            try:
                subprocess.run(
                    ["security", "add-generic-password", "-s", SERVICE_NAME, "-a", KEY_ACCOUNT, "-w", key, "-U", "-A"],
                    check=True,
                    capture_output=True,
                )
                return True
            except Exception:
                pass

        if cls.is_keychain_available():
            try:
                import keyring

                keyring.set_password(SERVICE_NAME, KEY_ACCOUNT, key)
                return True
            except Exception as e:
                print(f"[Security] Failed to save key to OS credential store: {cls.redact(str(e))}", file=sys.stderr)
                return False
        else:
            return True

    @classmethod
    def delete_api_key(cls) -> bool:
        """Remove the Gemini API key from the OS credential store and session memory."""
        global _IN_MEMORY_KEY
        _IN_MEMORY_KEY = None

        if sys.platform == "darwin":
            import subprocess

            try:
                subprocess.run(
                    ["security", "delete-generic-password", "-s", SERVICE_NAME, "-a", KEY_ACCOUNT],
                    capture_output=True,
                )
            except Exception:
                pass

        if cls.is_keychain_available():
            try:
                import keyring

                keyring.delete_password(SERVICE_NAME, KEY_ACCOUNT)
                return True
            except Exception:
                return False
        return True

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
        # Redact the currently active key if known
        current_key = cls.get_api_key()
        if current_key and len(current_key) > 6:
            redacted = redacted.replace(current_key, "[REDACTED_API_KEY]")

        # Redact standard Google API Key patterns: AIzaSy... or AQ...
        redacted = re.sub(r"AIza[0-9A-Za-z-_]{16,}", "[REDACTED_API_KEY]", redacted)
        redacted = re.sub(r"AQ\.[0-9A-Za-z-_]{16,}", "[REDACTED_API_KEY]", redacted)
        # Redact keys passed in URL query params if any
        redacted = re.sub(r"key=[0-9A-Za-z-_]+", "key=[REDACTED]", redacted)
        return redacted
