"""Tests for system autostart manager."""

from just_talk.system.autostart import AutostartManager


def test_autostart_toggle():
    initial_state = AutostartManager.is_autostart_enabled()
    try:
        # Enable
        AutostartManager.set_autostart(True)
        assert AutostartManager.is_autostart_enabled() is True

        # Disable
        AutostartManager.set_autostart(False)
        assert AutostartManager.is_autostart_enabled() is False
    finally:
        # Restore initial state
        AutostartManager.set_autostart(initial_state)
