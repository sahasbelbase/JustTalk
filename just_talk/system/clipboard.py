"""Clipboard management with backup and restoration capabilities."""

from __future__ import annotations

import sys
import time
from typing import Optional

try:
    from PySide6.QtGui import QClipboard, QGuiApplication

    HAS_PYSIDE = True
except ImportError:
    HAS_PYSIDE = False


class ClipboardManager:
    """Safely manages system clipboard operations and state restoration."""

    @staticmethod
    def get_text() -> str:
        """Retrieve current plain text from clipboard."""
        if HAS_PYSIDE and QGuiApplication.instance():
            cb = QGuiApplication.clipboard()
            return cb.text() or ""

        # macOS native pasteboard fallback
        if sys.platform == "darwin":
            try:
                from AppKit import NSPasteboard, NSPasteboardTypeString

                pb = NSPasteboard.generalPasteboard()
                text = pb.stringForType_(NSPasteboardTypeString)
                if text is not None:
                    return str(text)
            except Exception:
                pass

        try:
            import pyperclip

            return pyperclip.paste() or ""
        except Exception:
            return ""

    @staticmethod
    def set_text(text: str) -> bool:
        """Put text onto system clipboard."""
        if HAS_PYSIDE and QGuiApplication.instance():
            cb = QGuiApplication.clipboard()
            cb.setText(text)
            return True

        # macOS native pasteboard fallback
        if sys.platform == "darwin":
            try:
                from AppKit import NSPasteboard, NSPasteboardTypeString

                pb = NSPasteboard.generalPasteboard()
                pb.clearContents()
                pb.setString_forType_(text, NSPasteboardTypeString)
                return True
            except Exception:
                pass

        try:
            import pyperclip

            pyperclip.copy(text)
            return True
        except Exception as e:
            print(f"[Clipboard] Failed to set text: {e}", file=sys.stderr)
            return False

    @classmethod
    def restore_after_delay(cls, original_text: str, delay_sec: float = 0.08) -> None:
        """
        Wait for target app to consume the simulated paste event,
        then restore the user's previous clipboard contents.
        """
        time.sleep(delay_sec)
        cls.set_text(original_text)
