"""Unit tests for macOS hotkey detection, debounce, and permission verification."""

import sys
import time
import pytest

from just_talk.shortcuts.mac_hook import MacHotkeyMonitor
from just_talk.system.permissions import PermissionsManager


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific hotkey tests")
def test_permissions_manager_checks():
    """Verify PermissionsManager methods return expected types without exceptions."""
    acc = PermissionsManager.check_accessibility(prompt_if_needed=False)
    assert isinstance(acc, bool)

    input_mon = PermissionsManager.check_input_monitoring()
    assert isinstance(input_mon, bool)

    all_perms = PermissionsManager.check_all_permissions()
    assert "accessibility" in all_perms
    assert "input_monitoring" in all_perms
    assert "microphone" in all_perms
    assert "fn_emoji_disabled" in all_perms


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific hotkey tests")
def test_mac_hotkey_monitor_lifecycle():
    """Verify MacHotkeyMonitor initializes, starts, and cleanly stops."""
    started = []
    stopped = []

    monitor = MacHotkeyMonitor(
        on_start_recording=lambda action: started.append(action),
        on_stop_recording=lambda: stopped.append(True),
        trigger_key="fn",
        push_to_talk=True,
    )

    assert not monitor.is_tap_active()

    # Start monitor
    ok = monitor.start()
    assert isinstance(ok, bool)

    # Reset state
    monitor.reset_state()
    assert not monitor._is_active
    assert not monitor._prev_trigger_down

    # Clean stop
    monitor.stop()
    assert not monitor.is_tap_active()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific hotkey tests")
def test_mac_hotkey_monitor_combo_cancellation():
    """Verify that pressing another key while trigger is held cancels the voice trigger."""
    started = []
    stopped = []

    monitor = MacHotkeyMonitor(
        on_start_recording=lambda action: started.append(action),
        on_stop_recording=lambda: stopped.append(True),
        trigger_key="fn",
        push_to_talk=True,
    )

    # Simulate Fn press down
    monitor._handle_trigger_state(is_down=True, is_shift=False)
    assert monitor._prev_trigger_down is True

    # Simulate another keydown (e.g. F1 keycode 122 or arrow key) before or after debounce
    monitor._handle_other_key_down(keycode=122)
    assert monitor._cancelled_by_combination is True

    # Simulate Fn key release
    monitor._handle_trigger_state(is_down=False, is_shift=False)
    assert monitor._cancelled_by_combination is False

    # Should not have triggered any start recording
    assert len(started) == 0

    monitor.stop()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific hotkey tests")
def test_mac_hotkey_monitor_dynamic_shift():
    """Verify that pressing Shift while holding the trigger key switches to Action Mode dynamically."""
    started = []
    stopped = []
    action_changes = []

    monitor = MacHotkeyMonitor(
        on_start_recording=lambda action: started.append(action),
        on_stop_recording=lambda: stopped.append(True),
        trigger_key="fn",
        push_to_talk=True,
        on_action_mode_changed=lambda is_action: action_changes.append(is_action),
    )
    monitor._running = True

    # 1. Simulate Fn press down without shift
    monitor._handle_trigger_state(is_down=True, is_shift=False)
    # Wait for debounce to fire safely on busy CI runners
    start_time = time.time()
    while not monitor._is_active and (time.time() - start_time) < 2.0:
        time.sleep(0.01)

    assert monitor._is_active is True
    assert started == [False]
    assert action_changes == []

    # 2. Press Shift while holding Fn
    monitor._handle_trigger_state(is_down=True, is_shift=True)
    assert monitor._is_action_mode is True
    assert action_changes == [True]

    # 3. Release Shift while still holding Fn
    monitor._handle_trigger_state(is_down=True, is_shift=False)
    assert monitor._is_action_mode is False
    assert action_changes == [True, False]

    # 4. Release Fn
    monitor._handle_trigger_state(is_down=False, is_shift=False)
    assert monitor._is_active is False
    assert len(stopped) == 1

    monitor.stop()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific hotkey tests")
def test_mac_hotkey_monitor_toggle_mode():
    """Verify Tap-to-Start and Tap-to-Stop (toggle mode)."""
    started = []
    stopped = []

    monitor = MacHotkeyMonitor(
        on_start_recording=lambda action: started.append(action),
        on_stop_recording=lambda: stopped.append(True),
        trigger_key="fn",
        push_to_talk=False,  # Toggle mode
    )
    monitor._running = True

    # 1. Tap 1 (Press down and release Fn) -> Should start recording
    monitor._handle_trigger_state(is_down=True, is_shift=False)
    monitor._handle_trigger_state(is_down=False, is_shift=False)
    assert monitor._is_active is True
    assert started == [False]
    assert stopped == []

    # Wait past 250ms debounce window
    time.sleep(0.3)

    # 2. Tap 2 (Press down and release Fn again) -> Should stop recording
    monitor._handle_trigger_state(is_down=True, is_shift=False)
    monitor._handle_trigger_state(is_down=False, is_shift=False)
    assert monitor._is_active is False
    assert len(stopped) == 1

    monitor.stop()

