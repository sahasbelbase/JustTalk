"""Unit tests for live partial transcript streaming in the HUD overlay and AppBridge."""

import pytest
from PySide6.QtWidgets import QApplication
from unittest.mock import MagicMock

# Ensure QApplication exists for widgets
app = QApplication.instance() or QApplication([])

from just_talk.app.overlay import FloatingPillOverlay
from just_talk.app.main import AppBridge


def test_overlay_partial_transcript_lifecycle():
    overlay = FloatingPillOverlay()
    assert overlay._partial_transcript == ""
    assert overlay._target_pill_width == 216.0

    # Stream first words
    overlay.update_partial_transcript("Hello world")
    assert overlay._partial_transcript == "Hello world"
    initial_target_width = overlay._target_pill_width

    # Stream longer sentence expands target width up to max bounds
    overlay.update_partial_transcript("Hello world this is a live transcription streaming test to the floating HUD")
    assert overlay._partial_transcript == "Hello world this is a live transcription streaming test to the floating HUD"
    assert overlay._target_pill_width >= initial_target_width
    assert overlay._target_pill_width <= 560.0

    # Setting idle state resets partial transcript and restores default pill width
    overlay.set_state("idle")
    assert overlay._partial_transcript == ""
    assert overlay._target_pill_width == 216.0


def test_app_bridge_partial_transcript_signal():
    bridge = AppBridge()
    received = []
    bridge.partial_transcript.connect(lambda text: received.append(text))

    bridge.partial_transcript.emit("Live streaming word 1")
    bridge.partial_transcript.emit("Live streaming word 2")

    assert received == ["Live streaming word 1", "Live streaming word 2"]
