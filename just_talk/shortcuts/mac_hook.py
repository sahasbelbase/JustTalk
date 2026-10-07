"""macOS native dual-engine global hotkey and hold-to-talk monitor."""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable, Optional


class MacHotkeyMonitor:
    """
    Production-grade macOS system-wide hotkey and hold-to-talk monitor.
    
    Uses a resilient DUAL-ENGINE architecture:
    1. AppKit NSEvent Global + Local Monitors: Intercepts modifier transitions
       (Fn/Globe, Right Option, Right Command) across ALL applications and spaces
       via macOS Input Monitoring.
    2. Quartz CGEventTap: Low-level HID/Session event tap with dedicated CFRunLoop
       for rock-solid hardware-level interception.

    This ensures Fn / push-to-talk works seamlessly across third-party apps
    (Brave, Teams, Antigravity, VS Code, Notes, etc.) without losing focus.
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
    KEYCODE_V = 9

    # NSEvent monitors and the Quartz tap both see every key press; collapse them into one action
    PASTE_LAST_DEDUPE_SEC = 0.4

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
        on_action_mode_changed: Optional[Callable[[bool], None]] = None,
        on_cancel_recording: Optional[Callable[[], None]] = None,
        on_paste_last: Optional[Callable[[], None]] = None,
    ):
        self.on_start_recording = on_start_recording
        self.on_stop_recording = on_stop_recording
        self.trigger_key = trigger_key.lower().strip()
        self.push_to_talk = push_to_talk
        self.on_action_mode_changed = on_action_mode_changed
        self.on_cancel_recording = on_cancel_recording
        self.on_paste_last = on_paste_last
        self._last_paste_last_time = 0.0

        self._lock = threading.Lock()
        self._is_active = False
        self._is_action_mode = False
        self._press_start_time = 0.0
        self._last_toggle_time = 0.0

        # State tracking for transition detection and combo filtering
        self._prev_trigger_down = False
        self._prev_flags = 0
        self._cancelled_by_combination = False
        self._debounce_timer: Optional[threading.Timer] = None

        # AppKit Monitor references
        self._global_monitor = None
        self._local_monitor = None

        # Quartz Tap references
        self._tap = None
        self._run_loop_source = None
        self._run_loop = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def is_tap_active(self) -> bool:
        """Check whether at least one monitor engine is currently running."""
        with self._lock:
            return bool(self._running and (self._tap is not None or self._global_monitor is not None))

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
        """Start dual-engine global hotkey monitoring on macOS."""
        if sys.platform != "darwin":
            return False

        self.stop()
        self._running = True

        # Engine 1: Install AppKit NSEvent global & local monitors (requires Input Monitoring)
        ns_ok = self._install_ns_monitors()

        # Engine 2: Install Quartz CGEventTap on dedicated background thread (requires Accessibility)
        ready_event = threading.Event()
        success_container = [False]

        self._thread = threading.Thread(
            target=self._run_tap_thread,
            args=(ready_event, success_container),
            name="MacQuartzEventTapThread",
            daemon=True,
        )
        self._thread.start()

        ready_event.wait(timeout=2.0)
        tap_ok = success_container[0]

        is_active = ns_ok or tap_ok
        if not is_active:
            print(
                "[MacHotkeyMonitor] Both NSEvent and CGEventTap monitors failed. "
                "Ensure Input Monitoring and Accessibility permissions are enabled.",
                file=sys.stderr,
            )
            self._running = False
        else:
            print(
                f"[MacHotkeyMonitor] Global monitoring active for '{self.trigger_key}' "
                f"(NSEvent={ns_ok}, QuartzTap={tap_ok}).",
                file=sys.stderr,
            )
            if tap_ok:
                self._start_keepalive_watchdog()

        return is_active

    def _install_ns_monitors(self) -> bool:
        """Install AppKit global & local event monitors for seamless cross-app modifier detection."""
        try:
            import AppKit

            def ns_event_callback(event):
                try:
                    event_type = event.type()
                    # KeyDown for space shortcuts
                    if event_type == AppKit.NSEventTypeKeyDown:
                        if event.keyCode() == self.KEYCODE_V and not event.isARepeat():
                            flags = event.modifierFlags()
                            if self._is_paste_last_combo(
                                bool(flags & AppKit.NSEventModifierFlagControl),
                                bool(flags & AppKit.NSEventModifierFlagCommand),
                            ):
                                self._fire_paste_last()
                                return event
                        if self.trigger_key in ("ctrl_space", "ctrl+space", "alt_space", "alt+space"):
                            keycode = event.keyCode()
                            if keycode == self.KEYCODE_SPACE:
                                flags = event.modifierFlags()
                                is_shift = bool(flags & AppKit.NSEventModifierFlagShift)
                                if self.trigger_key in ("ctrl_space", "ctrl+space") and bool(flags & AppKit.NSEventModifierFlagControl):
                                    self._handle_trigger_state(True, is_shift)
                                elif self.trigger_key in ("alt_space", "alt+space") and bool(flags & AppKit.NSEventModifierFlagOption):
                                    self._handle_trigger_state(True, is_shift)
                        return event

                    # FlagsChanged (Fn, Option, Cmd)
                    if event_type == AppKit.NSEventTypeFlagsChanged:
                        flags = event.modifierFlags()
                        keycode = event.keyCode()
                        shift_is_active = bool(flags & AppKit.NSEventModifierFlagShift)

                        is_down = False
                        if self.trigger_key in ("fn", "globe", "right_alt", "alt_r", "right_option"):
                            # Support both Fn/Globe and Right Option
                            is_fn_down = bool(flags & AppKit.NSEventModifierFlagFunction)
                            is_right_alt_down = bool(flags & AppKit.NSEventModifierFlagOption) and (
                                keycode == self.KEYCODE_RIGHT_ALT or self._is_active
                            )
                            is_down = is_fn_down or is_right_alt_down
                        elif self.trigger_key in ("right_cmd", "cmd_r", "right_command"):
                            is_down = bool(flags & AppKit.NSEventModifierFlagCommand) and (
                                keycode == self.KEYCODE_RIGHT_CMD or self._is_active
                            )
                        elif self.trigger_key in ("alt", "option"):
                            is_down = bool(flags & AppKit.NSEventModifierFlagOption)

                        if is_down != self._prev_trigger_down or (is_down and shift_is_active != self._is_action_mode):
                            self._handle_trigger_state(is_down, shift_is_active)
                except Exception:
                    pass
                return event

            mask = AppKit.NSEventMaskFlagsChanged
            if self.on_paste_last or self.trigger_key in ("ctrl_space", "ctrl+space", "alt_space", "alt+space"):
                mask |= AppKit.NSEventMaskKeyDown

            self._global_monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                mask, ns_event_callback
            )
            self._local_monitor = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                mask, ns_event_callback
            )
            return self._global_monitor is not None or self._local_monitor is not None
        except Exception as e:
            print(f"[MacHotkeyMonitor] NSEvent monitor error: {e}", file=sys.stderr)
            return False

    def _start_keepalive_watchdog(self) -> None:
        """Periodic watchdog to ensure event tap stays enabled across macOS space switches."""
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
        Supports dynamically switching into/out of Action Mode while holding the trigger key.
        """
        to_start = False
        to_stop = False
        action_changed: Optional[bool] = None

        with self._lock:
            if is_down:
                if not self._prev_trigger_down:
                    self._prev_trigger_down = True
                    now = time.time()
                    self._press_start_time = now
                    self._cancelled_by_combination = False
                    self._is_action_mode = is_shift

                    if self.push_to_talk:
                        # Schedule debounce timer for push-to-talk
                        self._cancel_debounce()
                        self._debounce_timer = threading.Timer(
                            self.DEBOUNCE_DELAY_SEC, self._fire_start, args=(is_shift,)
                        )
                        self._debounce_timer.daemon = True
                        self._debounce_timer.start()
                    else:
                        # Foolproof Toggle Mode: Tap to Start, Tap to Stop
                        # Hardware debounce threshold (250ms) protects against switch bounce
                        if now - self._last_toggle_time >= 0.25:
                            self._last_toggle_time = now
                            if not self._is_active:
                                self._is_active = True
                                self._is_action_mode = is_shift
                                to_start = True
                            else:
                                self._is_active = False
                                self._is_action_mode = False
                                to_stop = True
                else:
                    # Key is already held down! Dynamically update action mode if Shift was pressed/released
                    if is_shift != self._is_action_mode:
                        self._is_action_mode = is_shift
                        if self._is_active:
                            action_changed = is_shift
                        elif self._debounce_timer:
                            self._cancel_debounce()
                            self._debounce_timer = threading.Timer(
                                self.DEBOUNCE_DELAY_SEC, self._fire_start, args=(is_shift,)
                            )
                            self._debounce_timer.daemon = True
                            self._debounce_timer.start()
            else:
                # Key released (Key up)
                if self._prev_trigger_down:
                    self._prev_trigger_down = False
                    self._cancel_debounce()

                    if self._cancelled_by_combination:
                        self._cancelled_by_combination = False
                        if self._is_active:
                            self._is_active = False
                            to_stop = True
                    elif self._is_active and self.push_to_talk:
                        # In Push-to-Talk mode, releasing the key stops recording
                        self._is_active = False
                        self._is_action_mode = False
                        to_stop = True

        if to_start:
            try:
                print(f"[MacHotkeyMonitor] Toggle START recording (action_mode={is_shift})", file=sys.stderr)
                self.on_start_recording(is_shift)
            except Exception as e:
                print(f"[MacHotkeyMonitor] on_start error: {e}", file=sys.stderr)

        if action_changed is not None and self.on_action_mode_changed:
            try:
                print(f"[MacHotkeyMonitor] Dynamic Action Mode change: {action_changed}", file=sys.stderr)
                self.on_action_mode_changed(action_changed)
            except Exception as e:
                print(f"[MacHotkeyMonitor] on_action_mode_changed error: {e}", file=sys.stderr)

        if to_stop:
            try:
                print("[MacHotkeyMonitor] STOP recording", file=sys.stderr)
                self.on_stop_recording()
            except Exception as e:
                print(f"[MacHotkeyMonitor] on_stop error: {e}", file=sys.stderr)

    def _is_paste_last_combo(self, ctrl_down: bool, cmd_down: bool) -> bool:
        """Ctrl+Cmd+V re-pastes the last dictation."""
        return bool(self.on_paste_last) and ctrl_down and cmd_down

    def _fire_paste_last(self) -> None:
        cancel_recording = False
        with self._lock:
            now = time.time()
            if now - self._last_paste_last_time < self.PASTE_LAST_DEDUPE_SEC:
                return
            self._last_paste_last_time = now
            if self._is_active:
                # Right Cmd can be the dictation key, so this combo may have just started a recording
                self._is_active = False
                self._is_action_mode = False
                cancel_recording = True
            self._cancel_debounce()

        if cancel_recording and self.on_cancel_recording:
            try:
                self.on_cancel_recording()
            except Exception as e:
                print(f"[MacHotkeyMonitor] cancel error: {e}", file=sys.stderr)
        print("[MacHotkeyMonitor] Ctrl+Cmd+V -> paste last dictation", file=sys.stderr)
        try:
            self.on_paste_last()
        except Exception as e:
            print(f"[MacHotkeyMonitor] on_paste_last error: {e}", file=sys.stderr)

    def _handle_other_key_down(self, keycode: int) -> None:
        """
        Called when another key is pressed while the trigger key is held or active.
        Cancels voice recording on Escape (keycode 53) or legitimate system combinations (Fn+F1-F12, Fn+arrows, Fn+delete).
        """
        # Emergency Cancel: Escape key (macOS kVK_Escape = 53)
        if keycode == 53:
            to_cancel = False
            with self._lock:
                if self._is_active or self._prev_trigger_down:
                    self._cancelled_by_combination = True
                    self._cancel_debounce()
                    if self._is_active:
                        self._is_active = False
                        to_cancel = True
            if to_cancel:
                print("[MacHotkeyMonitor] Escape key pressed -> CANCEL recording", file=sys.stderr)
                try:
                    if self.on_cancel_recording:
                        self.on_cancel_recording()
                    else:
                        self.on_stop_recording()
                except Exception as e:
                    print(f"[MacHotkeyMonitor] cancel error: {e}", file=sys.stderr)
            return

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
                kCGHIDEventTap,
            )

            def event_callback(proxy, event_type, event, refcon):
                # 1. Auto-recover if macOS temporarily disables tap under high load
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
                    keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                    if keycode == self.KEYCODE_V:
                        flags = CGEventGetFlags(event)
                        is_repeat = CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat)
                        if not is_repeat and self._is_paste_last_combo(
                            bool(flags & self.CTRL_FLAG_MASK), bool(flags & self.CMD_FLAG_MASK)
                        ):
                            self._fire_paste_last()
                            return event
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
                    if self.trigger_key in ("fn", "globe", "right_alt", "alt_r", "right_option"):
                        is_fn_down = bool(flags & self.FN_FLAG_MASK)
                        is_right_alt_down = bool(flags & self.ALT_FLAG_MASK) and (
                            keycode == self.KEYCODE_RIGHT_ALT or self._is_active
                        )
                        is_down = is_fn_down or is_right_alt_down
                    elif self.trigger_key in ("right_cmd", "cmd_r", "right_command"):
                        is_down = bool(flags & self.CMD_FLAG_MASK) and (
                            keycode == self.KEYCODE_RIGHT_CMD or self._is_active
                        )
                    elif self.trigger_key in ("alt", "option"):
                        is_down = bool(flags & self.ALT_FLAG_MASK)

                    if is_down != self._prev_trigger_down or (is_down and shift_is_active != self._is_action_mode):
                        self._handle_trigger_state(is_down, shift_is_active)

                return event

            if self.on_paste_last or self.trigger_key in ("ctrl_space", "ctrl+space", "alt_space", "alt+space"):
                mask = CGEventMaskBit(kCGEventFlagsChanged) | CGEventMaskBit(kCGEventKeyDown)
            else:
                mask = CGEventMaskBit(kCGEventFlagsChanged)

            # Try HID event tap first (system-wide hardware level), fallback to session tap
            self._tap = CGEventTapCreate(
                kCGHIDEventTap,
                kCGHeadInsertEventTap,
                kCGEventTapOptionListenOnly,
                mask,
                event_callback,
                None,
            )
            if not self._tap:
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
        """Stop event monitors and terminate run loops cleanly."""
        self._running = False
        self._cancel_debounce()

        # Clean up AppKit monitors
        if self._global_monitor:
            try:
                import AppKit
                AppKit.NSEvent.removeMonitor_(self._global_monitor)
            except Exception:
                pass
            self._global_monitor = None

        if self._local_monitor:
            try:
                import AppKit
                AppKit.NSEvent.removeMonitor_(self._local_monitor)
            except Exception:
                pass
            self._local_monitor = None

        # Clean up Quartz CFRunLoop
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
