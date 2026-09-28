"""macOS native Quartz Event Tap & AppKit global hotkey monitor."""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable, Optional


class MacHotkeyMonitor:
    """
    Rock-solid macOS hotkey and push-to-talk monitor combining Quartz CGEventTap
    with AppKit NSEvent monitors. Captures Fn/Globe, Right Option, and Right Command
    system-wide across all applications, spaces, and full-screen windows.
    """

    # Quartz / CoreGraphics Modifier Flag Masks
    FN_FLAG_MASK = 0x800000  # 1 << 23 (kCGEventFlagMaskSecondaryFn / Function key)
    SHIFT_FLAG_MASK = 0x20000  # 1 << 17 (kCGEventFlagMaskShift)
    ALT_FLAG_MASK = 0x80000  # 1 << 19 (kCGEventFlagMaskAlternate)
    CMD_FLAG_MASK = 0x100000  # 1 << 20 (kCGEventFlagMaskCommand)
    CTRL_FLAG_MASK = 0x40000  # 1 << 18 (kCGEventFlagMaskControl)

    # Virtual Keycodes on macOS
    KEYCODE_FN = 63  # kVK_Function (Fn / Globe key)
    KEYCODE_LEFT_ALT = 58
    KEYCODE_RIGHT_ALT = 61  # Right Option
    KEYCODE_LEFT_CMD = 55
    KEYCODE_RIGHT_CMD = 54  # Right Command
    KEYCODE_SPACE = 49

    def __init__(
        self,
        on_start_recording: Callable[[bool], None],  # bool: is_action_mode
        on_stop_recording: Callable[[], None],
        trigger_key: str = "fn",
        push_to_talk: bool = True,
    ):
        self.on_start_recording = on_start_recording
        self.on_stop_recording = on_stop_recording
        self.trigger_key = trigger_key.lower().strip()
        self.push_to_talk = push_to_talk

        self._lock = threading.Lock()
        self._is_active = False
        self._is_action_mode = False

        # Quartz Tap references
        self._tap = None
        self._run_loop_source = None
        self._run_loop = None
        self._thread: Optional[threading.Thread] = None

        # AppKit NSEvent monitor references
        self._global_monitor = None
        self._local_monitor = None
        self._running = False

    def start(self) -> bool:
        if sys.platform != "darwin":
            return False

        self.stop()
        self._running = True

        # 1. Start Quartz Event Tap on background thread
        ready_event = threading.Event()
        success_container = [False]

        self._thread = threading.Thread(
            target=self._run_tap_thread,
            args=(ready_event, success_container),
            name="MacQuartzEventTapThread",
            daemon=True,
        )
        self._thread.start()

        ready_event.wait(timeout=1.5)
        tap_ok = success_container[0]

        # 2. Register AppKit companion monitors for maximum resilience
        self._setup_appkit_monitors()

        return tap_ok or (self._global_monitor is not None)

    def _handle_state_change(self, is_down: bool, is_shift: bool) -> None:
        """Thread-safe handler for key transitions."""
        with self._lock:
            if self.push_to_talk:
                if is_down and not self._is_active:
                    self._is_active = True
                    self._is_action_mode = is_shift
                    try:
                        self.on_start_recording(self._is_action_mode)
                    except Exception as e:
                        print(f"[MacHotkeyMonitor] on_start error: {e}", file=sys.stderr)
                elif not is_down and self._is_active:
                    self._is_active = False
                    self._is_action_mode = False
                    try:
                        self.on_stop_recording()
                    except Exception as e:
                        print(f"[MacHotkeyMonitor] on_stop error: {e}", file=sys.stderr)
            else:
                # Toggle mode: trigger on key down edge
                if is_down:
                    self._is_active = not self._is_active
                    if self._is_active:
                        self.on_start_recording(is_shift)
                    else:
                        self.on_stop_recording()

    def _run_tap_thread(self, ready_event: threading.Event, success_container: list[bool]) -> None:
        try:
            import Quartz
            from Quartz import (
                CFMachPortCreateRunLoopSource,
                CFRunLoopAddSource,
                CFRunLoopGetCurrent,
                CFRunLoopRun,
                CFRunLoopStop,
                CGEventGetFlags,
                CGEventGetIntegerValueField,
                CGEventMaskBit,
                CGEventTapCreate,
                CGEventTapEnable,
                kCFRunLoopCommonModes,
                kCGEventFlagsChanged,
                kCGEventKeyDown,
                kCGEventKeyUp,
                kCGEventTapDisabledByTimeout,
                kCGEventTapDisabledByUserInput,
                kCGEventTapOptionListenOnly,
                kCGHeadInsertEventTap,
                kCGKeyboardEventKeycode,
                kCGSessionEventTap,
            )

            def event_callback(proxy, event_type, event, refcon):
                # Auto-recover if macOS temporarily disables tap under high load
                if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
                    if self._tap:
                        CGEventTapEnable(self._tap, True)
                    return event

                if event_type == kCGEventFlagsChanged:
                    flags = CGEventGetFlags(event)
                    keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                    shift_is_active = bool(flags & self.SHIFT_FLAG_MASK)

                    is_down = False
                    if self.trigger_key in ("fn", "globe"):
                        is_down = bool(flags & self.FN_FLAG_MASK)
                    elif self.trigger_key in ("right_alt", "alt_r", "right_option"):
                        is_down = bool(flags & self.ALT_FLAG_MASK) and (
                            keycode == self.KEYCODE_RIGHT_ALT or self._is_active
                        )
                    elif self.trigger_key in ("right_cmd", "cmd_r", "right_command"):
                        is_down = bool(flags & self.CMD_FLAG_MASK) and (
                            keycode == self.KEYCODE_RIGHT_CMD or self._is_active
                        )
                    elif self.trigger_key in ("alt", "option"):
                        is_down = bool(flags & self.ALT_FLAG_MASK)

                    self._handle_state_change(is_down, shift_is_active)

                return event

            # Create event tap for flagsChanged
            mask = CGEventMaskBit(kCGEventFlagsChanged)
            self._tap = CGEventTapCreate(
                kCGSessionEventTap,
                kCGHeadInsertEventTap,
                kCGEventTapOptionListenOnly,
                mask,
                event_callback,
                None,
            )

            if not self._tap:
                print(
                    "[MacHotkeyMonitor] Notice: CGEventTap requires Accessibility permission (AXIsProcessTrusted).",
                    file=sys.stderr,
                )
                success_container[0] = False
                ready_event.set()
                return

            self._run_loop = CFRunLoopGetCurrent()
            self._run_loop_source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
            CFRunLoopAddSource(self._run_loop, self._run_loop_source, kCFRunLoopCommonModes)
            CGEventTapEnable(self._tap, True)

            success_container[0] = True
            ready_event.set()

            # Run CFRunLoop until stop() is called
            CFRunLoopRun()

        except Exception as e:
            print(f"[MacHotkeyMonitor] Exception in event tap thread: {e}", file=sys.stderr)
            success_container[0] = False
            ready_event.set()

    def _setup_appkit_monitors(self) -> None:
        """Register AppKit global & local flagsChanged listeners."""
        try:
            from AppKit import (
                NSEvent,
                NSEventMaskFlagsChanged,
                NSEventModifierFlagCommand,
                NSEventModifierFlagFunction,
                NSEventModifierFlagOption,
                NSEventModifierFlagShift,
            )

            def appkit_handler(event):
                flags = event.modifierFlags()
                shift_is_active = bool(flags & NSEventModifierFlagShift)
                is_down = False

                if self.trigger_key in ("fn", "globe"):
                    is_down = bool(flags & NSEventModifierFlagFunction)
                elif self.trigger_key in ("right_alt", "alt_r", "right_option"):
                    is_down = bool(flags & NSEventModifierFlagOption) and (
                        event.keyCode() == self.KEYCODE_RIGHT_ALT or self._is_active
                    )
                elif self.trigger_key in ("right_cmd", "cmd_r", "right_command"):
                    is_down = bool(flags & NSEventModifierFlagCommand) and (
                        event.keyCode() == self.KEYCODE_RIGHT_CMD or self._is_active
                    )
                elif self.trigger_key in ("alt", "option"):
                    is_down = bool(flags & NSEventModifierFlagOption)

                self._handle_state_change(is_down, shift_is_active)
                return event

            self._global_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSEventMaskFlagsChanged, appkit_handler
            )
            self._local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                NSEventMaskFlagsChanged, appkit_handler
            )
        except Exception:
            pass

    def stop(self) -> None:
        self._running = False

        # Cleanup AppKit monitors
        try:
            from AppKit import NSEvent

            if self._global_monitor:
                NSEvent.removeMonitor_(self._global_monitor)
                self._global_monitor = None
            if self._local_monitor:
                NSEvent.removeMonitor_(self._local_monitor)
                self._local_monitor = None
        except Exception:
            pass

        # Cleanup Quartz Event Tap
        if self._run_loop:
            try:
                from Quartz import CFRunLoopStop

                CFRunLoopStop(self._run_loop)
            except Exception:
                pass
            self._run_loop = None

        self._tap = None
        self._run_loop_source = None
        with self._lock:
            self._is_active = False


# Backward compatibility alias
MacFnKeyMonitor = MacHotkeyMonitor

