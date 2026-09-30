"""Unit tests for cross-platform and Windows PynputHotkeyMonitor."""

from pynput import keyboard
from just_talk.shortcuts.fallback_hook import PynputHotkeyMonitor


def test_right_alt_and_altgr_matching():
    started = []
    stopped = []

    monitor = PynputHotkeyMonitor(
        trigger_key="right_alt",
        action_key="ctrl_shift_space",
        on_start_recording=lambda is_action: started.append(is_action),
        on_stop_recording=lambda: stopped.append(True),
        push_to_talk=True,
    )

    # 1. Test Key.alt_r
    monitor._on_press(keyboard.Key.alt_r)
    assert monitor._is_active is True
    assert len(started) == 1
    assert started[-1] is False

    monitor._on_release(keyboard.Key.alt_r)
    assert monitor._is_active is False
    assert len(stopped) == 1

    # 2. Test Key.alt_gr (what Windows pynput actually generates on press)
    alt_gr_key = getattr(keyboard.Key, "alt_gr", keyboard.KeyCode(vk=165))
    monitor._on_press(alt_gr_key)
    assert monitor._is_active is True
    assert len(started) == 2

    # Simulate Windows also sending synthetic left control
    monitor._on_press(keyboard.Key.ctrl_l)

    # Release AltGr
    monitor._on_release(alt_gr_key)
    assert monitor._is_active is False
    assert len(stopped) == 2
    # Ensure synthetic Ctrl_L was cleanly purged
    assert keyboard.Key.ctrl_l not in monitor._current_keys


def test_right_alt_vk165_matching():
    started = []
    stopped = []

    monitor = PynputHotkeyMonitor(
        trigger_key="right_alt",
        action_key="ctrl_shift_space",
        on_start_recording=lambda is_action: started.append(is_action),
        on_stop_recording=lambda: stopped.append(True),
        push_to_talk=True,
    )

    vk_key = keyboard.KeyCode(vk=165)
    monitor._on_press(vk_key)
    assert monitor._is_active is True
    assert len(started) == 1

    monitor._on_release(vk_key)
    assert monitor._is_active is False
    assert len(stopped) == 1


def test_alt_space_and_ctrl_space_matching():
    started = []
    stopped = []

    monitor = PynputHotkeyMonitor(
        trigger_key="alt_space",
        action_key="ctrl_shift_space",
        on_start_recording=lambda is_action: started.append(is_action),
        on_stop_recording=lambda: stopped.append(True),
        push_to_talk=True,
    )

    # Press Alt then Space
    monitor._on_press(keyboard.Key.alt)
    assert monitor._is_active is False
    monitor._on_press(keyboard.Key.space)
    assert monitor._is_active is True
    assert len(started) == 1

    # Release Space
    monitor._on_release(keyboard.Key.space)
    assert monitor._is_active is False
    assert len(stopped) == 1
    monitor.reset_state()
