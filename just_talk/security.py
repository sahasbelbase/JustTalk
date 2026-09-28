"""Secure API key storage using native OS credentials (Keychain / Credential Manager)."""

from __future__ import annotations

import os
import sys
from typing import Optional

SERVICE_NAME = "JustTalkVoiceInput"
KEY_ACCOUNT = "gemini_api_key"


class CredentialManager:
    """Manages sensitive API credentials using the OS credential store."""

    @staticmethod
    def get_api_key() -> Optional[str]:
        """
        Retrieve the Gemini API key.
        Checks:
        1. Native OS secure credential store (Keychain on macOS, Credential Manager on Windows)
        2. Environment variable GEMINI_API_KEY or GOOGLE_API_KEY as fallback
        """
        # 1. Check OS secure vault
        try:
            import keyring

            key = keyring.get_password(SERVICE_NAME, KEY_ACCOUNT)
            if key and key.strip():
                return key.strip()
        except Exception as e:
            # Fallback gracefully if keyring backend has permissions issues
            print(f"[Security] OS credential store access warning: {e}", file=sys.stderr)

        # 2. Check environment variables
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if env_key and env_key.strip():
            return env_key.strip()

        return None

    @staticmethod
    def set_api_key(key: str) -> bool:
        """Securely persist the Gemini API key in the OS credential store."""
        key = key.strip()
        if not key:
            return False

        try:
            import keyring

            keyring.set_password(SERVICE_NAME, KEY_ACCOUNT, key)
            return True
        except Exception as e:
            print(f"[Security] Failed to save key to OS credential store: {e}", file=sys.stderr)
            return False

    @staticmethod
    def delete_api_key() -> bool:
        """Remove the Gemini API key from the OS credential store."""
        try:
            import keyring

            keyring.delete_password(SERVICE_NAME, KEY_ACCOUNT)
            return True
        except Exception:
            return False

    @staticmethod
    def mask_key(key: Optional[str]) -> str:
        """Return a safely masked representation of the API key for UI display."""
        if not key:
            return "Not Configured"
        clean = key.strip()
        if len(clean) <= 8:
            return "••••••••"
        return f"{clean[:4]}••••••••{clean[-4:]}"
