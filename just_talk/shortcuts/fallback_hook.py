"""Cross-platform global keyboard hotkey and push-to-talk listener using pynput."""

from __future__ import annotations

import sys
import threading
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
    ):
        self.trigger_key = trigger_key.lower()
        self.action_key = action_key.lower()
        self.on_start_recording = on_start_recording
        self.on_stop_recording = on_stop_recording
        self.push_to_talk = push_to_talk

        self._current_keys: Set[keyboard.Key | keyboard.KeyCode] = set()
        self._listener: Optional[keyboard.Listener] = None
        self._is_active = False
        self._lock = threading.Lock()

    def _matches_trigger(self) -> bool:
        """Evaluate if the currently pressed keys match the trigger shortcut."""
        if self.trigger_key in ("right_alt", "alt_r"):
            return keyboard.Key.alt_r in self._current_keys
        elif self.trigger_key in ("alt_space", "alt+space"):
            has_alt = (keyboard.Key.alt in self._current_keys or
                       keyboard.Key.alt_l in self._current_keys or
                       keyboard.Key.alt_r in self._current_keys)
            has_space = keyboard.Key.space in self._current_keys
            return has_alt and has_space
        elif self.trigger_key in ("ctrl_shift_space", "ctrl+shift+space"):
            has_ctrl = (keyboard.Key.ctrl in self._current_keys or
                        keyboard.Key.ctrl_l in self._current_keys or
                        keyboard.Key.ctrl_r in self._current_keys)
            has_shift = (keyboard.Key.shift in self._current_keys or
                         keyboard.Key.shift_l in self._current_keys or
                         keyboard.Key.shift_r in self._current_keys)
            has_space = keyboard.Key.space in self._current_keys
            return has_ctrl and has_shift and has_space
        elif self.trigger_key in ("fn", "globe"):
            return any(
                getattr(k, "vk", None) in (63, 0xFF) or getattr(k, "char", "") == "fn"
                for k in self._current_keys
            )
        return False

    def _matches_action(self) -> bool:
        """Evaluate if the currently pressed keys match the action shortcut."""
        has_shift = (keyboard.Key.shift in self._current_keys or
                     keyboard.Key.shift_l in self._current_keys or
                     keyboard.Key.shift_r in self._current_keys)
        return self._matches_trigger() and has_shift

    def _on_press(self, key):
        with self._lock:
            self._current_keys.add(key)
            is_trigger = self._matches_trigger()
            is_action = self._matches_action()

            if is_trigger:
                if self.push_to_talk:
                    if not self._is_active:
                        self._is_active = True
                        try:
                            self.on_start_recording(is_action)
                        except Exception as e:
                            print(f"[PynputHook] on_start error: {e}", file=sys.stderr)
                else:
                    # Toggle mode
                    self._is_active = not self._is_active
                    if self._is_active:
                        self.on_start_recording(is_action)
                    else:
                        self.on_stop_recording()

    def _on_release(self, key):
        with self._lock:
            if key in self._current_keys:
                self._current_keys.remove(key)

            if self.push_to_talk and self._is_active:
                # If trigger key was released, stop recording
                if not self._matches_trigger():
                    self._is_active = False
                    try:
                        self.on_stop_recording()
                    except Exception as e:
                        print(f"[PynputHook] on_stop error: {e}", file=sys.stderr)

    def start(self) -> bool:
        try:
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception as e:
            print(f"[PynputHook] Failed to start listener: {e}", file=sys.stderr)
            return False

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._is_active = False
