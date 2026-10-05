"""Typeless-replica floating pill overlay with audio-reactive waveform visualizer, cancel & confirm controls."""

from __future__ import annotations

import math
import sys
import time
from typing import Callable, Optional

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

from .theme import ThemeManager


class FloatingPillOverlay(QWidget):
    """
    Exact, pixel-perfect replica of the Typeless / Dynamic Island floating voice pill.
    Features:
    - Pitch-black frosted glass capsule with hairline border
    - Left cancel [ ✕ ] button (dark gray circle with crisp white cross)
    - Center live audio equalizer (9 symmetrical white rounded waveform bars)
    - Right confirm [ ✓ ] button (crisp white circle with black checkmark)
    - High-sensitivity real-time audio reactivity
    - Non-activating, stays on top, smooth morph and fade transitions
    """

    STATE_IDLE = 0
    STATE_LISTENING = 1
    STATE_PROCESSING = 2
    STATE_INSERTED = 3
    STATE_INSERTED_OFFLINE = 4
    STATE_COPIED = 5
    STATE_ERROR = 6

    # Symmetrical harmonic weights for the 9 equalizer bars
    # Center (bar 4) is tallest, smoothly tapering symmetrically left and right
    BAR_WEIGHTS = [0.30, 0.45, 0.65, 0.85, 1.0, 0.85, 0.65, 0.45, 0.30]

    cancel_requested = Signal()
    confirm_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._state = self.STATE_IDLE
        self._is_action_mode = False
        self._status_text = ""
        self._audio_level = 0.0
        self._target_audio_level = 0.0
        self._bars = [0.2] * 9
        self._shake_offset = 0.0
        self._press_start_time = 0.0
        self._is_dark = True
        self._spinner_angle = 0.0
        self._hovered_btn: Optional[str] = None

        # Animation properties
        self._morph_progress = 0.0
        self._opacity = 0.0
        self._live_transcript = ""
        self._pill_width = 216.0
        self._target_pill_width = 216.0
        self._pill_height = 48.0

        # Window flags: Tool type creates a Cocoa QNSPanel on macOS.
        # Paired with hidesOnDeactivate=False and NSWindowStyleMaskNonactivatingPanel,
        # this matches Floaty, Raycast, and Wispr Flow to float across all apps and spaces without stealing focus.
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        # Timers
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.hide_overlay)

        # 60 FPS animation timer
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._on_animation_frame)

        self._apply_native_window_attributes()
        self.setFixedSize(580, 68)
        self._reposition()

    # -------------------------------------------------------------------------
    # Properties for Qt Animations
    # -------------------------------------------------------------------------

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
        """Allow overlay to appear over full-screen apps, Brave, Teams, and across all macOS spaces without stealing focus."""
        if sys.platform == "darwin":
            try:
                import ctypes
                import objc
                from AppKit import (
                    NSWindowCollectionBehaviorCanJoinAllSpaces,
                    NSWindowCollectionBehaviorFullScreenAuxiliary,
                    NSWindowCollectionBehaviorIgnoresCycle,
                    NSStatusWindowLevel,
                    NSWindowStyleMaskNonactivatingPanel,
                )

                view_ptr = int(self.winId())
                c_void_p = ctypes.c_void_p(view_ptr)
                ns_view = objc.objc_object(c_void_p=c_void_p)
                ns_panel = ns_view.window()
                if ns_panel:
                    # Critical for floating over other apps: prevent Cocoa from auto-hiding NSPanel on deactivate
                    ns_panel.setHidesOnDeactivate_(False)
                    ns_panel.setFloatingPanel_(True)
                    # QNSPanel doesn't support setCanBecomeKeyWindow_; use setBecomesKeyOnlyIfNeeded_ instead
                    ns_panel.setBecomesKeyOnlyIfNeeded_(True)

                    # Non-activating panel style mask prevents stealing focus from active app (Brave, Teams, etc.)
                    mask = ns_panel.styleMask()
                    ns_panel.setStyleMask_(mask | NSWindowStyleMaskNonactivatingPanel)

                    # Collection behavior: follow across all spaces, Mission Control, and full-screen windows
                    behavior = (
                        NSWindowCollectionBehaviorCanJoinAllSpaces
                        | NSWindowCollectionBehaviorFullScreenAuxiliary
                        | NSWindowCollectionBehaviorIgnoresCycle
                    )
                    ns_panel.setCollectionBehavior_(behavior)

                    # Status window level (25) floats reliably above all normal windows and full-screen spaces
                    ns_panel.setLevel_(NSStatusWindowLevel)
                    ns_panel.orderWindow_relativeTo_(1, 0)
                    ns_panel.orderFrontRegardless()
            except Exception as e:
                print(f"[Overlay] Native window config error: {e}", file=sys.stderr)
        elif sys.platform == "win32":
            try:
                import ctypes

                hwnd = int(self.winId())
                user32 = ctypes.windll.user32
                GWL_EXSTYLE = -20
                WS_EX_TOPMOST = 0x00000008
                WS_EX_TOOLWINDOW = 0x00000080
                WS_EX_NOACTIVATE = 0x08000000
                HWND_TOPMOST = -1
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOACTIVATE = 0x0010
                SWP_SHOWWINDOW = 0x0040

                style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
                user32.SetWindowPos(
                    hwnd,
                    HWND_TOPMOST,
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
            except Exception as e:
                print(f"[Overlay] Windows native window config error: {e}", file=sys.stderr)

    def _bring_to_front_windows(self) -> None:
        """Force window to the very front on Windows without stealing keyboard focus."""
        if sys.platform == "win32":
            try:
                import ctypes

                hwnd = int(self.winId())
                HWND_TOPMOST = -1
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOACTIVATE = 0x0010
                SWP_SHOWWINDOW = 0x0040
                ctypes.windll.user32.SetWindowPos(
                    hwnd,
                    HWND_TOPMOST,
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
            except Exception:
                pass

    def _bring_to_front_mac(self) -> None:
        """Force window to the very front of all applications and spaces without stealing keyboard focus."""
        if sys.platform == "darwin":
            try:
                import ctypes
                import objc
                from AppKit import (
                    NSWindowCollectionBehaviorCanJoinAllSpaces,
                    NSWindowCollectionBehaviorFullScreenAuxiliary,
                    NSWindowCollectionBehaviorIgnoresCycle,
                    NSStatusWindowLevel,
                    NSWindowStyleMaskNonactivatingPanel,
                )

                view_ptr = int(self.winId())
                c_void_p = ctypes.c_void_p(view_ptr)
                ns_view = objc.objc_object(c_void_p=c_void_p)
                ns_panel = ns_view.window()
                if ns_panel:
                    ns_panel.setHidesOnDeactivate_(False)
                    ns_panel.setFloatingPanel_(True)
                    ns_panel.setBecomesKeyOnlyIfNeeded_(True)
                    mask = ns_panel.styleMask()
                    ns_panel.setStyleMask_(mask | NSWindowStyleMaskNonactivatingPanel)
                    behavior = (
                        NSWindowCollectionBehaviorCanJoinAllSpaces
                        | NSWindowCollectionBehaviorFullScreenAuxiliary
                        | NSWindowCollectionBehaviorIgnoresCycle
                    )
                    ns_panel.setCollectionBehavior_(behavior)
                    ns_panel.setLevel_(NSStatusWindowLevel)
                    ns_panel.orderWindow_relativeTo_(1, 0)
                    ns_panel.orderFrontRegardless()
            except Exception:
                pass

    def _bring_to_front(self) -> None:
        """Force window to the front across platforms without stealing focus."""
        if sys.platform == "darwin":
            self._bring_to_front_mac()
        elif sys.platform == "win32":
            self._bring_to_front_windows()

    def _reposition(self) -> None:
        """Position pill near active text caret, focused input, or active window, like Wispr Flow and Typeless."""
        try:
            from just_talk.system.caret_locator import CaretLocator

            x, y, has_text = CaretLocator.locate_target(
                pill_width=self.width(),
                pill_height=self.height(),
                offset_y=8,
            )
            self.move(x, y)
        except Exception:
            from PySide6.QtGui import QCursor, QGuiApplication

            cursor_pos = QCursor.pos()
            screen = QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
            if screen:
                geom = screen.availableGeometry()
                x = geom.x() + (geom.width() - self.width()) // 2
                y = geom.y() + geom.height() - self.height() - 36
                self.move(x, y)

    # -------------------------------------------------------------------------
    # State Transitions
    # -------------------------------------------------------------------------

    def show_listening(self, is_action_mode: bool = False) -> None:
        """Called the instant the Fn shortcut key is pressed down."""
        self._auto_hide_timer.stop()
        self._press_start_time = time.time()
        self._state = self.STATE_LISTENING
        self._is_action_mode = is_action_mode
        self._status_text = "Action Mode" if is_action_mode else "Listening"
        self._live_transcript = ""
        self._shake_offset = 0.0
        self._audio_level = 0.0
        self._target_audio_level = 0.0
        self._bars = [0.2] * 9
        self._pill_width = 224.0 if is_action_mode else 208.0
        self._target_pill_width = self._pill_width

        self._reposition()
        if not self.isVisible():
            self.show()
        self._apply_native_window_attributes()
        self._bring_to_front()

        self._opacity = 1.0
        self._morph_progress = 1.0

        # Snappy physical scale pop-in animation
        self._anim = QPropertyAnimation(self, b"morphProgress")
        self._anim.setDuration(120)
        self._anim.setStartValue(0.88)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._anim.start()

        self._anim_timer.start()
        self.update()

    @property
    def _partial_transcript(self) -> str:
        return self._live_transcript

    def set_state(self, state: int | str) -> None:
        """Set overlay state."""
        if state in ("idle", self.STATE_IDLE):
            self._state = self.STATE_IDLE
            self._live_transcript = ""
            self._pill_width = 216.0
            self._target_pill_width = 216.0
            self.hide()

    def update_partial_transcript(self, text: str) -> None:
        """Update live streaming partial transcript displayed inside the floating HUD."""
        clean_text = text.strip()
        if not clean_text:
            return
        self._live_transcript = clean_text
        font = ThemeManager.get_ui_font(13, weight=QFont.Weight.Medium)
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(clean_text)
        # Ensure room for cancel button, mini wave, text, and confirm button
        desired_w = min(540.0, max(224.0 if self._is_action_mode else 208.0, text_w + 130.0))
        self._target_pill_width = desired_w
        self.update()

    def set_action_mode(self, is_action_mode: bool) -> None:
        """Dynamically elevate or lower the listening session to/from Action Mode while speaking."""
        if self._state == self.STATE_LISTENING:
            self._is_action_mode = is_action_mode
            self._status_text = "Action Mode" if is_action_mode else "Listening"
            if not self._live_transcript:
                self._pill_width = 224.0 if is_action_mode else 208.0
                self._target_pill_width = self._pill_width
            self.update()

    def update_audio_level(self, rms: float) -> None:
        """Live microphone volume callback (RMS 0.0 - 1.0) with non-linear boost."""
        if self._state == self.STATE_LISTENING:
            # Non-linear perceptual scaling gives instant snappy responsiveness even on soft speech
            boosted = math.sqrt(max(0.0, rms - 0.001)) * 6.5
            self._target_audio_level = min(1.0, max(0.0, boosted))

    def show_processing(self, text: str = "Cleaning...") -> None:
        """Morph from waveform into spinning thinking shimmer."""
        self._state = self.STATE_PROCESSING
        self._status_text = text
        self._live_transcript = ""
        self._pill_width = 175.0
        self._target_pill_width = 175.0
        self._opacity = 1.0
        if not self.isVisible():
            self.show()
        self._apply_native_window_attributes()
        self._bring_to_front()
        if not self._anim_timer.isActive():
            self._anim_timer.start()
        self.update()

    def show_inserted(self) -> None:
        """Emerald checkmark confirmation."""
        self._state = self.STATE_INSERTED
        self._status_text = "Inserted"
        self._live_transcript = ""
        self._pill_width = 150.0
        self._target_pill_width = 150.0
        self._opacity = 1.0
        if not self.isVisible():
            self.show()
        self._bring_to_front()
        self.update()
        self._auto_hide_timer.start(1100)

    def show_inserted_offline(self) -> None:
        """Offline fallback confirmation."""
        self._state = self.STATE_INSERTED_OFFLINE
        self._status_text = "Inserted (offline)"
        self._live_transcript = ""
        self._pill_width = 190.0
        self._target_pill_width = 190.0
        self._opacity = 1.0
        if not self.isVisible():
            self.show()
        self._bring_to_front()
        self.update()
        self._auto_hide_timer.start(1400)

    def show_copied(self) -> None:
        """Clipboard confirmation badge."""
        self._state = self.STATE_COPIED
        self._status_text = "Copied to Clipboard"
        self._live_transcript = ""
        self._pill_width = 180.0
        self._target_pill_width = 180.0
        self._opacity = 1.0
        if not self.isVisible():
            self.show()
        self._bring_to_front()
        self.update()
        self._auto_hide_timer.start(1400)

    def show_error(self, message: str = "No speech detected") -> None:
        """Subtle horizontal shake with error message."""
        self._state = self.STATE_ERROR
        self._status_text = message
        self._live_transcript = ""
        self._pill_width = 200.0
        self._target_pill_width = 200.0
        self._shake_start = time.time()
        self._opacity = 1.0
        if not self.isVisible():
            self.show()
        self._bring_to_front()
        self.update()
        self._auto_hide_timer.start(1500)

    def hide_overlay(self) -> None:
        """Collapse and fade out."""
        if self._state == self.STATE_IDLE:
            return

        if hasattr(self, "_fade_anim") and self._fade_anim is not None:
            try:
                self._fade_anim.stop()
            except Exception:
                pass

        self._fade_anim = QPropertyAnimation(self, b"fadeOpacity")
        self._fade_anim.setDuration(160)
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_hidden)
        self._fade_anim.start()

    def _on_hidden(self) -> None:
        self._state = self.STATE_IDLE
        self._anim_timer.stop()
        self.hide()

    # -------------------------------------------------------------------------
    # Animation Frame (60 FPS)
    # -------------------------------------------------------------------------

    def _on_animation_frame(self) -> None:
        if self._state == self.STATE_IDLE:
            return

        now = time.time()

        # Smoothly interpolate pill width towards target width for liquid morphing
        if abs(self._pill_width - self._target_pill_width) > 0.5:
            self._pill_width += (self._target_pill_width - self._pill_width) * 0.28
        else:
            self._pill_width = self._target_pill_width

        # 1. Audio smoothing (instant attack ~25ms, smooth organic release)
        if self._target_audio_level > self._audio_level:
            self._audio_level += (self._target_audio_level - self._audio_level) * 0.65
        else:
            self._audio_level += (self._target_audio_level - self._audio_level) * 0.18

        # 2. Update 9 Waveform Bars (Fluid undulating harmonic ripple like Wispr Flow / Typeless / Floaty)
        for i, weight in enumerate(self.BAR_WEIGHTS):
            dist_from_center = abs(i - 4)  # 0 to 4
            # Dynamic harmonic phase wave for vocal articulation
            phase = now * 11.0 - dist_from_center * 0.48
            harmonic = 0.40 + 0.60 * (0.5 + 0.5 * math.sin(phase))
            dynamic_speech = self._audio_level * harmonic * weight * 1.5

            # Ambient undulating breath ripple so the user always sees the float animation is active
            ambient_wave = (0.20 + 0.10 * math.sin(now * 5.0 - dist_from_center * 0.55)) * weight
            target_h = max(ambient_wave, dynamic_speech)
            target_h = min(1.0, max(0.12, target_h))

            if target_h > self._bars[i]:
                self._bars[i] += (target_h - self._bars[i]) * 0.55
            else:
                self._bars[i] += (target_h - self._bars[i]) * 0.28

        # 3. Spinner angle for processing
        if self._state == self.STATE_PROCESSING:
            self._spinner_angle = (self._spinner_angle + 10.0) % 360.0

        # 4. Error shake
        if self._state == self.STATE_ERROR and hasattr(self, "_shake_start"):
            elapsed = now - self._shake_start
            if elapsed < 0.22:
                self._shake_offset = 6.0 * math.sin(elapsed * math.pi * 16.0) * (1.0 - elapsed / 0.22)
            else:
                self._shake_offset = 0.0

        self.update()

    # -------------------------------------------------------------------------
    # Mouse Interaction (Hover States & Click Cancel / Confirm)
    # -------------------------------------------------------------------------

    def mouseMoveEvent(self, event) -> None:
        # Handle dragging if active
        if hasattr(self, "_drag_start_offset") and self._drag_start_offset is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                new_pos = event.globalPosition().toPoint() - self._drag_start_offset
                self.move(new_pos)
                return

        if self._state != self.STATE_LISTENING:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        pos = event.position()
        w = self._pill_width
        h = self._pill_height
        x = (self.width() - w) / 2.0
        y = (self.height() - h) / 2.0

        cancel_center = QPointF(x + 24.0, y + h / 2.0)
        confirm_center = QPointF(x + w - 24.0, y + h / 2.0)

        dist_cancel = math.hypot(pos.x() - cancel_center.x(), pos.y() - cancel_center.y())
        dist_confirm = math.hypot(pos.x() - confirm_center.x(), pos.y() - confirm_center.y())

        prev_hover = self._hovered_btn
        if dist_cancel <= 16.0:
            self._hovered_btn = "cancel"
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif dist_confirm <= 16.0:
            self._hovered_btn = "confirm"
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self._hovered_btn = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

        if self._hovered_btn != prev_hover:
            self.update()

    def leaveEvent(self, event) -> None:
        if self._hovered_btn is not None:
            self._hovered_btn = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()

    def mousePressEvent(self, event) -> None:
        if self._state != self.STATE_LISTENING:
            return

        pos = event.position()
        w = self._pill_width
        h = self._pill_height
        x = (self.width() - w) / 2.0

        # Left button area: Cancel
        if pos.x() < x + 40.0:
            self.show_error("Cancelled")
            self.cancel_requested.emit()
        # Right button area: Confirm / Finish
        elif pos.x() > x + w - 40.0:
            self.confirm_requested.emit()
        else:
            # Click on pill body: allow dragging
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_start_offset = event.globalPosition().toPoint() - self.pos()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_start_offset = None


    # -------------------------------------------------------------------------
    # Painting (Pixel-Perfect Typeless Replica)
    # -------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        if self._state == self.STATE_IDLE and self._opacity <= 0.01:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        now = time.time()

        # Dynamic pill dimensions
        w = self._pill_width * self._morph_progress
        h = self._pill_height
        x = (self.width() - w) / 2.0 + self._shake_offset
        y = (self.height() - h) / 2.0

        capsule_rect = QRectF(x, y, w, h)
        radius = h / 2.0

        # 1. Outer Soft Glow / Shadow
        glow_path = QPainterPath()
        if self._state == self.STATE_LISTENING and self._is_action_mode:
            glow_path.addRoundedRect(capsule_rect.adjusted(-3, -3, 3, 3), radius + 3, radius + 3)
            painter.fillPath(glow_path, QColor(255, 159, 10, 75))
            border_pen = QPen(QColor(255, 159, 10, 200), 1.4)
        else:
            glow_path.addRoundedRect(capsule_rect.adjusted(-2, -2, 2, 2), radius + 2, radius + 2)
            painter.fillPath(glow_path, QColor(0, 0, 0, 45))
            border_pen = QPen(QColor(255, 255, 255, 34), 1.0)

        # 2. Main Capsule: Deep Obsidian Black (#0B0C0E)
        capsule_path = QPainterPath()
        capsule_path.addRoundedRect(capsule_rect, radius, radius)
        painter.fillPath(capsule_path, QColor(11, 12, 14, 245))

        # 3. Hairline Border (subtle clean outline)
        painter.setPen(border_pen)
        painter.drawPath(capsule_path)

        # ---------------------------------------------------------------------
        # State: LISTENING (Exact replica of user's screenshot)
        # ---------------------------------------------------------------------
        if self._state == self.STATE_LISTENING:
            btn_radius = 15.0

            # A. Left Cancel Button: Dark Gray Circle with White [ ✕ ]
            cancel_center = QPointF(x + 24.0, y + h / 2.0)
            painter.setPen(Qt.PenStyle.NoPen)
            if self._hovered_btn == "cancel":
                painter.setBrush(QColor(76, 78, 86, 255))
            else:
                painter.setBrush(QColor(54, 55, 60, 240))
            painter.drawEllipse(cancel_center, btn_radius, btn_radius)

            # Draw "✕" with anti-aliasing
            cross_pen = QPen(QColor(255, 255, 255, 245), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(cross_pen)
            cross_r = 4.8
            cx, cy = cancel_center.x(), cancel_center.y()
            painter.drawLine(QPointF(cx - cross_r, cy - cross_r), QPointF(cx + cross_r, cy + cross_r))
            painter.drawLine(QPointF(cx - cross_r, cy + cross_r), QPointF(cx + cross_r, cy - cross_r))

            # B. Right Confirm Button: Solid White Circle with Black [ ✓ ]
            confirm_center = QPointF(x + w - 24.0, y + h / 2.0)
            painter.setPen(Qt.PenStyle.NoPen)
            if self._hovered_btn == "confirm":
                painter.setBrush(QColor(255, 179, 64, 255) if self._is_action_mode else QColor(230, 232, 238, 255))
            else:
                painter.setBrush(QColor(255, 159, 10, 255) if self._is_action_mode else QColor(255, 255, 255, 255))
            painter.drawEllipse(confirm_center, btn_radius, btn_radius)

            # Draw "✓" in bold black
            check_pen = QPen(QColor(11, 12, 14, 255), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(check_pen)
            check_path = QPainterPath()
            check_path.moveTo(confirm_center.x() - 4.5, confirm_center.y() + 0.2)
            check_path.lineTo(confirm_center.x() - 1.2, confirm_center.y() + 4.2)
            check_path.lineTo(confirm_center.x() + 5.5, confirm_center.y() - 3.8)
            painter.drawPath(check_path)

            # C. Center Sound Waveform Visualizer or Live Partial Transcript
            if not self._live_transcript:
                num_bars = len(self._bars)
                bar_w = 3.2
                bar_gap = 3.8
                total_waveform_w = num_bars * bar_w + (num_bars - 1) * bar_gap
                waveform_start_x = x + (w - total_waveform_w) / 2.0
                center_y = y + h / 2.0

                painter.setPen(Qt.PenStyle.NoPen)
                if self._is_action_mode:
                    painter.setBrush(QColor(255, 179, 64, 255))
                else:
                    painter.setBrush(QColor(255, 255, 255, 255))

                for idx, bar_ratio in enumerate(self._bars):
                    # Center bar max height: 28px, min: 5px
                    bar_h = max(5.0, bar_ratio * 28.0)
                    bx = waveform_start_x + idx * (bar_w + bar_gap)
                    by = center_y - bar_h / 2.0
                    bar_rect = QRectF(bx, by, bar_w, bar_h)
                    painter.drawRoundedRect(bar_rect, 1.6, 1.6)

                if self._is_action_mode:
                    # Draw subtle "⚡ ACTION" tag
                    painter.setPen(QColor(255, 179, 64, 220))
                    font = painter.font()
                    font.setPixelSize(9)
                    font.setBold(True)
                    painter.setFont(font)
                    painter.drawText(
                        QRectF(x, y + 2, w, 11),
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                        "⚡ ACTION MODE",
                    )
            else:
                # Live streaming words displayed in real-time as user speaks!
                # 1. Mini 3-bar audio wave indicator right beside the cancel button
                mini_start_x = x + 44.0
                center_y = y + h / 2.0
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 179, 64, 230) if self._is_action_mode else QColor(255, 255, 255, 220))
                for m_idx in range(3):
                    m_ratio = self._bars[3 + m_idx]
                    m_h = max(4.0, m_ratio * 16.0)
                    m_bx = mini_start_x + m_idx * 5.0
                    m_by = center_y - m_h / 2.0
                    painter.drawRoundedRect(QRectF(m_bx, m_by, 2.4, m_h), 1.2, 1.2)

                # 2. Live text layout
                text_start_x = mini_start_x + 20.0
                avail_text_w = max(40.0, (x + w - 46.0) - text_start_x)
                font = ThemeManager.get_ui_font(13, weight=QFont.Weight.Medium)
                painter.setFont(font)
                fm = QFontMetrics(font)

                # Elide on left so latest spoken words are always prominently visible
                elided_str = fm.elidedText(self._live_transcript, Qt.TextElideMode.ElideLeft, int(avail_text_w - 12.0))

                # Text color
                painter.setPen(QColor(245, 245, 247, 255))
                text_rect = QRectF(text_start_x, y, avail_text_w, h)
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_str)

                # 3. Pulsing live indicator bar at end of visible text
                drawn_w = min(avail_text_w, fm.horizontalAdvance(elided_str))
                cursor_x = text_start_x + drawn_w + 3.0
                if cursor_x < x + w - 44.0:
                    cursor_opacity = int(140 + 115 * (0.5 + 0.5 * math.sin(now * 7.0)))
                    painter.setPen(QColor(255, 179, 64, cursor_opacity) if self._is_action_mode else QColor(255, 255, 255, cursor_opacity))
                    painter.drawLine(QPointF(cursor_x, center_y - 6.0), QPointF(cursor_x, center_y + 6.0))

        # ---------------------------------------------------------------------
        # State: PROCESSING (Spinning Shimmer + Text)
        # ---------------------------------------------------------------------
        elif self._state == self.STATE_PROCESSING:
            # Spinner on left
            spin_center = QPointF(x + 24.0, y + h / 2.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            spinner_pen = QPen(QColor(255, 255, 255, 60), 2.2)
            painter.setPen(spinner_pen)
            painter.drawArc(QRectF(spin_center.x() - 7, spin_center.y() - 7, 14, 14), 0, 360 * 16)

            active_pen = QPen(QColor(90, 200, 250, 255), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(active_pen)
            painter.drawArc(QRectF(spin_center.x() - 7, spin_center.y() - 7, 14, 14), int(self._spinner_angle * 16), 110 * 16)

            # Text
            painter.setPen(QColor(245, 245, 247))
            painter.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.Medium))
            text_rect = QRectF(x + 44.0, y, w - 54.0, h)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._status_text)

        # ---------------------------------------------------------------------
        # State: INSERTED / INSERTED_OFFLINE / COPIED
        # ---------------------------------------------------------------------
        elif self._state in (self.STATE_INSERTED, self.STATE_INSERTED_OFFLINE, self.STATE_COPIED):
            btn_radius = 12.0
            icon_center = QPointF(x + 22.0, y + h / 2.0)

            if self._state == self.STATE_INSERTED:
                # Emerald green check
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(48, 209, 88))
                painter.drawEllipse(icon_center, btn_radius, btn_radius)

                check_pen = QPen(QColor(255, 255, 255), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                painter.setPen(check_pen)
                p = QPainterPath()
                p.moveTo(icon_center.x() - 4.0, icon_center.y() + 0.2)
                p.lineTo(icon_center.x() - 1.0, icon_center.y() + 3.6)
                p.lineTo(icon_center.x() + 4.5, icon_center.y() - 3.2)
                painter.drawPath(p)

            elif self._state == self.STATE_INSERTED_OFFLINE:
                # Amber offline check
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 159, 10))
                painter.drawEllipse(icon_center, btn_radius, btn_radius)

                check_pen = QPen(QColor(255, 255, 255), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                painter.setPen(check_pen)
                p = QPainterPath()
                p.moveTo(icon_center.x() - 4.0, icon_center.y() + 0.2)
                p.lineTo(icon_center.x() - 1.0, icon_center.y() + 3.6)
                p.lineTo(icon_center.x() + 4.5, icon_center.y() - 3.2)
                painter.drawPath(p)

            else:
                # Blue clipboard
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(10, 132, 255))
                painter.drawEllipse(icon_center, btn_radius, btn_radius)

            # Label
            painter.setPen(QColor(245, 245, 247))
            painter.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.Medium))
            text_rect = QRectF(x + 42.0, y, w - 50.0, h)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._status_text)

        # ---------------------------------------------------------------------
        # State: ERROR (Shake)
        # ---------------------------------------------------------------------
        elif self._state == self.STATE_ERROR:
            warn_center = QPointF(x + 22.0, y + h / 2.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 69, 58))
            painter.drawEllipse(warn_center, 11.0, 11.0)

            # Exclamation mark
            painter.setPen(QPen(QColor(255, 255, 255), 2.0))
            painter.drawLine(QPointF(warn_center.x(), warn_center.y() - 4.0), QPointF(warn_center.x(), warn_center.y() + 1.0))
            painter.drawPoint(QPointF(warn_center.x(), warn_center.y() + 4.5))

            painter.setPen(QColor(255, 69, 58))
            painter.setFont(ThemeManager.get_ui_font(12, weight=QFont.Weight.Medium))
            text_rect = QRectF(x + 40.0, y, w - 48.0, h)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._status_text)
