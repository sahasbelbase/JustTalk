"""Unit tests for SystemAudioDucker (computer sound muting during dictation)."""

import sys
import pytest
from just_talk.system.audio_ducker import SystemAudioDucker


def test_audio_ducker_initialization():
    """Verify ducker initializes cleanly with ducked flag False."""
    ducker = SystemAudioDucker()
    assert ducker._is_ducked is False
    assert isinstance(ducker.is_system_muted(), bool)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific NSAppleScript audio tests")
def test_audio_ducker_macos_mute_unmute_cycle():
    """Verify mute and unmute lifecycle on macOS."""
    ducker = SystemAudioDucker()
    initial_mute = ducker.is_system_muted()

    try:
        # 1. Trigger mute
        ducker.mute()
        if not initial_mute:
            assert ducker._is_ducked is True
            assert ducker.is_system_muted() is True

        # 2. Trigger unmute
        ducker.unmute()
        assert ducker._is_ducked is False
        assert ducker.is_system_muted() == initial_mute
    finally:
        # Guarantee restoration
        ducker.unmute()


def test_audio_ducker_idempotent():
    """Verify calling mute or unmute repeatedly does not fail or corrupt state."""
    ducker = SystemAudioDucker()
    try:
        ducker.mute()
        ducker.mute()  # Second call should be no-op
        ducker.unmute()
        ducker.unmute()  # Second call should be no-op
        assert ducker._is_ducked is False
    finally:
        ducker.unmute()


def test_audio_ducker_windows_flow(monkeypatch):
    """Verify Windows WASAPI and keybd_event code path execution."""
    from unittest.mock import MagicMock

    ducker = SystemAudioDucker()
    ducker._is_ducked = False
    ducker._was_already_muted = False

    # Mock Windows platform
    monkeypatch.setattr(sys, "platform", "win32")

    # Mock WASAPI set_mute and endpoint
    mock_set_mute = MagicMock(return_value=0)
    mock_endpoint = 12345
    ducker._win_set_mute = mock_set_mute
    ducker._win_endpoint_volume = mock_endpoint

    # Test Mute
    monkeypatch.setattr(ducker, "is_system_muted", lambda: False)
    ducker.mute()
    assert ducker._is_ducked is True
    mock_set_mute.assert_called_with(mock_endpoint, 1, None)

    # Test Unmute
    ducker.unmute()
    assert ducker._is_ducked is False
    mock_set_mute.assert_called_with(mock_endpoint, 0, None)

