"""Universal active text insertion engine with clipboard fallback and state restoration."""

from __future__ import annotations

import sys
import threading
import time
from typing import Optional, Tuple

from pynput.keyboard import Controller, Key

from .clipboard import ClipboardManager

# A draft is taken back with Cmd/Ctrl+Z before the polished text goes in. Terminals can't undo a
# paste, so the draft stayed and the polished copy landed right after it. VS Code-style editors
# and JetBrains IDEs have a built-in terminal, so they count too unless the focus is clearly not one.
_TERMINAL_APPS = ("terminal", "iterm", "warp", "ghostty", "kitty", "alacritty", "wezterm", "tabby",
                  "powershell", "command prompt", "cmd.exe")
_IDE_APPS = ("code", "cursor", "windsurf", "antigravity", "zed", "pycharm", "intellij", "webstorm",
             "goland", "clion", "rider", "rustrover", "phpstorm", "rubymine", "android studio", "datagrip")


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

    def return_to_target(self) -> None:
        """Clicking the pill's ✕ makes Just Talk the active app (its window jumps to the front) on
        macOS. Give the focus back to the app the user was dictating into, if Just Talk took it."""
        if sys.platform != "darwin" or self._target_app is None:
            return
        try:
            from AppKit import NSApplication, NSRunningApplication, NSWorkspace

            me = NSRunningApplication.currentApplication()
            if self._target_app.processIdentifier() == me.processIdentifier():
                return  # dictating into Just Talk itself
            ours = lambda: (lambda f: f is not None and f.processIdentifier() == me.processIdentifier())(  # noqa: E731
                NSWorkspace.sharedWorkspace().frontmostApplication())
            if not ours():
                return
            # macOS 14+ ignores one app pushing another to the front ("activate ignoring other
            # apps"); the active app has to hand over: yield, then activate the target
            app = NSApplication.sharedApplication()
            if hasattr(app, "yieldActivationToApplication_"):
                app.yieldActivationToApplication_(self._target_app)
            if hasattr(self._target_app, "activate"):
                self._target_app.activate()
            else:
                self._target_app.activateWithOptions_(0)
            time.sleep(0.12)
            if ours():  # still refused: hiding Just Talk always gives the focus back
                app.hide_(None)
            print(f"[TextInserter] Back to '{self._target_app.localizedName()}' after cancel", file=sys.stderr)
        except Exception as e:
            print(f"[TextInserter] couldn't return to the target app: {e}", file=sys.stderr)

    def draft_can_be_undone(self, app_name: Optional[str] = None) -> bool:
        """Whether a quick draft pasted now can be taken back with undo when the polished text is ready."""
        name = (app_name or self.get_active_app_name()).lower()
        if any(k in name for k in _TERMINAL_APPS):
            return False
        if any(k in name for k in _IDE_APPS):
            return self._focus_is_web_text_box()
        return True

    def _focus_is_web_text_box(self) -> bool:
        """macOS: the focused element is a web text box (an editor or chat box) and not xterm.js,
        the terminal inside VS Code-style editors. False whenever it can't be told."""
        if sys.platform != "darwin":
            return False
        try:
            import ApplicationServices as AS

            app = self._target_app
            if app is None:
                from AppKit import NSWorkspace

                app = NSWorkspace.sharedWorkspace().frontmostApplication()
            elem = AS.AXUIElementCreateApplication(app.processIdentifier())
            AS.AXUIElementSetAttributeValue(elem, "AXManualAccessibility", True)
            err, focused = AS.AXUIElementCopyAttributeValue(elem, AS.kAXFocusedUIElementAttribute, None)
            if err != 0 or focused is None:
                return False
            err, classes = AS.AXUIElementCopyAttributeValue(focused, "AXDOMClassList", None)
            if err != 0 or not classes:
                return False
            _, desc = AS.AXUIElementCopyAttributeValue(focused, "AXDescription", None)
            text = " ".join(str(c) for c in classes).lower() + " " + str(desc or "").lower()
            return "xterm" not in text and "terminal" not in text
        except Exception:
            return False

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

    @staticmethod
    def _target_is_frontmost(pid: int) -> bool:
        try:
            from AppKit import NSWorkspace

            front = NSWorkspace.sharedWorkspace().frontmostApplication()
            return front is not None and front.processIdentifier() == pid
        except Exception:
            return False

    @staticmethod
    def _focused_text_length() -> Optional[int]:
        """Characters in the focused text box (macOS accessibility), or None when it can't be read."""
        if sys.platform != "darwin":
            return None
        try:
            import ApplicationServices as AS
            from AppKit import NSWorkspace

            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            elem = AS.AXUIElementCreateApplication(app.processIdentifier())
            err, focused = AS.AXUIElementCopyAttributeValue(elem, AS.kAXFocusedUIElementAttribute, None)
            if err != 0 or focused is None:
                return None
            # only real text boxes that hold the text: a terminal's input box stays empty, which
            # looked like a missed paste and pasted the same text again
            err, role = AS.AXUIElementCopyAttributeValue(focused, AS.kAXRoleAttribute, None)
            if err != 0 or str(role) not in ("AXTextArea", "AXTextField", "AXSearchField", "AXComboBox"):
                return None
            err, value = AS.AXUIElementCopyAttributeValue(focused, AS.kAXValueAttribute, None)
            return len(value) if err == 0 and isinstance(value, str) else None
        except Exception:
            return None

    def _paste_missed(self, before: int) -> bool:
        """True when the focused text box still has the same length 0.6 s after pasting (well past
        how long browsers take to report a change, so a slow update isn't mistaken for a miss)."""
        for _ in range(12):
            time.sleep(0.05)
            now = self._focused_text_length()
            if now is None or now != before:
                return False
        return True

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

                Quartz.CGEventSetFlags(cmd_down, Quartz.kCGEventFlagMaskCommand)

                target_pid = None
                if self._target_app is not None and hasattr(self._target_app, "processIdentifier"):
                    target_pid = self._target_app.processIdentifier()

                # When the target is in front, send Cmd+V the way a real key press travels (HID).
                # Events posted straight to a process were sometimes dropped by Chromium apps
                # (Brave, VS Code, Antigravity) while Just Talk still showed "Inserted".
                if target_pid and not self._target_is_frontmost(target_pid) and hasattr(Quartz, "CGEventPostToPid"):
                    # Focus moved elsewhere: address the paste to the target app only
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

    def _synthesize_copy(self) -> bool:
        """Synthesize Cmd+C on macOS or Ctrl+C on Windows in the target app."""
        if sys.platform == "darwin":
            try:
                import Quartz

                source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
                c_code = 0x08  # macOS virtual keycode for 'c'
                c_down = Quartz.CGEventCreateKeyboardEvent(source, c_code, True)
                c_up = Quartz.CGEventCreateKeyboardEvent(source, c_code, False)
                # Explicit flags so a still-held Fn/Shift/Option can't turn this into another shortcut
                Quartz.CGEventSetFlags(c_down, Quartz.kCGEventFlagMaskCommand)
                Quartz.CGEventSetFlags(c_up, Quartz.kCGEventFlagMaskCommand)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, c_down)
                time.sleep(0.025)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, c_up)
                return True
            except Exception:
                pass
            modifier = Key.cmd
        elif sys.platform == "win32":
            try:
                import ctypes

                user32 = ctypes.windll.user32
                KEYEVENTF_KEYUP = 0x0002
                user32.keybd_event(0x11, 0, 0, 0)  # VK_CONTROL down
                time.sleep(0.02)
                user32.keybd_event(0x43, 0, 0, 0)  # VK_C down
                time.sleep(0.03)
                user32.keybd_event(0x43, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.015)
                user32.keybd_event(0x11, 0, KEYEVENTF_KEYUP, 0)
                return True
            except Exception:
                pass
            modifier = Key.ctrl
        else:
            modifier = Key.ctrl

        try:
            self._keyboard.press(modifier)
            time.sleep(0.015)
            self._keyboard.press('c')
            time.sleep(0.025)
            self._keyboard.release('c')
            time.sleep(0.015)
            self._keyboard.release(modifier)
            return True
        except Exception:
            return False

    def copy_selection(self, timeout_sec: float = 0.6) -> str:
        """
        Return the text currently selected in the target app, or "" when nothing is selected.
        The clipboard is swapped for a sentinel first so an empty selection can't be confused
        with whatever the user had copied before; the original clipboard is put back afterwards.
        """
        # A still-held Shift/Alt from the shortcut would turn Ctrl+C into a different command
        self.wait_for_modifiers_released()
        original = ClipboardManager.get_text()
        sentinel = f"⁣justtalk-selection-probe-{time.time_ns()}⁣"
        if not ClipboardManager.set_text(sentinel):
            return ""

        selected = ""
        try:
            if sys.platform == "darwin":
                self._reactivate_target_window()
            elif sys.platform == "win32" and self._target_hwnd:
                try:
                    import ctypes

                    ctypes.windll.user32.SetForegroundWindow(self._target_hwnd)
                    time.sleep(0.03)
                except Exception:
                    pass

            if self._synthesize_copy():
                deadline = time.time() + timeout_sec
                while time.time() < deadline:
                    time.sleep(0.03)
                    current = ClipboardManager.get_text()
                    if current != sentinel:
                        selected = current
                        break
        finally:
            ClipboardManager.set_text(original)

        return selected if selected.strip() else ""

    @staticmethod
    def is_implicit_line_copy(text: str) -> bool:
        """VS Code-style editors copy the current line (with its newline) when nothing is selected."""
        return text.endswith("\n") and "\n" not in text.rstrip("\r\n")

    @staticmethod
    def wait_for_modifiers_released(timeout_sec: float = 1.0) -> None:
        """Block until the user lets go of modifier keys (so a synthetic paste isn't combined with them)."""
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if not TextInserter._modifiers_down():
                return
            time.sleep(0.02)

    @staticmethod
    def _modifiers_down() -> bool:
        if sys.platform == "darwin":
            try:
                import Quartz

                flags = Quartz.CGEventSourceFlagsState(Quartz.kCGEventSourceStateHIDSystemState)
                mask = (
                    Quartz.kCGEventFlagMaskCommand
                    | Quartz.kCGEventFlagMaskControl
                    | Quartz.kCGEventFlagMaskAlternate
                    | Quartz.kCGEventFlagMaskShift
                )
                return bool(flags & mask)
            except Exception:
                return False
        if sys.platform == "win32":
            try:
                import ctypes

                state = ctypes.windll.user32.GetAsyncKeyState
                # Shift, Ctrl, Alt, left/right Windows keys
                return any(state(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C))
            except Exception:
                return False
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
        replacing = replace_previous or self._has_active_draft
        if replacing:
            self.undo_last_paste()
            time.sleep(0.04)

        # Step 4: Synthesize simulated paste keystroke
        try:
            # never in terminals or IDEs (their input box doesn't hold the text), nor after an undo
            checkable = not replacing and self.draft_can_be_undone(active_app)
            before = self._focused_text_length() if checkable else None
            paste_ok = self._synthesize_paste()
            if not paste_ok:
                raise RuntimeError("All paste mechanisms failed")
            # A paste can be dropped silently; when the text box didn't change, paste once more.
            # Not after an undo (a draft swap can leave the length the same), so never twice.
            if before is not None and self._paste_missed(before):
                print(f"[TextInserter] Paste didn't land in '{active_app}'; pasting again", file=sys.stderr)
                self._synthesize_paste()

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

