"""Stop the mouse wheel from changing dropdowns/spin boxes while scrolling a page."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QSlider,
    QWidget,
)

_GUARDED = (QComboBox, QAbstractSpinBox, QSlider)
_WHEEL_OK = "_justtalk_wheel_ok"

# Keyboard focus the user gave on purpose. Focus a window hands out on its own when it
# opens (ActiveWindow/Other) must not make the wheel change values while scrolling.
_KEYBOARD_FOCUS = (
    Qt.FocusReason.TabFocusReason,
    Qt.FocusReason.BacktabFocusReason,
    Qt.FocusReason.ShortcutFocusReason,
)


def _guarded_widget(obj: QObject) -> Optional[QWidget]:
    """Return the dropdown/spin box/slider ``obj`` belongs to (e.g. an editable combo's line edit)."""
    w = obj if isinstance(obj, QWidget) else None
    for _ in range(3):
        if w is None:
            return None
        if isinstance(w, _GUARDED):
            return w
        w = w.parentWidget()
    return None


class WheelGuard(QObject):
    """
    App-wide event filter. A wheel event over a closed dropdown, spin box or slider
    scrolls the surrounding page instead of silently changing the value. Values are
    changed by clicking and picking from the list (whose popup still scrolls normally),
    or with the wheel after tabbing into the control with the keyboard.

    Plain focus isn't trusted: windows auto-focus their first control when they open,
    which is exactly when users start scrolling.
    """

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        etype = event.type()
        if etype in (QEvent.Type.FocusIn, QEvent.Type.FocusOut) and isinstance(obj, _GUARDED):
            obj.setProperty(_WHEEL_OK, etype == QEvent.Type.FocusIn and event.reason() in _KEYBOARD_FOCUS)
            return False
        if etype != QEvent.Type.Wheel:
            return False

        widget = _guarded_widget(obj)
        if widget is None or (widget.hasFocus() and widget.property(_WHEEL_OK)):
            return False

        # Don't let the wheel grab focus either (QComboBox defaults to WheelFocus).
        if widget.focusPolicy() == Qt.FocusPolicy.WheelFocus:
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        parent = widget.parentWidget()
        while parent is not None and not isinstance(parent, QAbstractScrollArea):
            parent = parent.parentWidget()
        if parent is not None:
            QCoreApplication.sendEvent(parent.viewport(), event)
        return True


_guard: Optional[WheelGuard] = None


def install_wheel_guard(app: QApplication) -> None:
    global _guard
    if _guard is None:
        _guard = WheelGuard(app)
        app.installEventFilter(_guard)
