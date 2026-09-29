"""macOS native Quartz Event Tap global hotkey monitor."""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable, Optional


class MacHotkeyMonitor:
    """
    Production-grade macOS system-wide hotkey and hold-to-talk monitor using
    Quartz CGEventTap with dedicated CFRunLoop.
    
    Captures Fn/Globe (via flagsChanged and SecondaryFn flag transitions),
    Right Option, Right Command, and Control+Space across all applications,
    spaces, and full-screen windows (Wispr Flow / Typeless behavior).
    """

    # Quartz / CoreGraphics Modifier Flag Masks
    FN_FLAG_MASK = 0x800000  # 1 << 23 (kCGEventFlagMaskSecondaryFn / Function key)
    SHIFT_FLAG_MASK = 0x20000  # 1 << 17 (kCGEventFlagMaskShift)
    ALT_FLAG_MASK = 0x80000  # 1 << 19 (kCGEventFlagMaskAlternate)
    CMD_FLAG_MASK = 0x100000  # 1 << 20 (kCGEventFlagMaskCommand)
    CTRL_FLAG_MASK = 0x40000  # 1 << 18 (kCGEventFlagMaskControl)

    # Virtual Keycodes on macOS
    KEYCODE_FN = 63  # kVK_Function (Fn / Globe key on Apple keyboards)
    KEYCODE_GLOBE_ALT = 179  # Globe key on some Apple Silicon / ISO keyboards
    KEYCODE_LEFT_ALT = 58
    KEYCODE_RIGHT_ALT = 61  # Right Option
    KEYCODE_LEFT_CMD = 55
    KEYCODE_RIGHT_CMD = 54  # Right Command
    KEYCODE_LEFT_CTRL = 59
    KEYCODE_SPACE = 49

    # Minimum hold duration in seconds to consider it a deliberate hold-to-talk action
    DEBOUNCE_DELAY_SEC = 0.080  # 80ms for ultra-responsive trigger

    # macOS Virtual Keycodes that form legitimate Fn system combinations:
    # Forward Delete, Arrow navigation (Home/End/PageUp/PageDown), and F1-F12
    FN_COMBINATION_KEYS = {
        51,  # Delete / Backspace (Fn+Delete = Forward Delete)
        123, 124, 125, 126,  # Left, Right, Down, Up (Home, End, PageUp, PageDown)
        122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111,  # F1 - F12
    }

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
        self._press_start_time = 0.0

        # State tracking for transition detection and combo filtering
        self._prev_trigger_down = False
        self._prev_flags = 0
        self._cancelled_by_combination = False
        self._debounce_timer: Optional[threading.Timer] = None

        # Quartz Tap references
        self._tap = None
        self._run_loop_source = None
        self._run_loop = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def is_tap_active(self) -> bool:
        """Check whether the Quartz CGEventTap is currently created and running."""
        with self._lock:
            return bool(self._running and self._tap is not None)

    def reset_state(self) -> None:
        """Reset internal active flags to idle and cancel any pending debounce timers."""
        with self._lock:
            self._is_active = False
            self._is_action_mode = False
            self._cancelled_by_combination = False
            self._prev_trigger_down = False
            if self._debounce_timer:
                self._debounce_timer.cancel()
                self._debounce_timer = None

    def start(self) -> bool:
        """Start Quartz CGEventTap on a dedicated background thread with CFRunLoop."""
        if sys.platform != "darwin":
            return False

        self.stop()
        self._running = True

        ready_event = threading.Event()
        success_container = [False]

        self._thread = threading.Thread(
            target=self._run_tap_thread,
            args=(ready_event, success_container),
            name="MacQuartzEventTapThread",
            daemon=True,
        )
        self._thread.start()

        # Wait for run loop initialization
        ready_event.wait(timeout=2.0)
        tap_ok = success_container[0]

        if not tap_ok:
            print(
                "[MacHotkeyMonitor] Quartz EventTap creation failed. "
                "Ensure Accessibility and Input Monitoring permissions are granted.",
                file=sys.stderr,
            )
            self._running = False
        else:
            print(
                f"[MacHotkeyMonitor] System-wide Quartz EventTap active for trigger '{self.trigger_key}'.",
                file=sys.stderr,
            )
            self._start_keepalive_watchdog()

        return tap_ok

    def _start_keepalive_watchdog(self) -> None:
        """Periodic watchdog to ensure event tap stays enabled across macOS space switches and app transitions."""
        def watchdog():
            while self._running:
                time.sleep(2.0)
                if not self._running:
                    break
                if self._tap is not None:
                    try:
                        from Quartz import CGEventTapIsEnabled, CGEventTapEnable
                        if not CGEventTapIsEnabled(self._tap):
                            CGEventTapEnable(self._tap, True)
                    except Exception:
                        pass

        w_thread = threading.Thread(target=watchdog, daemon=True, name="HotkeyTapWatchdog")
        w_thread.start()

    def _cancel_debounce(self) -> None:
        """Cancel any pending debounce timer safely."""
        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._debounce_timer = None

    def _fire_start(self, is_action_mode: bool) -> None:
        """Invoked after debounce delay when key has been steadily held down."""
        to_start = False
        with self._lock:
            self._debounce_timer = None
            if self._running and self._prev_trigger_down and not self._cancelled_by_combination and not self._is_active:
                self._is_active = True
                self._is_action_mode = is_action_mode
                to_start = True

        if to_start:
            try:
                print(
                    f"[MacHotkeyMonitor] Hold detected (>{int(self.DEBOUNCE_DELAY_SEC * 1000)}ms), "
                    f"START recording (action_mode={is_action_mode})",
                    file=sys.stderr,
                )
                self.on_start_recording(is_action_mode)
            except Exception as e:
                print(f"[MacHotkeyMonitor] on_start error: {e}", file=sys.stderr)

    def _handle_trigger_state(self, is_down: bool, is_shift: bool) -> None:
        """
        Handle key transition changes with debounce and combination cancellation.
        Ensures quick accidental taps (<80ms) are filtered and callbacks are invoked outside lock.
        """
        to_stop = False

        with self._lock:
            if is_down:
                if not self._prev_trigger_down:
                    self._prev_trigger_down = True
                    self._press_start_time = time.time()
                    self._cancelled_by_combination = False

                    if self.push_to_talk:
                        # Schedule debounce timer
                        self._cancel_debounce()
                        self._debounce_timer = threading.Timer(
                            self.DEBOUNCE_DELAY_SEC, self._fire_start, args=(is_shift,)
                        )
                        self._debounce_timer.daemon = True
                        self._debounce_timer.start()
                    else:
                        # Toggle mode: click to start, click to stop
                        if not self._is_active:
                            self._is_active = True
                            self._is_action_mode = is_shift
                            to_start = True
                        else:
                            if time.time() - self._press_start_time > 0.20:
                                self._is_active = False
                                to_stop = True
            else:
                # Key released (Key up)
                if self._prev_trigger_down:
                    self._prev_trigger_down = False
                    self._cancel_debounce()

                    if self._cancelled_by_combination:
                        # Key was released after being used in a combination (e.g. Fn+F1)
                        self._cancelled_by_combination = False
                        if self._is_active:
                            self._is_active = False
                            to_stop = True
                    elif self._is_active:
                        if self.push_to_talk:
                            self._is_active = False
                            self._is_action_mode = False
                            to_stop = True

        if to_stop:
            try:
                print("[MacHotkeyMonitor] Key released, STOP recording", file=sys.stderr)
                self.on_stop_recording()
            except Exception as e:
                print(f"[MacHotkeyMonitor] on_stop error: {e}", file=sys.stderr)

    def _handle_other_key_down(self, keycode: int) -> None:
        """
        Called when another key is pressed while the trigger key is held.
        Only treats verified system combination keys (Fn+arrows, Fn+delete, Fn+F1-F12)
        as combinations to cancel voice recording, ignoring regular app keys.
        """
        if keycode not in self.FN_COMBINATION_KEYS:
            return

        to_stop = False
        with self._lock:
            if self._prev_trigger_down:
                self._cancelled_by_combination = True
                self._cancel_debounce()
                if self._is_active:
                    self._is_active = False
                    to_stop = True
                    print(
                        f"[MacHotkeyMonitor] Fn combination detected with keycode {keycode}; "
                        "cancelling voice trigger.",
                        file=sys.stderr,
                    )

        if to_stop:
            try:
                self.on_stop_recording()
            except Exception as e:
                print(f"[MacHotkeyMonitor] on_stop error on combination cancel: {e}", file=sys.stderr)


    def _run_tap_thread(self, ready_event: threading.Event, success_container: list[bool]) -> None:
        """Entry point for background thread running Quartz CFRunLoop."""
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
                kCGEventTapDisabledByTimeout,
                kCGEventTapDisabledByUserInput,
                kCGEventTapOptionListenOnly,
                kCGHeadInsertEventTap,
                kCGKeyboardEventKeycode,
                kCGSessionEventTap,
            )

            def event_callback(proxy, event_type, event, refcon):
                # 1. Auto-recover if macOS temporarily disables tap under high CPU load
                if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
                    if self._tap is not None:
                        try:
                            CGEventTapEnable(self._tap, True)
                            print("[MacHotkeyMonitor] Re-enabled event tap after timeout/user input disable.", file=sys.stderr)
                        except Exception:
                            pass
                    return event

                # 2. Check for key down events (only active if trigger is space-based)
                if event_type == kCGEventKeyDown:
                    if self.trigger_key not in ("ctrl_space", "ctrl+space", "alt_space", "alt+space"):
                        return event
                    keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                    if keycode != self.KEYCODE_SPACE:
                        return event
                    flags = CGEventGetFlags(event)
                    is_shift = bool(flags & self.SHIFT_FLAG_MASK)
                    if self.trigger_key in ("ctrl_space", "ctrl+space") and bool(flags & self.CTRL_FLAG_MASK):
                        self._handle_trigger_state(True, is_shift)
                    elif self.trigger_key in ("alt_space", "alt+space") and bool(flags & self.ALT_FLAG_MASK):
                        self._handle_trigger_state(True, is_shift)
                    return event

                # 3. Check modifier flagsChanged transitions
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

                    # Only process when the trigger flag state has actually changed
                    if is_down != self._prev_trigger_down:
                        self._handle_trigger_state(is_down, shift_is_active)

                return event

            # Create event tap: ONLY intercept modifier changes for modifier keys (Fn, Globe, Option, Cmd)
            # This completely avoids intercepting regular user typing, preventing macOS from disabling the tap.
            if self.trigger_key in ("ctrl_space", "ctrl+space", "alt_space", "alt+space"):
                mask = CGEventMaskBit(kCGEventFlagsChanged) | CGEventMaskBit(kCGEventKeyDown)
            else:
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

    def stop(self) -> None:
        """Stop event tap and terminate run loop cleanly."""
        self._running = False
        self._cancel_debounce()

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
            self._prev_trigger_down = False
            self._cancelled_by_combination = False


# Backward compatibility alias
MacFnKeyMonitor = MacHotkeyMonitor
