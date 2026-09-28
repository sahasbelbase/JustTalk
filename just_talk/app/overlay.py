"""Redesigned floating pill overlay with native backdrop blur, waveform animations, and morphing transitions."""

from __future__ import annotations

import math
import sys
import time
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QTimer,
    Qt,
    Property,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .theme import ThemeManager


class FloatingPillOverlay(QWidget):
    """
    State-of-the-art non-intrusive floating indicator pill.
    Always on top, click-through, non-activating, renders native backdrop blur,
    morphing geometry, and live RMS audio waveform.
    """

    STATE_IDLE = 0
    STATE_LISTENING = 1
    STATE_PROCESSING = 2
    STATE_INSERTED = 3
    STATE_INSERTED_OFFLINE = 4
    STATE_COPIED = 5
    STATE_ERROR = 6

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._state = self.STATE_IDLE
        self._is_action_mode = False
        self._status_text = ""
        self._audio_level = 0.0
        self._target_audio_level = 0.0
        self._bars = [0.15] * 8  # 8 waveform bars
        self._shake_offset = 0.0
        self._press_start_time = 0.0
        self._is_dark = True
        self._reduce_motion = False

        # Morphing animation properties (width, opacity, y_offset)
        self._morph_progress = 0.0  # 0.0 (compact dot) to 1.0 (full capsule)
        self._opacity = 0.0
        self._y_offset = 0.0
        self._pill_width = 220.0
        self._pill_height = 44.0

        # Window flags: Frameless, Always on Top, Non-activating, Click-through
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Timers
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.hide_overlay)

        # Animation timer (~60 FPS while visible)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._on_animation_frame)

        self._apply_native_window_attributes()
        self.setFixedSize(260, 56)
        self._reposition()

    # Qt Properties for QPropertyAnimation
    def _get_morph(self) -> float:
        return self._morph_progress

    def _set_morph(self, val: float) -> None:
        self._morph_progress = val
        self.update()

    morphProgress = Property(float, _get_morph, _set_morph)

    def _get_fade(self) -> float:
        return self._opacity

    def _set_fade(self, val: float) -> None:
        self._opacity = val
        self.update()

    fadeOpacity = Property(float, _get_fade, _set_fade)

    def _apply_native_window_attributes(self) -> None:
        """Apply native macOS Spaces and backdrop blur where supported."""
        if sys.platform == "darwin":
            try:
                from AppKit import (
                    NSApplication,
                    NSColor,
                    NSVisualEffectMaterialHUD,
                    NSVisualEffectStateActive,
                    NSVisualEffectView,
                    NSWindow,
                    NSWindowCollectionBehaviorCanJoinAllSpaces,
                    NSWindowCollectionBehaviorFullScreenAuxiliary,
                )

                view_ptr = int(self.winId())
                # PyObjC bridging to set collectionBehavior over full-screen apps
                import objc
                ns_view = objc.objc_object(c_void_p=view_ptr)
                ns_window = ns_view.window()
                if ns_window:
                    behavior = ns_window.collectionBehavior()
                    ns_window.setCollectionBehavior_(
                        behavior
                        | NSWindowCollectionBehaviorCanJoinAllSpaces
                        | NSWindowCollectionBehaviorFullScreenAuxiliary
                    )
            except Exception:
                pass

    def _reposition(self) -> None:
        """Center horizontally at bottom of the active display with cursor."""
        from PySide6.QtGui import QCursor, QGuiApplication

        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            x = geom.x() + (geom.width() - self.width()) // 2
            y = geom.y() + geom.height() - self.height() - 48
            self.move(x, y)

    def set_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def show_listening(self, is_action_mode: bool = False) -> None:
        """Called immediately on push-to-talk key down."""
        self._auto_hide_timer.stop()
        self._press_start_time = time.time()
        self._state = self.STATE_LISTENING
        self._is_action_mode = is_action_mode
        self._status_text = "Action Mode" if is_action_mode else "Listening..."
        self._shake_offset = 0.0
        self._audio_level = 0.0
        self._target_audio_level = 0.0
        self._pill_width = 230.0 if is_action_mode else 210.0

        self._reposition()
        self.show()

        # Morph in: slide up 8px & fade in (180ms)
        self._anim = QPropertyAnimation(self, b"morphProgress")
        self._anim.setDuration(180)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

        self._fade_anim = QPropertyAnimation(self, b"fadeOpacity")
        self._fade_anim.setDuration(160)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

        self._anim_timer.start()

    def update_audio_level(self, rms: float) -> None:
        """Microphone RMS level callback."""
        if self._state == self.STATE_LISTENING:
            self._target_audio_level = min(1.0, max(0.0, rms * 18.0))

    def show_processing(self, text: str = "Cleaning...") -> None:
        self._state = self.STATE_PROCESSING
        self._status_text = text
        self.update()

    def show_inserted(self) -> None:
        """Morph to emerald success check."""
        self._state = self.STATE_INSERTED
        self._status_text = "Inserted"
        self.update()
        self._auto_hide_timer.start(1200)

    def show_inserted_offline(self) -> None:
        """Fallback status: raw Whisper transcription inserted locally."""
        self._state = self.STATE_INSERTED_OFFLINE
        self._status_text = "Inserted (offline)"
        self.update()
        self._auto_hide_timer.start(1500)

    def show_copied(self) -> None:
        """Clipboard fallback confirmation."""
        self._state = self.STATE_COPIED
        self._status_text = "Copied to clipboard"
        self.update()
        self._auto_hide_timer.start(1500)

    def show_error(self, message: str = "No speech detected") -> None:
        """Amber error with subtle horizontal shake."""
        self._state = self.STATE_ERROR
        self._status_text = message
        self._trigger_shake()
        self.update()
        self._auto_hide_timer.start(1600)

    def _trigger_shake(self) -> None:
        """Brief 2-cycle horizontal shake (~240ms)."""
        self._shake_start = time.time()

    def hide_overlay(self) -> None:
        """Smoothly collapse back to dot and hide."""
        if self._state == self.STATE_IDLE:
            return

        self._fade_anim = QPropertyAnimation(self, b"fadeOpacity")
        self._fade_anim.setDuration(180)
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_hidden)
        self._fade_anim.start()

    def _on_hidden(self) -> None:
        self._state = self.STATE_IDLE
        self._anim_timer.stop()
        self.hide()

    def _on_animation_frame(self) -> None:
        """Frame update for waveform, idle breathing, and shake."""
        if self._state == self.STATE_IDLE:
            return

        now = time.time()

        # 1. Audio level smoothing (Fast attack 40ms, slow release 180ms)
        if self._target_audio_level > self._audio_level:
            self._audio_level += (self._target_audio_level - self._audio_level) * 0.45
        else:
            self._audio_level += (self._target_audio_level - self._audio_level) * 0.12

        # 2. Update 8 Waveform Bars
        idle_breath = 0.18 + 0.08 * math.sin(now * 3.5)
        for i in range(len(self._bars)):
            phase = i * 0.45
            bar_target = max(idle_breath, self._audio_level * (0.4 + 0.6 * math.sin(now * 12.0 + phase)))
            self._bars[i] += (bar_target - self._bars[i]) * 0.35

        # 3. Shake animation for error
        if self._state == self.STATE_ERROR and hasattr(self, "_shake_start"):
            elapsed = now - self._shake_start
            if elapsed < 0.24:
                # 2-cycle sine shake
                self._shake_offset = 6.0 * math.sin(elapsed * math.pi * 16.0) * (1.0 - elapsed / 0.24)
            else:
                self._shake_offset = 0.0

        self.update()

    def paintEvent(self, event) -> None:
        """Render antialiased modern glass capsule with waveform and typography."""
        if self._state == self.STATE_IDLE and self._opacity <= 0.01:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)

        tokens = ThemeManager.get_tokens(self._is_dark)

        # Dynamic morph dimensions
        w = 44.0 + (self._pill_width - 44.0) * self._morph_progress
        h = self._pill_height
        x = (self.width() - w) / 2.0 + self._shake_offset
        y = (self.height() - h) / 2.0 + (1.0 - self._morph_progress) * 8.0

        capsule_rect = QRectF(x, y, w, h)
        radius = h / 2.0

        # Background: Translucent frosted glass
        if self._is_dark:
            bg_color = QColor(24, 25, 30, 230)
            border_color = QColor(255, 255, 255, 26)
        else:
            bg_color = QColor(255, 255, 255, 238)
            border_color = QColor(15, 23, 42, 24)

        path = QPainterPath()
        path.addRoundedRect(capsule_rect, radius, radius)
        painter.fillPath(path, bg_color)
        painter.setPen(QPen(border_color, 1.0))
        painter.drawPath(path)

        # If still morphing in as a dot, only draw center dot
        if self._morph_progress < 0.35:
            dot_color = QColor(tokens.listening)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot_color)
            painter.drawEllipse(capsule_rect.center(), 5.0, 5.0)
            return

        # Status Dot / Icon Placement
        dot_cx = x + 24.0
        dot_cy = y + h / 2.0

        if self._state == self.STATE_LISTENING:
            dot_color = QColor(tokens.action if self._is_action_mode else tokens.listening)
            base_r = 4.5
            meter_r = base_r + (self._audio_level * 4.0)

            # Outer glow
            painter.setPen(Qt.PenStyle.NoPen)
            glow_color = QColor(dot_color.red(), dot_color.green(), dot_color.blue(), 50)
            painter.setBrush(glow_color)
            painter.drawEllipse(QPoint(int(dot_cx), int(dot_cy)), int(meter_r + 3), int(meter_r + 3))

            # Core dot
            painter.setBrush(dot_color)
            painter.drawEllipse(QPoint(int(dot_cx), int(dot_cy)), int(meter_r), int(meter_r))

            # Draw Waveform Bars (7 bars centered between label and right margin)
            bars_start_x = x + w - 46.0
            bar_w = 2.4
            bar_gap = 2.2
            for idx, bar_h_ratio in enumerate(self._bars[:7]):
                bh = max(4.0, bar_h_ratio * 16.0)
                bx = bars_start_x + idx * (bar_w + bar_gap)
                by = dot_cy - bh / 2.0
                bar_rect = QRectF(bx, by, bar_w, bh)
                painter.setBrush(QColor(dot_color.red(), dot_color.green(), dot_color.blue(), 190))
                painter.drawRoundedRect(bar_rect, 1.2, 1.2)

        elif self._state == self.STATE_PROCESSING:
            # Cyan pulsing dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens.processing))
            painter.drawEllipse(QPoint(int(dot_cx), int(dot_cy)), 5, 5)

        elif self._state == self.STATE_INSERTED:
            # Emerald checkmark dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens.success))
            painter.drawEllipse(QPoint(int(dot_cx), int(dot_cy)), 5, 5)

        elif self._state == self.STATE_INSERTED_OFFLINE:
            # Subtle amber/muted green for offline fallback
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens.warning))
            painter.drawEllipse(QPoint(int(dot_cx), int(dot_cy)), 5, 5)

        elif self._state == self.STATE_COPIED:
            # Blue clipboard dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens.clipboard))
            painter.drawEllipse(QPoint(int(dot_cx), int(dot_cy)), 5, 5)

        elif self._state == self.STATE_ERROR:
            # Amber warning dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens.warning))
            painter.drawEllipse(QPoint(int(dot_cx), int(dot_cy)), 5, 5)

        # Label Text
        painter.setPen(QColor(tokens.text))
        painter.setFont(ThemeManager.font(13, weight=QFont.Weight.Medium, family="ui"))
        label_rect = QRectF(x + 40.0, y, w - 85.0, h)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._status_text)
