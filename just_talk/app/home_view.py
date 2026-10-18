"""Home View with Dashboard and Contribution Graph."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import List, Dict

from PySide6.QtCore import Qt, QRect, QPoint, QSize
from PySide6.QtGui import QFont, QPainter, QColor, QBrush, QPen, QPainterPath
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QToolTip
)

from ..config import AppConfig
from ..database.history import HistoryDatabase
from .theme import DARK_TOKENS, LIGHT_TOKENS, ThemeManager


class ContributionGraphWidget(QWidget):
    """A GitHub-style contribution graph for words spoken per day."""

    def __init__(self, db: HistoryDatabase, config: AppConfig, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self.setMouseTracking(True)
        self.setMinimumHeight(160)
        
        self.cell_size = 12
        self.cell_margin = 4
        self.weeks_to_show = 52
        
        # Color palettes matching Stitch Design System
        self.light_colors = ["#EBEDF0", "#A7F3D0", "#34D399", "#10B981", "#047857"]
        self.dark_colors = ["#1E2229", "#064E3B", "#006D32", "#10B981", "#4EDEA3"]
        
        self.daily_data: Dict[str, dict] = {}
        self.max_words = 1
        self.quartiles = [0, 0, 0, 0]
        
        self.refresh()

    def refresh(self):
        stats = self.db.get_daily_stats(365)
        self.daily_data = {d["date"]: d for d in stats}
        
        if stats:
            words = sorted([d["word_count"] for d in stats if d["word_count"] > 0])
            if words:
                self.max_words = words[-1]
                # Calculate quartiles for color thresholds
                self.quartiles = [
                    words[max(0, int(len(words) * 0.25) - 1)],
                    words[max(0, int(len(words) * 0.50) - 1)],
                    words[max(0, int(len(words) * 0.75) - 1)],
                    words[-1]
                ]
            else:
                self.quartiles = [100, 500, 1000, 2000]
        else:
            self.quartiles = [100, 500, 1000, 2000]
            
        self.update()

    def _grid(self):
        """First day (a Sunday) and number of week columns that fit, ending with this week."""
        step = self.cell_size + self.cell_margin
        weeks = max(1, min(self.weeks_to_show, (self.width() - 38) // step))
        today = datetime.now().date()
        this_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
        return this_sunday - timedelta(weeks=weeks - 1), weeks

    def _get_color_level(self, words: int) -> int:
        if words == 0: return 0
        if words <= self.quartiles[0]: return 1
        if words <= self.quartiles[1]: return 2
        if words <= self.quartiles[2]: return 3
        return 4

    def paintEvent(self, event):
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            is_dark = ThemeManager.is_dark(self.config.appearance)
            colors = self.dark_colors if is_dark else self.light_colors
            text_color = ThemeManager.qcolor(DARK_TOKENS.text_secondary if is_dark else LIGHT_TOKENS.text_secondary)

            painter.setPen(text_color)
            painter.setFont(ThemeManager.get_mono_font(10, weight=QFont.Weight.Medium))
            
            today = datetime.now().date()
            start_date, weeks = self._grid()

            x_offset = 38
            y_offset = 20
            
            # Draw day labels (Mon, Wed, Fri)
            painter.drawText(4, y_offset + (1 * (self.cell_size + self.cell_margin)) + 10, "Mon")
            painter.drawText(4, y_offset + (3 * (self.cell_size + self.cell_margin)) + 10, "Wed")
            painter.drawText(4, y_offset + (5 * (self.cell_size + self.cell_margin)) + 10, "Fri")

            # Draw cells
            curr_date = start_date
            last_month = -1
            
            painter.setPen(Qt.PenStyle.NoPen)
            
            for week in range(weeks):
                for day in range(7):
                    if curr_date > today:
                        break
                        
                    ds = curr_date.strftime("%Y-%m-%d")
                    
                    # Draw month labels
                    if day == 0 and curr_date.month != last_month and curr_date.day <= 14:
                        painter.setPen(text_color)
                        painter.drawText(x_offset + (week * (self.cell_size + self.cell_margin)), 12, curr_date.strftime("%b"))
                        painter.setPen(Qt.PenStyle.NoPen)
                        last_month = curr_date.month

                    words = self.daily_data.get(ds, {}).get("word_count", 0)
                    lvl = self.get_level(words)
                    
                    rect = QRect(
                        x_offset + (week * (self.cell_size + self.cell_margin)),
                        y_offset + (day * (self.cell_size + self.cell_margin)),
                        self.cell_size,
                        self.cell_size
                    )
                    
                    path = QPainterPath()
                    path.addRoundedRect(rect, 2.5, 2.5)
                    painter.fillPath(path, QColor(colors[lvl]))
                    
                    curr_date += timedelta(days=1)
        except Exception:
            pass
        finally:
            painter.end()
                
    def get_level(self, words: int) -> int:
        return self._get_color_level(words)
        
    def mouseMoveEvent(self, event):
        x = event.pos().x() - 38
        y = event.pos().y() - 20
        
        if x < 0 or y < 0:
            QToolTip.hideText()
            return
            
        week = x // (self.cell_size + self.cell_margin)
        day = y // (self.cell_size + self.cell_margin)
        start_date, weeks = self._grid()

        if week >= 0 and week < weeks and day >= 0 and day < 7:
            today = datetime.now().date()
            target = start_date + timedelta(weeks=week, days=day)
            if target <= today:
                ds = target.strftime("%Y-%m-%d")
                d = self.daily_data.get(ds)
                if d:
                    w = d['word_count']
                    m = d['duration_min']
                    app = d['top_app']
                    tip = f"{target.strftime('%b %d, %Y')}\n{w} words ({m} min)\nTop app: {app}"
                else:
                    tip = f"{target.strftime('%b %d, %Y')}\nNo dictations"
                
                QToolTip.showText(event.globalPos(), tip, self)
                return
                
        QToolTip.hideText()


class DashboardWidget(QWidget):
    """The Home Dashboard containing greeting, bento stats and contribution graph."""
    
    def __init__(self, db: HistoryDatabase, config: AppConfig, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self._build_ui()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        
        # 1. Hero Greeting Row
        hdr = QHBoxLayout()
        hdr_left = QVBoxLayout()
        hdr_left.setSpacing(2)

        self.greeting = QLabel(self._get_time_greeting())
        self.greeting.setFont(ThemeManager.get_display_font(26, weight=QFont.Weight.Bold))
        hdr_left.addWidget(self.greeting)

        subtitle = QLabel("Speak in any app. Just Talk types it for you.")
        subtitle.setObjectName("mutedLabel")
        subtitle.setFont(ThemeManager.get_ui_font(12))
        hdr_left.addWidget(subtitle)
        hdr.addLayout(hdr_left)
        hdr.addStretch()
        
        # Typical wait after you stop talking, from your recent dictations
        self.latency_pill = QLabel("")
        self.latency_pill.setObjectName("statusPill")
        self.latency_pill.setFont(ThemeManager.get_ui_font(11, weight=QFont.Weight.Medium))
        hdr.addWidget(self.latency_pill)

        # Shortcut hint
        self.shortcut_hint = QLabel("")
        self.shortcut_hint.setObjectName("mutedLabel")
        self.shortcut_hint.setFont(ThemeManager.get_ui_font(12))
        hdr.addWidget(self.shortcut_hint)
        layout.addLayout(hdr)
        
        # 2. 4-Metric Bento Grid Row
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(14)

        swpm = self.config.speaking_speed_wpm
        twpm = self.config.typing_speed_wpm
        c1, self._words_val, self._words_sub = self._bento_stat_card("Words Spoken", "", "")
        c2, self._saved_val, self._saved_sub = self._bento_stat_card("Time Saved", "", "", tooltip=f"Based on {swpm} wpm speaking vs {twpm} wpm typing")
        c3, self._streak_val, self._streak_sub = self._bento_stat_card("Current Streak", "", "")
        c4, self._today_val, self._today_sub = self._bento_stat_card("Spoken Today", "", "")
        self._update_stats()

        cards_layout.addWidget(c1)
        cards_layout.addWidget(c2)
        cards_layout.addWidget(c3)
        cards_layout.addWidget(c4)

        layout.addLayout(cards_layout)
        
        # 3. Dictation Activity (Contribution Matrix Heatmap)
        graph_card = QFrame()
        graph_card.setObjectName("card")
        gl = QVBoxLayout(graph_card)
        gl.setContentsMargins(18, 16, 18, 16)
        gl.setSpacing(12)
        
        ghdr = QHBoxLayout()
        gtitle = QLabel("Dictation Activity")
        gtitle.setFont(ThemeManager.get_ui_font(14, weight=QFont.Weight.DemiBold))
        ghdr.addWidget(gtitle)
        ghdr.addStretch()

        # Legend: Less ... More
        legend_layout = QHBoxLayout()
        legend_layout.setSpacing(4)
        less_lbl = QLabel("Less")
        less_lbl.setObjectName("mutedLabel")
        less_lbl.setFont(ThemeManager.get_mono_font(10))
        legend_layout.addWidget(less_lbl)

        is_dark = ThemeManager.is_dark(self.config.appearance)
        pal = ["#1E2229", "#064E3B", "#006D32", "#10B981", "#4EDEA3"] if is_dark else ["#EBEDF0", "#A7F3D0", "#34D399", "#10B981", "#047857"]
        for c in pal:
            dot = QLabel()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(f"background-color: {c}; border-radius: 2px;")
            legend_layout.addWidget(dot)

        more_lbl = QLabel("More")
        more_lbl.setObjectName("mutedLabel")
        more_lbl.setFont(ThemeManager.get_mono_font(10))
        legend_layout.addWidget(more_lbl)
        ghdr.addLayout(legend_layout)

        gl.addLayout(ghdr)
        
        self.graph = ContributionGraphWidget(self.db, self.config)
        gl.addWidget(self.graph)
        
        layout.addWidget(graph_card)

    def _update_stats(self) -> None:
        stats = self.db.get_stats_summary()
        tw = stats["total_words"]
        swpm = self.config.speaking_speed_wpm
        twpm = self.config.typing_speed_wpm

        # Formula: (words/typing) - (words/speaking) = time saved in minutes
        mins_saved = (tw / twpm) - (tw / swpm) if twpm > 0 and swpm > 0 else 0
        hrs = int(mins_saved // 60)
        mins = int(mins_saved % 60)

        self._words_val.setText(f"{tw:,}")
        self._saved_val.setText(f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m")
        streak = stats["streak_days"]
        self._streak_val.setText(f"{streak} day" if streak == 1 else f"{streak} days")
        self._today_val.setText(f"{stats['today_words']:,}")

        daily = {d["date"]: d for d in self.db.get_daily_stats(7)}
        week_start = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
        week_words = sum(d["word_count"] for k, d in daily.items() if k >= week_start)
        self._words_sub.setText(f"{week_words:,} this week")
        self._saved_sub.setText(f"{swpm / twpm:.1f}x faster" if twpm > 0 and swpm > 0 else "")
        self._streak_sub.setText("in a row" if streak else "Dictate to start")
        today_min = daily.get(datetime.now().strftime("%Y-%m-%d"), {}).get("duration_min", 0)
        self._today_sub.setText(f"{today_min:.0f} min speaking" if today_min >= 1 else "")

        waits = sorted(i.duration_ms for i in self.db.get_recent(limit=30) if i.duration_ms > 0)
        if waits:
            self.latency_pill.setText(f"● Typical wait {waits[len(waits) // 2] / 1000:.1f} s")
            self.latency_pill.setToolTip("Median time from when you stop talking to when your text appears (last 30 dictations)")
        self.latency_pill.setVisible(bool(waits))

    def _bento_stat_card(self, label: str, value: str, subtext: str, tooltip: str = "") -> tuple[QFrame, QLabel, QLabel]:
        f = QFrame()
        f.setObjectName("bentoCard")
        l = QVBoxLayout(f)
        l.setContentsMargins(16, 14, 16, 14)
        l.setSpacing(6)
        
        lbl = QLabel(label)
        lbl.setObjectName("mutedLabel")
        lbl.setFont(ThemeManager.get_ui_font(12, weight=QFont.Weight.Medium))
        if tooltip:
            lbl.setToolTip(tooltip)
            
        val = QLabel(value)
        val.setObjectName("statMetric")
        val.setFont(ThemeManager.get_display_font(24, weight=QFont.Weight.Bold))

        sub = QLabel(subtext)
        sub.setObjectName("statTrend")
        sub.setFont(ThemeManager.get_mono_font(10, weight=QFont.Weight.Medium))
        
        l.addWidget(lbl)
        l.addWidget(val)
        l.addWidget(sub)
        return f, val, sub

    def _get_time_greeting(self) -> str:
        h = datetime.now().hour
        if h < 12: return "Good morning."
        if h < 17: return "Good afternoon."
        return "Good evening."
        
    def refresh(self):
        self.greeting.setText(self._get_time_greeting())
        self.graph.refresh()
        self._update_stats()
