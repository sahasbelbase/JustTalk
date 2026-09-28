"""macOS native Function (Fn/Globe) key push-to-talk monitor."""

from __future__ import annotations

import sys
import threading
from typing import Callable, Optional


class MacFnKeyMonitor:
    """
    Monitors the macOS Function (Fn/Globe) key state via AppKit flagsChanged events.
    Supports push-to-talk (Hold Fn to speak, release to stop)
    and Action Mode (Hold Fn + Shift).
    """

    def __init__(
        self,
        on_start_recording: Callable[[bool], None],  # bool: is_action_mode
        on_stop_recording: Callable[[], None],
    ):
        self.on_start_recording = on_start_recording
        self.on_stop_recording = on_stop_recording
        self._is_fn_down = False
        self._is_action_mode = False
        self._monitor = None
        self._running = False

    def start(self) -> bool:
        if sys.platform != "darwin":
            return False

        try:
            from AppKit import (
                NSEvent,
                NSEventMaskFlagsChanged,
                NSEventModifierFlagFunction,
                NSEventModifierFlagShift,
            )

            def flags_changed_handler(event):
                flags = event.modifierFlags()
                fn_pressed = bool(flags & NSEventModifierFlagFunction)
                shift_pressed = bool(flags & NSEventModifierFlagShift)

                if fn_pressed and not self._is_fn_down:
                    # Fn key pressed down -> Start Recording
                    self._is_fn_down = True
                    self._is_action_mode = shift_pressed
                    try:
                        self.on_start_recording(self._is_action_mode)
                    except Exception as e:
                        print(f"[MacFnHook] on_start error: {e}", file=sys.stderr)

                elif not fn_pressed and self._is_fn_down:
                    # Fn key released -> Stop Recording & Transcribe
                    self._is_fn_down = False
                    self._is_action_mode = False
                    try:
                        self.on_stop_recording()
                    except Exception as e:
                        print(f"[MacFnHook] on_stop error: {e}", file=sys.stderr)

            # Register AppKit global event monitor
            self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSEventMaskFlagsChanged, flags_changed_handler
            )
            self._running = True
            return True

        except Exception as e:
            print(f"[MacFnHook] Failed to initialize macOS Fn event tap: {e}", file=sys.stderr)
            return False

    def stop(self) -> None:
        if self._monitor is not None:
            try:
                from AppKit import NSEvent

                NSEvent.removeMonitor_(self._monitor)
            except Exception:
                pass
            self._monitor = None
        self._running = False
