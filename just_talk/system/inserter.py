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
        self._target_hwnd = None
        self._target_app = None
        self._original_clipboard: Optional[str] = None
        self._has_active_draft: bool = False

    def capture_active_target(self) -> None:
        """Capture the currently focused window or application and clipboard at the instant recording begins."""
        try:
            self._original_clipboard = ClipboardManager.get_text()
        except Exception:
            self._original_clipboard = None
        self._has_active_draft = False

        if sys.platform == "darwin":
            try:
                from AppKit import NSWorkspace

                self._target_app = NSWorkspace.sharedWorkspace().frontmostApplication()
            except Exception:
                self._target_app = None
        elif sys.platform == "win32":
            try:
                import ctypes

                self._target_hwnd = ctypes.windll.user32.GetForegroundWindow()
            except Exception:
                self._target_hwnd = None

    def get_active_app_name(self) -> str:
        """Query the name of the focused target application."""
        if sys.platform == "darwin":
            try:
                if self._target_app is not None and hasattr(self._target_app, "localizedName"):
                    name = self._target_app.localizedName()
                    if name:
                        return str(name)
                from AppKit import NSWorkspace

                app = NSWorkspace.sharedWorkspace().frontmostApplication()
                if app:
                    return str(app.localizedName() or "Unknown")
            except Exception:
                pass
        elif sys.platform == "win32":
            try:
                import ctypes

                hwnd = self._target_hwnd or ctypes.windll.user32.GetForegroundWindow()
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                    return str(buff.value)
            except Exception:
                pass

        return "Active Application"

    def _reactivate_target_window(self) -> None:
        """Ensure the user's target application and text cursor are in the foreground before pasting."""
        if sys.platform == "darwin":
            try:
                if self._target_app is not None and hasattr(self._target_app, "activateWithOptions_"):
                    # NSApplicationActivateIgnoringOtherApps = 1 << 1 (2)
                    self._target_app.activateWithOptions_(1 << 1)
                    time.sleep(0.08)
                else:
                    from AppKit import NSWorkspace
                    app = NSWorkspace.sharedWorkspace().frontmostApplication()
                    if app and hasattr(app, "activateWithOptions_"):
                        app.activateWithOptions_(1 << 1)
                        time.sleep(0.08)
            except Exception as e:
                print(f"[TextInserter] macOS target reactivation error: {e}", file=sys.stderr)
        elif sys.platform == "win32":
            try:
                import ctypes

                user32 = ctypes.windll.user32
                # Clear any lingering Alt key state from push-to-talk to prevent menu-bar activation
                KEYEVENTF_KEYUP = 0x0002
                user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)  # VK_MENU (Alt) up
                user32.keybd_event(0x1B, 0, 0, 0)                # VK_ESCAPE down (dismiss menu bar if active)
                time.sleep(0.01)
                user32.keybd_event(0x1B, 0, KEYEVENTF_KEYUP, 0)  # VK_ESCAPE up

                if self._target_hwnd:
                    user32.SetForegroundWindow(self._target_hwnd)
                    user32.BringWindowToTop(self._target_hwnd)
                    time.sleep(0.05)
            except Exception as e:
                print(f"[TextInserter] Windows target reactivation error: {e}", file=sys.stderr)

    def _synthesize_paste(self) -> bool:
        """Synthesize platform-native paste keystroke (Cmd+V on macOS, Ctrl+V on Windows)."""
        if sys.platform == "darwin":
            # 1. Native CoreGraphics CGEvent (direct HID & PID event tap injection)
            try:
                import Quartz

                source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
                v_code = 0x09  # macOS virtual keycode for 'v'
                cmd_code = 0x37  # macOS virtual keycode for Command

                cmd_down = Quartz.CGEventCreateKeyboardEvent(source, cmd_code, True)
                v_down = Quartz.CGEventCreateKeyboardEvent(source, v_code, True)
                Quartz.CGEventSetFlags(v_down, Quartz.kCGEventFlagMaskCommand)
                v_up = Quartz.CGEventCreateKeyboardEvent(source, v_code, False)
                Quartz.CGEventSetFlags(v_up, Quartz.kCGEventFlagMaskCommand)
                cmd_up = Quartz.CGEventCreateKeyboardEvent(source, cmd_code, False)

                target_pid = None
                if self._target_app is not None and hasattr(self._target_app, "processIdentifier"):
                    target_pid = self._target_app.processIdentifier()

                if target_pid and hasattr(Quartz, "CGEventPostToPid"):
                    # Direct PID-addressed event delivery directly into target app queue
                    Quartz.CGEventPostToPid(target_pid, cmd_down)
                    time.sleep(0.01)
                    Quartz.CGEventPostToPid(target_pid, v_down)
                    time.sleep(0.025)
                    Quartz.CGEventPostToPid(target_pid, v_up)
                    time.sleep(0.01)
                    Quartz.CGEventPostToPid(target_pid, cmd_up)
                else:
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, cmd_down)
                    time.sleep(0.01)
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, v_down)
                    time.sleep(0.025)
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, v_up)
                    time.sleep(0.01)
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, cmd_up)
                return True
            except Exception:
                pass

            # 2. pynput fallback
            try:
                self._keyboard.press(Key.cmd)
                time.sleep(0.015)
                self._keyboard.press('v')
                time.sleep(0.025)
                self._keyboard.release('v')
                time.sleep(0.015)
                self._keyboard.release(Key.cmd)
                return True
            except Exception:
                pass

            # 3. AppleScript fallback
            try:
                import subprocess

                subprocess.run(
                    ["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'],
                    timeout=1.0,
                    check=False,
                )
                return True
            except Exception:
                return False

        elif sys.platform == "win32":
            # 1. Win32 native keybd_event (direct hardware keyboard event generation)
            try:
                import ctypes

                user32 = ctypes.windll.user32
                VK_CONTROL = 0x11
                VK_V = 0x56
                KEYEVENTF_KEYUP = 0x0002

                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                time.sleep(0.02)
                user32.keybd_event(VK_V, 0, 0, 0)
                time.sleep(0.03)
                user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.015)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                return True
            except Exception:
                pass

            # 2. pynput fallback
            try:
                self._keyboard.press(Key.ctrl)
                time.sleep(0.015)
                self._keyboard.press('v')
                time.sleep(0.025)
                self._keyboard.release('v')
                time.sleep(0.015)
                self._keyboard.release(Key.ctrl)
                return True
            except Exception:
                return False

        else:
            # Linux / X11 fallback
            try:
                self._keyboard.press(Key.ctrl)
                time.sleep(0.015)
                self._keyboard.press('v')
                time.sleep(0.025)
                self._keyboard.release('v')
                time.sleep(0.015)
                self._keyboard.release(Key.ctrl)
                return True
            except Exception:
                return False

    def undo_last_paste(self) -> None:
        """Synthesize Cmd+Z on macOS or Ctrl+Z on Windows to undo prior draft paste."""
        if sys.platform == "darwin":
            try:
                import Quartz

                source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
                z_code = 0x06  # virtual keycode for 'z'
                cmd_code = 0x37  # virtual keycode for Command

                cmd_down = Quartz.CGEventCreateKeyboardEvent(source, cmd_code, True)
                z_down = Quartz.CGEventCreateKeyboardEvent(source, z_code, True)
                Quartz.CGEventSetFlags(z_down, Quartz.kCGEventFlagMaskCommand)
                z_up = Quartz.CGEventCreateKeyboardEvent(source, z_code, False)
                Quartz.CGEventSetFlags(z_up, Quartz.kCGEventFlagMaskCommand)
                cmd_up = Quartz.CGEventCreateKeyboardEvent(source, cmd_code, False)

                target_pid = None
                if self._target_app is not None and hasattr(self._target_app, "processIdentifier"):
                    target_pid = self._target_app.processIdentifier()

                if target_pid and hasattr(Quartz, "CGEventPostToPid"):
                    Quartz.CGEventPostToPid(target_pid, cmd_down)
                    time.sleep(0.01)
                    Quartz.CGEventPostToPid(target_pid, z_down)
                    time.sleep(0.02)
                    Quartz.CGEventPostToPid(target_pid, z_up)
                    time.sleep(0.01)
                    Quartz.CGEventPostToPid(target_pid, cmd_up)
                else:
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, cmd_down)
                    time.sleep(0.01)
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, z_down)
                    time.sleep(0.02)
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, z_up)
                    time.sleep(0.01)
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, cmd_up)
            except Exception:
                try:
                    self._keyboard.press(Key.cmd)
                    time.sleep(0.01)
                    self._keyboard.press('z')
                    time.sleep(0.02)
                    self._keyboard.release('z')
                    time.sleep(0.01)
                    self._keyboard.release(Key.cmd)
                except Exception:
                    pass
        elif sys.platform == "win32":
            try:
                import ctypes

                user32 = ctypes.windll.user32
                VK_CONTROL = 0x11
                VK_Z = 0x5A
                KEYEVENTF_KEYUP = 0x0002
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                time.sleep(0.01)
                user32.keybd_event(VK_Z, 0, 0, 0)
                time.sleep(0.02)
                user32.keybd_event(VK_Z, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.01)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            except Exception:
                try:
                    self._keyboard.press(Key.ctrl)
                    self._keyboard.press('z')
                    self._keyboard.release('z')
                    self._keyboard.release(Key.ctrl)
                except Exception:
                    pass

    def insert(
        self,
        text: str,
        restore_clipboard: bool = True,
        replace_previous: bool = False,
    ) -> Tuple[bool, str, str]:
        """
        Insert final text into the currently active target application.
        Returns:
            Tuple[success: bool, status: str ("inserted" | "clipboard"), active_app: str]
        """
        if not text:
            return True, "inserted", "System"

        active_app = self.get_active_app_name()
        current_clipboard = ClipboardManager.get_text()
        orig_to_restore = self._original_clipboard if self._original_clipboard is not None else current_clipboard

        # Step 1: Put formatted text onto clipboard
        set_ok = ClipboardManager.set_text(text)
        if not set_ok:
            return False, "failed", active_app

        # Step 2: Check if an active text target or application window is present
        from .caret_locator import CaretLocator
        if CaretLocator._last_has_text_target is False:
            print("[TextInserter] No active text target detected. Text copied to clipboard safely.", file=sys.stderr)
            return True, "clipboard", active_app

        # Step 3: Reactivate the original target application
        self._reactivate_target_window()

        # Step 3b: If in-place replacement (Phase 2), undo previous draft first
        if replace_previous or self._has_active_draft:
            self.undo_last_paste()
            time.sleep(0.04)

        # Step 4: Synthesize simulated paste keystroke
        try:
            paste_ok = self._synthesize_paste()
            if not paste_ok:
                raise RuntimeError("All paste mechanisms failed")

            if not restore_clipboard:
                # Active draft emitted: keep flag set and DO NOT restore clipboard yet
                self._has_active_draft = True
            else:
                self._has_active_draft = False
                # Step 5: Restore prior clipboard in background thread after target app consumes paste
                if orig_to_restore is not None and orig_to_restore != text:
                    restore_delay = max(1.0, min(2.5, 1.0 + len(text) * 0.001))
                    threading.Thread(
                        target=ClipboardManager.restore_after_delay,
                        args=(orig_to_restore, restore_delay),
                        daemon=True,
                    ).start()

            return True, "inserted", active_app

        except Exception as e:
            print(f"[TextInserter] Keystroke synthesis error: {e}. Falling back to clipboard.", file=sys.stderr)
            return True, "clipboard", active_app

    def cancel_draft(self) -> None:
        """Undo any lingering draft paste and restore user's original clipboard."""
        if self._has_active_draft:
            try:
                self._reactivate_target_window()
                self.undo_last_paste()
            except Exception as e:
                print(f"[TextInserter] Error undoing draft on cancel: {e}", file=sys.stderr)
            self._has_active_draft = False

        if self._original_clipboard is not None:
            try:
                ClipboardManager.set_text(self._original_clipboard)
            except Exception as e:
                print(f"[TextInserter] Error restoring clipboard on cancel: {e}", file=sys.stderr)
            self._original_clipboard = None

