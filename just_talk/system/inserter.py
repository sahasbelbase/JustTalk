"""Universal active text insertion engine with clipboard fallback and state restoration."""

from __future__ import annotations

import sys
import threading
import time
from typing import Optional, Tuple

from pynput.keyboard import Controller, Key

from .clipboard import ClipboardManager


class TextInserter:
    """Inserts text into the currently active target application."""

    def __init__(self):
        self._keyboard = Controller()

    @staticmethod
    def get_active_app_name() -> str:
        """Query the name of the currently focused/frontmost application."""
        if sys.platform == "darwin":
            try:
                from AppKit import NSWorkspace

                app = NSWorkspace.sharedWorkspace().frontmostApplication()
                if app:
                    return str(app.localizedName() or "Unknown")
            except Exception:
                pass
        elif sys.platform == "win32":
            try:
                import ctypes

                hwnd = ctypes.windll.user32.GetForegroundWindow()
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                    return str(buff.value)
            except Exception:
                pass

        return "Active Application"

    def insert(self, text: str, restore_clipboard: bool = True) -> Tuple[bool, str, str]:
        """
        Insert final text into the currently active input field.
        Returns:
            Tuple[success: bool, status: str ("inserted" | "clipboard"), active_app: str]
        """
        if not text:
            return True, "inserted", "System"

        active_app = self.get_active_app_name()
        original_clipboard = ClipboardManager.get_text()

        # Step 1: Put formatted text onto clipboard
        set_ok = ClipboardManager.set_text(text)
        if not set_ok:
            return False, "failed", active_app

        # Step 2: Synthesize simulated paste keystroke
        try:
            time.sleep(0.025)  # Pause to ensure clipboard is committed in OS
            modifier = Key.cmd if sys.platform == "darwin" else Key.ctrl
            self._keyboard.press(modifier)
            time.sleep(0.015)
            self._keyboard.press('v')
            time.sleep(0.025)
            self._keyboard.release('v')
            time.sleep(0.015)
            self._keyboard.release(modifier)

            # Step 3: Restore prior clipboard in background thread after app consumes paste
            if restore_clipboard and original_clipboard != text:
                restore_delay = max(0.45, min(1.5, 0.45 + len(text) * 0.001))
                threading.Thread(
                    target=ClipboardManager.restore_after_delay,
                    args=(original_clipboard, restore_delay),
                    daemon=True,
                ).start()

            return True, "inserted", active_app

        except Exception as e:
            print(f"[TextInserter] Keystroke synthesis error: {e}. Falling back to clipboard.", file=sys.stderr)
            # Text is already safely on clipboard
            return True, "clipboard", active_app
