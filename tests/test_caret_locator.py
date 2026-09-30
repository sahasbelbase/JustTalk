"""Unit tests for dynamic CaretLocator."""

import sys
from PySide6.QtCore import QPoint
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

from just_talk.system.caret_locator import CaretLocator


def test_caret_locator_fallback():
    """Verify that CaretLocator always returns valid integer screen coordinates."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    x, y = CaretLocator.get_target_position(pill_width=216, pill_height=48)
    assert isinstance(x, int)
    assert isinstance(y, int)
    assert x >= 0
    assert y >= 0


def test_caret_locator_bounds_clamping():
    """Verify that coordinates are clamped within the screen geometry."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    x, y = CaretLocator.get_target_position(pill_width=280, pill_height=68)
    screens = app.screens()
    assert len(screens) > 0

    # Ensure coords fall within at least one valid screen's coordinate envelope
    contained = any(
        s.geometry().contains(QPoint(x + 140, y + 34)) or s.availableGeometry().contains(QPoint(x, y))
        for s in screens
    )
    assert contained


def test_caret_locator_locate_target():
    """Verify locate_target returns 3 items: x, y, and boolean has_text_target."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    x, y, has_text = CaretLocator.locate_target(pill_width=216, pill_height=48)
    assert isinstance(x, int)
    assert isinstance(y, int)
    assert isinstance(has_text, bool)
    assert CaretLocator.has_active_text_target() == has_text
