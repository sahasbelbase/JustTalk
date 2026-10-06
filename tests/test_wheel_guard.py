"""Scrolling over an unfocused dropdown must scroll the page, not change the value."""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QComboBox, QScrollArea, QVBoxLayout, QWidget

from just_talk.app.wheel_guard import install_wheel_guard


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    install_wheel_guard(a)
    return a


def _wheel(widget, delta=-120):
    pos = QPointF(widget.rect().center())
    ev = QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, delta),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)


def test_wheel_over_unfocused_combo_scrolls_page(app):
    area = QScrollArea()
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.addSpacing(400)
    combo = QComboBox()
    combo.addItems(["a", "b", "c"])
    lay.addWidget(combo)
    lay.addSpacing(2000)
    area.setWidget(inner)
    area.resize(300, 300)
    area.show()
    app.processEvents()
    # Opening a window may auto-focus the first dropdown; that must not hijack the wheel.
    combo.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
    app.processEvents()

    _wheel(combo)
    app.processEvents()
    assert combo.currentIndex() == 0
    assert area.verticalScrollBar().value() > 0


def test_wheel_over_tab_focused_combo_still_changes_value(app):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit

    page = QWidget()
    lay = QVBoxLayout(page)
    edit = QLineEdit()
    combo = QComboBox()
    combo.addItems(["a", "b", "c"])
    lay.addWidget(edit)
    lay.addWidget(combo)
    page.show()
    page.activateWindow()
    edit.setFocus()
    app.processEvents()
    QTest.keyClick(edit, Qt.Key.Key_Tab)  # keyboard user tabs into the dropdown
    app.processEvents()
    if not combo.hasFocus():
        pytest.skip("window focus unavailable in this environment")
    _wheel(combo)
    assert combo.currentIndex() == 1
