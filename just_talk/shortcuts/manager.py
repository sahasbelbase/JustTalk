"""Central shortcut manager coordinating platform-specific hooks."""

from __future__ import annotations

import sys
from typing import Callable, Optional

from .fallback_hook import PynputHotkeyMonitor
from .mac_hook import MacFnKeyMonitor


class ShortcutManager:
    """Manages active global hotkey listeners for voice input triggers."""

    def __init__(
        self,
        shortcut: str,
        action_shortcut: str,
        push_to_talk: bool,
        on_start_recording: Callable[[bool], None],
        on_stop_recording: Callable[[], None],
    ):
        self.shortcut = shortcut
        self.action_shortcut = action_shortcut
        self.push_to_talk = push_to_talk
        self.on_start_recording = on_start_recording
        self.on_stop_recording = on_stop_recording

        self._mac_monitor: Optional[MacFnKeyMonitor] = None
        self._pynput_monitor: Optional[PynputHotkeyMonitor] = None

    def start(self) -> bool:
        self.stop()

        if sys.platform == "darwin" and self.shortcut.lower() in (
            "fn",
            "globe",
            "right_alt",
            "alt_r",
            "right_option",
            "right_cmd",
            "cmd_r",
            "right_command",
            "alt",
            "option",
        ):
            self._mac_monitor = MacFnKeyMonitor(
                on_start_recording=self.on_start_recording,
                on_stop_recording=self.on_stop_recording,
                trigger_key=self.shortcut,
                push_to_talk=self.push_to_talk,
            )
            ok = self._mac_monitor.start()
            if ok:
                return True
            print("[ShortcutManager] MacHotkeyMonitor failed; falling back to pynput.", file=sys.stderr)

        # Cross-platform fallback listener
        self._pynput_monitor = PynputHotkeyMonitor(
            trigger_key=self.shortcut,
            action_key=self.action_shortcut,
            push_to_talk=self.push_to_talk,
            on_start_recording=self.on_start_recording,
            on_stop_recording=self.on_stop_recording,
        )
        return self._pynput_monitor.start()

    def stop(self) -> None:
        if self._mac_monitor:
            self._mac_monitor.stop()
            self._mac_monitor = None
        if self._pynput_monitor:
            self._pynput_monitor.stop()
            self._pynput_monitor = None

    def reset_state(self) -> None:
        """Reset monitor states when cancelled or finished."""
        if self._mac_monitor and hasattr(self._mac_monitor, "reset_state"):
            self._mac_monitor.reset_state()

    def reload(self, shortcut: str, action_shortcut: str, push_to_talk: bool) -> bool:
        self.shortcut = shortcut
        self.action_shortcut = action_shortcut
        self.push_to_talk = push_to_talk
        return self.start()
