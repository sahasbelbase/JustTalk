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
            # When Right Alt is released, clean up synthetic Ctrl if present.
            if is_right_alt_release:
                ctrl_to_remove = [
                    k for k in self._current_keys
                    if k in (keyboard.Key.ctrl, keyboard.Key.ctrl_l) or getattr(k, "vk", None) in (17, 162)
                ]
                for ck in ctrl_to_remove:
                    self._current_keys.discard(ck)

            if self.push_to_talk and self._is_active:
                # If trigger key was released, stop recording
                if not self._matches_trigger():
                    self._is_active = False
                    try:
                        self.on_stop_recording()
                    except Exception as e:
                        print(f"[PynputHook] on_stop error: {e}", file=sys.stderr)

    def reset_state(self) -> None:
        """Reset internal key tracking and state."""
        with self._lock:
            self._current_keys.clear()
            self._is_active = False

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
