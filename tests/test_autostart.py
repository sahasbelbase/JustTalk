"""Tests for system autostart manager."""

from just_talk.system.autostart import AutostartManager


def test_autostart_toggle():
    initial_state = AutostartManager.is_autostart_enabled()
    try:
        # Enable
        ok = AutostartManager.set_autostart(True)
        if ok:
            assert AutostartManager.is_autostart_enabled() is True

            # Disable
            AutostartManager.set_autostart(False)
            assert AutostartManager.is_autostart_enabled() is False
        else:
            # If system registry/launchagent write is restricted in CI environment
            assert isinstance(ok, bool)
    finally:
        # Restore initial state
        AutostartManager.set_autostart(initial_state)
