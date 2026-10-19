"""Small native widgets for the setup flow: live-highlight reading view, mic meter, step bar,
choice cards, chips and a flow layout. All colours come from the theme tokens."""

from __future__ import annotations

import math
import time
from typing import List, Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from .theme import ThemeManager


def _tokens():
    """Tokens for the theme actually applied (the app may override the OS appearance)."""
    app = QApplication.instance()
    dark = app.palette().color(QPalette.ColorRole.Window).lightness() < 128 if app else True
    return ThemeManager.get_tokens(dark)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def _with_alpha(c: QColor, alpha: float) -> QColor:
    out = QColor(c)
    out.setAlphaF(alpha)
    return out


# ── Reading view ──────────────────────────────────────────────────────────────

class ReadingView(QWidget):
    """A sentence whose words light up as the speech engine hears them.

    Words start dim, flash the accent colour when first heard and settle to full text colour.
    After the take, misheard words get an amber underline.
    """

    PENDING, HEARD, OK, MISHEARD, MISSED = range(5)
    _SETTLE_SEC = 0.55

    def __init__(self, parent: Optional[QWidget] = None, size: int = 30):
        super().__init__(parent)
        self._words: List[str] = []
        self._state: List[int] = []
        self._lit_at: List[float] = []
        self._font = ThemeManager.font(size, QFont.Weight.DemiBold)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    # API
    def set_sentence(self, text: str) -> None:
        self._words = text.split()
        self._state = [self.PENDING] * len(self._words)
        self._lit_at = [0.0] * len(self._words)
        self.updateGeometry()
        self.update()

    def set_frontier(self, index: int) -> None:
        """Light every word up to and including index (never un-lights a word)."""
        now = time.monotonic()
        changed = False
        for i in range(min(index + 1, len(self._words))):
            if self._state[i] == self.PENDING:
                self._state[i] = self.HEARD
                self._lit_at[i] = now
                changed = True
        if changed:
            self._timer.start()
            self.update()

    def set_marks(self, statuses: List[str]) -> None:
        now = time.monotonic()
        mapping = {"ok": self.OK, "misheard": self.MISHEARD, "missed": self.MISSED}
        for i, st in enumerate(statuses[: len(self._words)]):
            if self._state[i] == self.PENDING:
                self._lit_at[i] = now
            self._state[i] = mapping.get(st, self.OK)
        self._timer.start()
        self.update()

    def reset_marks(self) -> None:
        self._state = [self.PENDING] * len(self._words)
        self.update()

    # Layout
    def _line_height(self, fm: QFontMetrics) -> int:
        return int(fm.height() * 1.38)

    def _layout(self, width: int):
        fm = QFontMetrics(self._font)
        space = fm.horizontalAdvance(" ")
        x, y = 0, 0
        lh = self._line_height(fm)
        placed = []
        for i, w in enumerate(self._words):
            ww = fm.horizontalAdvance(w)
            if x > 0 and x + ww > width:
                x, y = 0, y + lh
            placed.append((i, x, y, ww))
            x += ww + space
        height = (y + lh) if self._words else lh
        return placed, height

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._layout(max(width, 1))[1] + 8

    def sizeHint(self) -> QSize:
        return QSize(640, self.heightForWidth(640))

    def minimumSizeHint(self) -> QSize:
        return QSize(200, self.heightForWidth(self.width() or 640))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.setMinimumHeight(self.heightForWidth(self.width()))

    # Paint
    def _tick(self) -> None:
        now = time.monotonic()
        if not any(t and now - t < self._SETTLE_SEC for t in self._lit_at):
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        t = _tokens()
        text = ThemeManager.qcolor(t.text)
        accent = ThemeManager.qcolor(t.accent)
        warning = ThemeManager.qcolor(t.warning)
        pending = _with_alpha(text, 0.26)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(self._font)
        fm = QFontMetrics(self._font)
        now = time.monotonic()
        placed, _ = self._layout(self.width())
        for i, x, y, ww in placed:
            state = self._state[i]
            if state == self.PENDING:
                color = pending
            elif state in (self.MISHEARD, self.MISSED):
                color = warning if state == self.MISHEARD else _with_alpha(warning, 0.55)
            else:
                age = (now - self._lit_at[i]) / self._SETTLE_SEC if self._lit_at[i] else 1.0
                color = _mix(accent, text, age)
            p.setPen(color)
            baseline = y + fm.ascent() + 2
            p.drawText(QPoint(x, baseline), self._words[i])
            if state in (self.MISHEARD, self.MISSED):
                pen = QPen(_with_alpha(warning, 0.8), 2)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                if state == self.MISSED:
                    pen.setStyle(Qt.PenStyle.DotLine)
                p.setPen(pen)
                uy = baseline + max(4, fm.descent() // 2 + 2)
                p.drawLine(x + 1, uy, x + ww - 1, uy)
        p.end()


# ── Mic level meter ───────────────────────────────────────────────────────────

class LevelMeter(QWidget):
    """Five bars that follow the microphone level; dim when not listening."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._level = 0.0
        self._active = False
        self._phase = 0.0
        self.setFixedSize(46, 26)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            self._timer.start()
        else:
            self._timer.stop()
            self._level = 0.0
        self.update()

    def set_level(self, level: float) -> None:
        """level: 0..1, already scaled to this microphone."""
        target = min(1.0, max(0.0, level))
        self._level += (target - self._level) * (0.55 if target > self._level else 0.2)

    def _tick(self) -> None:
        self._phase += 0.33
        self.update()

    def paintEvent(self, event) -> None:
        t = _tokens()
        color = ThemeManager.qcolor(t.accent if self._active else t.text_muted)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        bars, bw, gap = 5, 4, 5
        x0 = (self.width() - (bars * bw + (bars - 1) * gap)) // 2
        shape = (0.45, 0.8, 1.0, 0.8, 0.45)
        for i in range(bars):
            wobble = 0.15 * math.sin(self._phase + i * 1.3) if self._active else 0.0
            h = 4 + (self.height() - 6) * max(0.0, min(1.0, self._level * shape[i] + wobble * self._level))
            r = QRect(x0 + i * (bw + gap), int((self.height() - h) / 2), bw, int(h))
            p.drawRoundedRect(r, 2, 2)
        p.end()


# ── Step bar ──────────────────────────────────────────────────────────────────

class StepBar(QWidget):
    def __init__(self, steps: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._steps = steps
        self._current = 0
        self._fraction = 0.0  # progress inside the current step
        self.setFixedHeight(3)

    def set_current(self, index: int, fraction: float = 0.0) -> None:
        self._current = index
        self._fraction = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, event) -> None:
        t = _tokens()
        accent = ThemeManager.qcolor(t.accent)
        track = ThemeManager.qcolor(t.border)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        gap = 6
        seg = (self.width() - gap * (self._steps - 1)) / self._steps
        for i in range(self._steps):
            x = i * (seg + gap)
            path = QPainterPath()
            path.addRoundedRect(x, 0, seg, self.height(), 1.5, 1.5)
            p.fillPath(path, track)
            fill = 1.0 if i < self._current else self._fraction if i == self._current else 0.0
            if i == self._current:
                fill = max(fill, 0.12)
            if fill > 0:
                bar = QPainterPath()
                bar.addRoundedRect(x, 0, seg * fill, self.height(), 1.5, 1.5)
                p.fillPath(bar, accent)
        p.end()


# ── Flow layout (chips wrap onto new lines) ───────────────────────────────────

class FlowLayout(QLayout):
    def __init__(self, parent: Optional[QWidget] = None, spacing: int = 8):
        super().__init__(parent)
        self._items: List[QWidgetItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x > rect.x() and x + hint.width() > rect.right() + 1:
                x, y, line_h = rect.x(), y + line_h + self._spacing, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


# ── Choice card & chips ───────────────────────────────────────────────────────

class ChoiceCard(QFrame):
    """A large selectable card with a title and an optional caption."""

    toggled = Signal(bool)

    def __init__(self, title: str, caption: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("choiceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("checked", False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("rowTitle")
        lay.addWidget(self.title)
        if caption:
            self.caption = QLabel(caption)
            self.caption.setObjectName("caption")
            lay.addWidget(self.caption)

    def isChecked(self) -> bool:
        return bool(self.property("checked"))

    def setChecked(self, on: bool) -> None:
        if self.isChecked() == on:
            return
        self.setProperty("checked", on)
        self.style().unpolish(self)
        self.style().polish(self)
        self.toggled.emit(on)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.setChecked(not self.isChecked())
        super().mouseReleaseEvent(event)


def chip(text: str, checkable: bool = True) -> QPushButton:
    b = QPushButton(text.replace("&", "&&"))
    b.setObjectName("chip")
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class SegmentedChoice(QWidget):
    """One-of-many chips, e.g. Devanagari / Roman / Depends on app."""

    changed = Signal(str)

    def __init__(self, options: List[tuple], current: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._buttons = {}
        for value, label in options:
            b = chip(label)
            b.setChecked(value == current)
            b.clicked.connect(lambda _=False, v=value: self.set_value(v, emit=True))
            lay.addWidget(b)
            self._buttons[value] = b
        lay.addStretch()

    def set_value(self, value: str, emit: bool = False) -> None:
        for v, b in self._buttons.items():
            b.setChecked(v == value)
        if emit:
            self.changed.emit(value)

    def value(self) -> str:
        return next((v for v, b in self._buttons.items() if b.isChecked()), "")


class WordsInput(QWidget):
    """Type a name or term and press Enter; each becomes a removable chip."""

    changed = Signal(list)

    def __init__(self, words: List[str], placeholder: str, limit: int = 12, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._words: List[str] = []
        self._limit = limit
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.returnPressed.connect(self._add_from_edit)
        lay.addWidget(self.edit)
        self._chips_host = QWidget()
        self._flow = FlowLayout(self._chips_host)
        lay.addWidget(self._chips_host)
        for w in words:
            self._add(w, emit=False)

    def words(self) -> List[str]:
        return list(self._words)

    def _add_from_edit(self) -> None:
        for part in self.edit.text().split(","):
            self._add(part)
        self.edit.clear()

    def _add(self, word: str, emit: bool = True) -> None:
        word = " ".join(word.split())
        if not word or word.lower() in (w.lower() for w in self._words) or len(self._words) >= self._limit:
            return
        self._words.append(word)
        b = chip(f"{word}   ×", checkable=False)
        b.setToolTip("Remove")
        b.clicked.connect(lambda _=False, w=word, btn=b: self._remove(w, btn))
        self._flow.addWidget(b)
        self._chips_host.updateGeometry()
        if emit:
            self.changed.emit(self.words())

    def _remove(self, word: str, button: QPushButton) -> None:
        self._words = [w for w in self._words if w != word]
        self._flow.removeWidget(button)
        button.deleteLater()
        self._chips_host.updateGeometry()
        self.changed.emit(self.words())


class AccuracyBar(QWidget):
    """Horizontal bar for an accuracy score with a tick at the goal."""

    def __init__(self, value: float, goal: float, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._value = value
        self._goal = goal
        self.setFixedHeight(6)

    def paintEvent(self, event) -> None:
        t = _tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        track = QPainterPath()
        track.addRoundedRect(0, 0, self.width(), self.height(), 3, 3)
        p.fillPath(track, ThemeManager.qcolor(t.border))
        fill = QPainterPath()
        color = t.success if self._value >= self._goal else t.accent
        fill.addRoundedRect(0, 0, self.width() * max(0.02, min(1.0, self._value)), self.height(), 3, 3)
        p.fillPath(fill, ThemeManager.qcolor(color))
        gx = int(self.width() * self._goal)
        p.fillRect(gx - 1, 0, 2, self.height(), ThemeManager.qcolor(t.text_secondary))
        p.end()

