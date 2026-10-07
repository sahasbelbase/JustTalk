"""Cross-platform global keyboard hotkey and push-to-talk listener using pynput."""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable, Optional, Set

from pynput import keyboard


class PynputHotkeyMonitor:
    """
    Cross-platform push-to-talk and hotkey listener.
    Supports keys like Right Alt, Ctrl+Shift+Space, Alt+Space.
    """

    def __init__(
        self,
        trigger_key: str,
        action_key: str,
        on_start_recording: Callable[[bool], None],  # bool: is_action_mode
        on_stop_recording: Callable[[], None],
        push_to_talk: bool = True,
        on_action_mode_changed: Optional[Callable[[bool], None]] = None,
        on_cancel_recording: Optional[Callable[[], None]] = None,
        on_paste_last: Optional[Callable[[], None]] = None,
    ):
        self.trigger_key = trigger_key.lower()
        self.action_key = action_key.lower()
        self.on_start_recording = on_start_recording
        self.on_stop_recording = on_stop_recording
        self.push_to_talk = push_to_talk
        self.on_action_mode_changed = on_action_mode_changed
        self.on_cancel_recording = on_cancel_recording
        self.on_paste_last = on_paste_last

        self._current_keys: Set[keyboard.Key | keyboard.KeyCode] = set()
        self._listener: Optional[keyboard.Listener] = None
        self._is_active = False
        self._is_action_mode = False
        self._last_toggle_time = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _is_right_alt(key) -> bool:
        """Robust check for Right Alt / AltGr across Windows, macOS, and Linux keyboard drivers."""
        if key in (keyboard.Key.alt_r, getattr(keyboard.Key, "alt_gr", None)):
            return True
        name = getattr(key, "name", "")
        if name in ("alt_r", "alt_gr", "altgr"):
            return True
        vk = getattr(key, "vk", None)
        # Windows virtual key codes: VK_RMENU = 165 (0xA5)
        if vk in (165, 0xA5):
            return True
        return False

    def _matches_trigger(self) -> bool:
        """Evaluate if the currently pressed keys match the trigger shortcut."""
        trigger = self.trigger_key.lower().replace(" ", "_").replace("-", "_")

        if trigger in ("right_alt", "alt_r", "alt_gr", "altgr", "right_option", "rightalt"):
            return any(self._is_right_alt(k) for k in self._current_keys)
        elif trigger in ("alt", "option"):
            return any(
                self._is_right_alt(k)
                or k in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, getattr(keyboard.Key, "alt_gr", None))
                or getattr(k, "vk", None) in (18, 164, 165)
                for k in self._current_keys
            )
        elif trigger in ("alt_space", "alt+space"):
            has_alt = any(
                k in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, getattr(keyboard.Key, "alt_gr", None))
                or getattr(k, "vk", None) in (18, 164, 165)
                for k in self._current_keys
            )
            has_space = any(k == keyboard.Key.space or getattr(k, "vk", None) == 32 for k in self._current_keys)
            return has_alt and has_space
        elif trigger in ("ctrl_space", "ctrl+space"):
            has_ctrl = any(
                k in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r)
                or getattr(k, "vk", None) in (17, 162, 163)
                for k in self._current_keys
            )
            has_space = any(k == keyboard.Key.space or getattr(k, "vk", None) == 32 for k in self._current_keys)
            return has_ctrl and has_space
        elif trigger in ("ctrl_shift_space", "ctrl+shift+space"):
            has_ctrl = any(
                k in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r)
                or getattr(k, "vk", None) in (17, 162, 163)
                for k in self._current_keys
            )
            has_shift = any(
                k in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r)
                or getattr(k, "vk", None) in (16, 160, 161)
                for k in self._current_keys
            )
            has_space = any(k == keyboard.Key.space or getattr(k, "vk", None) == 32 for k in self._current_keys)
            return has_ctrl and has_shift and has_space
        elif trigger in ("fn", "globe", "right_alt", "alt_r", "right_option"):
            # Universal push-to-talk: support either Right Alt or Fn
            return any(
                self._is_right_alt(k)
                or getattr(k, "vk", None) in (63, 0xFF)
                or getattr(k, "char", "") == "fn"
                for k in self._current_keys
            )
        return False

    def _matches_action(self) -> bool:
        """Evaluate if the currently pressed keys match the action shortcut."""
        has_shift = any(
            k in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r)
            or getattr(k, "vk", None) in (16, 160, 161)
            for k in self._current_keys
        )
        return self._matches_trigger() and has_shift

    def _matches_paste_last(self) -> bool:
        """Paste-last-dictation shortcut: Ctrl+Cmd+V on macOS, Win+Alt+V elsewhere."""
        v_vk = 9 if sys.platform == "darwin" else 0x56
        has_v = any(
            getattr(k, "vk", None) == v_vk or (getattr(k, "char", None) or "").lower() == "v"
            for k in self._current_keys
        )
        has_cmd = any(
            k in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r)
            or (sys.platform == "win32" and getattr(k, "vk", None) in (91, 92))
            for k in self._current_keys
        )
        if sys.platform == "darwin":
            has_ctrl = any(k in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r) for k in self._current_keys)
            return has_v and has_cmd and has_ctrl
        has_alt = any(
            k in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, getattr(keyboard.Key, "alt_gr", None))
            or getattr(k, "vk", None) in (18, 164, 165)
            for k in self._current_keys
        )
        return has_v and has_cmd and has_alt

    def _handle_paste_last(self) -> None:
        cancel_recording = False
        with self._lock:
            if self._is_active:
                # Right Alt is also the dictation key, so this combo may have just started a recording
                self._is_active = False
                self._is_action_mode = False
                cancel_recording = True
        if cancel_recording and self.on_cancel_recording:
            try:
                self.on_cancel_recording()
            except Exception as e:
                print(f"[PynputHook] cancel error: {e}", file=sys.stderr)
        try:
            self.on_paste_last()
        except Exception as e:
            print(f"[PynputHook] on_paste_last error: {e}", file=sys.stderr)

    def _on_press(self, key):
        to_start = False
        to_stop = False
        action_changed: Optional[bool] = None
        now = time.time()

        # Emergency Cancel: Escape key
        if key == keyboard.Key.esc:
            to_cancel = False
            with self._lock:
                if self._is_active:
                    self._is_active = False
                    self._is_action_mode = False
                    to_cancel = True
            if to_cancel:
                print("[PynputHook] Escape key pressed -> CANCEL recording", file=sys.stderr)
                try:
                    if self.on_cancel_recording:
                        self.on_cancel_recording()
                    else:
                        self.on_stop_recording()
                except Exception as e:
                    print(f"[PynputHook] cancel error: {e}", file=sys.stderr)
                return

        with self._lock:
            # Check if this key was already pressed (OS auto-repeat filtering)
            is_repeat = key in self._current_keys
            self._current_keys.add(key)
            is_paste_last = bool(self.on_paste_last) and not is_repeat and self._matches_paste_last()

        if is_paste_last:
            self._handle_paste_last()
            return

        with self._lock:
            is_trigger = self._matches_trigger()
            is_action = self._matches_action()

            if is_trigger:
                if self.push_to_talk:
                    if not self._is_active:
                        self._is_active = True
                        self._is_action_mode = is_action
                        to_start = True
                    else:
                        # Already active: check if Shift was pressed during the hold
                        if is_action != self._is_action_mode:
                            self._is_action_mode = is_action
                            action_changed = is_action
                else:
                    # Foolproof Toggle Mode: Tap to Start, Tap to Stop
                    # Filter out rapid key repeat pulses and debounce contact bounce (<250ms)
                    if not is_repeat and (now - self._last_toggle_time >= 0.25):
                        self._last_toggle_time = now
                        if not self._is_active:
                            self._is_active = True
                            self._is_action_mode = is_action
                            to_start = True
                        else:
                            self._is_active = False
                            self._is_action_mode = False
                            to_stop = True

        if to_start:
            try:
                self.on_start_recording(is_action)
            except Exception as e:
                print(f"[PynputHook] on_start error: {e}", file=sys.stderr)

        if action_changed is not None and self.on_action_mode_changed:
            try:
                self.on_action_mode_changed(action_changed)
            except Exception as e:
                print(f"[PynputHook] on_action_mode_changed error: {e}", file=sys.stderr)

        if to_stop:
            try:
                self.on_stop_recording()
            except Exception as e:
                print(f"[PynputHook] on_stop error: {e}", file=sys.stderr)

    def _on_release(self, key):
        to_stop = False
        action_changed: Optional[bool] = None

        with self._lock:
            is_right_alt_release = self._is_right_alt(key)

            # Match and remove by key identity, virtual key code, or name
            to_remove = set()
            for k in self._current_keys:
                if k == key:
                    to_remove.add(k)
                elif getattr(k, "vk", None) is not None and getattr(k, "vk", None) == getattr(key, "vk", None):
                    to_remove.add(k)
                elif getattr(k, "name", None) is not None and getattr(k, "name", None) == getattr(key, "name", None):
                    to_remove.add(k)
                elif is_right_alt_release and self._is_right_alt(k):
                    to_remove.add(k)

            for k in to_remove:
                self._current_keys.discard(k)

            # On Windows, AltGr often generates a synthetic Ctrl_L press event.
            if is_right_alt_release:
                ctrl_to_remove = [
                    k for k in self._current_keys
                    if k in (keyboard.Key.ctrl, keyboard.Key.ctrl_l) or getattr(k, "vk", None) in (17, 162)
                ]
                for ck in ctrl_to_remove:
                    self._current_keys.discard(ck)

            if self.push_to_talk and self._is_active:
                if not self._matches_trigger():
                    self._is_active = False
                    self._is_action_mode = False
                    to_stop = True
                else:
                    # Trigger is still down, but Shift might have been released
                    is_action = self._matches_action()
                    if is_action != self._is_action_mode:
                        self._is_action_mode = is_action
                        action_changed = is_action

        if action_changed is not None and self.on_action_mode_changed:
            try:
                self.on_action_mode_changed(action_changed)
            except Exception as e:
                print(f"[PynputHook] on_action_mode_changed error: {e}", file=sys.stderr)

        if to_stop:
            try:
                self.on_stop_recording()
            except Exception as e:
                print(f"[PynputHook] on_stop error: {e}", file=sys.stderr)

    def reset_state(self) -> None:
        """Reset internal key tracking and state."""
        with self._lock:
            self._current_keys.clear()
            self._is_active = False
            self._is_action_mode = False

    def start(self) -> bool:
        try:
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._listener.daemon = True
            self._listener.start()
            print(f"[PynputHook] Global keyboard listener started for trigger '{self.trigger_key}'.", file=sys.stderr)
            return True
        except Exception as e:
            print(f"[PynputHook] Failed to start listener: {e}", file=sys.stderr)
            return False

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self.reset_state()
