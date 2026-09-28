"""Subtle native floating pill overlay for recording and processing feedback."""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class FloatingPillOverlay(QWidget):
    """
    Subtle, non-intrusive floating indicator pill.
    Always on top, click-through, does not steal focus from active text fields.
    """

    STATE_IDLE = 0
    STATE_LISTENING = 1
    STATE_PROCESSING = 2
    STATE_INSERTED = 3
    STATE_COPIED = 4
    STATE_ERROR = 5

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._state = self.STATE_IDLE
        self._is_action_mode = False
        self._audio_level = 0.0
        self._status_text = ""

        # Window flags: Frameless, Always on Top, Non-activating
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SubWindow
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.hide_overlay)

        self.setFixedSize(220, 44)
        self._reposition()

    def _reposition(self) -> None:
        """Position pill at bottom-center of the active screen."""
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            x = geom.x() + (geom.width() - self.width()) // 2
            y = geom.y() + geom.height() - self.height() - 48
            self.move(x, y)

    def show_listening(self, is_action_mode: bool = False) -> None:
        """Display listening indicator."""
        self._auto_hide_timer.stop()
        self._state = self.STATE_LISTENING
        self._is_action_mode = is_action_mode
        self._audio_level = 0.0
        self._status_text = "Action Mode" if is_action_mode else "Listening..."
        self._reposition()
        self.show()
        self.update()

    def update_audio_level(self, rms: float) -> None:
        """Update audio level (0.0 to 1.0) for visual feedback."""
        if self._state == self.STATE_LISTENING:
            # Smooth audio visual meter
            normalized = min(1.0, rms * 15.0)
            self._audio_level = 0.7 * self._audio_level + 0.3 * normalized
            self.update()

    def show_processing(self, text: str = "Cleaning...") -> None:
        """Display processing indicator."""
        self._auto_hide_timer.stop()
        self._state = self.STATE_PROCESSING
        self._status_text = text
        self.update()

    def show_inserted(self) -> None:
        """Display successful insertion indicator and auto-hide."""
        self._state = self.STATE_INSERTED
        self._status_text = "Inserted"
        self.update()
        self._auto_hide_timer.start(1200)

    def show_copied(self) -> None:
        """Display clipboard fallback indicator and auto-hide."""
        self._state = self.STATE_COPIED
        self._status_text = "Copied to clipboard"
        self.update()
        self._auto_hide_timer.start(1600)

    def show_error(self, message: str = "No speech detected") -> None:
        """Display error indicator and auto-hide."""
        self._state = self.STATE_ERROR
        self._status_text = message
        self.update()
        self._auto_hide_timer.start(1600)

    def hide_overlay(self) -> None:
        """Hide the overlay completely."""
        self._state = self.STATE_IDLE
        self.hide()

    def paintEvent(self, event) -> None:
        """Custom paint event for crisp dark glass pill."""
        if self._state == self.STATE_IDLE:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = rect.height() / 2.0

        # Background: Translucent dark glass
        bg_color = QColor(24, 24, 28, 235)
        border_color = QColor(255, 255, 255, 30)

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, bg_color)
        painter.setPen(QPen(border_color, 1.2))
        painter.drawPath(path)

        # Draw State Indicator Dot / Icon
        dot_center_x = 26
        dot_center_y = self.height() // 2

        if self._state == self.STATE_LISTENING:
            if self._is_action_mode:
                dot_color = QColor(168, 85, 247)  # Purple
            else:
                dot_color = QColor(239, 68, 68)   # Red
            base_radius = 5.0
            meter_radius = base_radius + (self._audio_level * 5.0)

            # Outer glow
            painter.setPen(Qt.PenStyle.NoPen)
            glow_color = QColor(dot_color.red(), dot_color.green(), dot_color.blue(), 60)
            painter.setBrush(glow_color)
            painter.drawEllipse(QPoint(dot_center_x, dot_center_y), meter_radius + 3, meter_radius + 3)

            # Inner dot
            painter.setBrush(dot_color)
            painter.drawEllipse(QPoint(dot_center_x, dot_center_y), meter_radius, meter_radius)

        elif self._state == self.STATE_PROCESSING:
            # Cyan pulsing dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(6, 182, 212))
            painter.drawEllipse(QPoint(dot_center_x, dot_center_y), 5, 5)

        elif self._state == self.STATE_INSERTED:
            # Emerald green check
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(16, 185, 129))
            painter.drawEllipse(QPoint(dot_center_x, dot_center_y), 5, 5)

        elif self._state == self.STATE_COPIED:
            # Blue clipboard dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(59, 130, 246))
            painter.drawEllipse(QPoint(dot_center_x, dot_center_y), 5, 5)

        elif self._state == self.STATE_ERROR:
            # Amber warning dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(245, 158, 11))
            painter.drawEllipse(QPoint(dot_center_x, dot_center_y), 5, 5)

        # Draw Label Text
        painter.setPen(QColor(240, 240, 245))
        font = QFont("SF Pro Display" if sys.platform == "darwin" else "Segoe UI", 11)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)

        text_rect = QRect(44, 0, self.width() - 54, self.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._status_text)
