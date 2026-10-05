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
        
        # Color palettes
        self.light_colors = ["#EBEDF0", "#9BE9A8", "#40C463", "#30A14E", "#216E39"]
        self.dark_colors = ["#161B22", "#0E4429", "#006D32", "#26A641", "#39D353"]
        
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
            
            is_dark = self.config.appearance == "dark"
            colors = self.dark_colors if is_dark else self.light_colors
            text_color = QColor(DARK_TOKENS.text_muted if is_dark else LIGHT_TOKENS.text_muted)
            
            painter.setPen(text_color)
            painter.setFont(ThemeManager.get_ui_font(10))
            
            today = datetime.now().date()
            # Find the most recent Sunday to align weeks
            days_since_sunday = (today.weekday() + 1) % 7
            end_date = today + timedelta(days=6 - days_since_sunday)
            start_date = end_date - timedelta(weeks=self.weeks_to_show)
            
            x_offset = 40
            y_offset = 20
            
            # Draw day labels (Mon, Wed, Fri)
            painter.drawText(5, y_offset + (1 * (self.cell_size + self.cell_margin)) + 10, "Mon")
            painter.drawText(5, y_offset + (3 * (self.cell_size + self.cell_margin)) + 10, "Wed")
            painter.drawText(5, y_offset + (5 * (self.cell_size + self.cell_margin)) + 10, "Fri")

            # Draw cells
            curr_date = start_date
            last_month = -1
            
            painter.setPen(Qt.PenStyle.NoPen)
            
            for week in range(self.weeks_to_show):
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
                    path.addRoundedRect(rect, 2, 2)
                    painter.fillPath(path, QColor(colors[lvl]))
                    
                    curr_date += timedelta(days=1)
        except Exception:
            pass
        finally:
            painter.end()
                
    def get_level(self, words: int) -> int:
        return self._get_color_level(words)
        
    def mouseMoveEvent(self, event):
        x = event.pos().x() - 40
        y = event.pos().y() - 20
        
        if x < 0 or y < 0:
            QToolTip.hideText()
            return
            
        week = x // (self.cell_size + self.cell_margin)
        day = y // (self.cell_size + self.cell_margin)
        
        if week >= 0 and week < self.weeks_to_show and day >= 0 and day < 7:
            today = datetime.now().date()
            days_since_sunday = (today.weekday() + 1) % 7
            end_date = today + timedelta(days=6 - days_since_sunday)
            start_date = end_date - timedelta(weeks=self.weeks_to_show)
            
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
    """The Home Dashboard containing stats and contribution graph."""
    
    def __init__(self, db: HistoryDatabase, config: AppConfig, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self._build_ui()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        
        # Greeting
        hdr = QHBoxLayout()
        greeting = QLabel(self._get_time_greeting())
        greeting.setFont(ThemeManager.get_display_font(28, weight=QFont.Weight.Bold))
        hdr.addWidget(greeting)
        hdr.addStretch()
        
        shortcut_hint = QLabel("Hold Option to dictate")
        shortcut_hint.setObjectName("mutedLabel")
        shortcut_hint.setFont(ThemeManager.get_ui_font(13))
        hdr.addWidget(shortcut_hint)
        layout.addLayout(hdr)
        
        # Stat cards
        stats = self.db.get_stats_summary()
        tw = stats["total_words"]
        swpm = self.config.speaking_speed_wpm
        twpm = self.config.typing_speed_wpm
        
        # Formula: (words/typing) - (words/speaking) = time saved in minutes
        mins_saved = (tw / twpm) - (tw / swpm) if twpm > 0 and swpm > 0 else 0
        hrs = int(mins_saved // 60)
        mins = int(mins_saved % 60)
        ts_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"
        
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(16)
        
        c1 = self._stat_card("Words Spoken", f"{tw:,}")
        c2 = self._stat_card("Time Saved", ts_str, tooltip=f"Based on {swpm} wpm speaking vs {twpm} wpm typing")
        c3 = self._stat_card("Current Streak", f"{stats['streak_days']} days")
        c4 = self._stat_card("Spoken Today", f"{stats['today_words']:,}")
        
        cards_layout.addWidget(c1)
        cards_layout.addWidget(c2)
        cards_layout.addWidget(c3)
        cards_layout.addWidget(c4)
        
        layout.addLayout(cards_layout)
        
        # Contribution Graph
        graph_card = QFrame()
        graph_card.setObjectName("card")
        gl = QVBoxLayout(graph_card)
        gl.setContentsMargins(20, 20, 20, 20)
        gl.setSpacing(16)
        
        ghdr = QHBoxLayout()
        gtitle = QLabel("Dictation Activity")
        gtitle.setFont(ThemeManager.get_ui_font(14, weight=QFont.Weight.DemiBold))
        ghdr.addWidget(gtitle)
        ghdr.addStretch()
        gl.addLayout(ghdr)
        
        self.graph = ContributionGraphWidget(self.db, self.config)
        gl.addWidget(self.graph)
        
        layout.addWidget(graph_card)

    def _stat_card(self, label: str, value: str, tooltip: str = "") -> QFrame:
        f = QFrame()
        f.setObjectName("surfaceCard")
        l = QVBoxLayout(f)
        l.setContentsMargins(20, 16, 20, 16)
        
        lbl = QLabel(label)
        lbl.setObjectName("mutedLabel")
        lbl.setFont(ThemeManager.get_ui_font(12, weight=QFont.Weight.Medium))
        if tooltip:
            lbl.setToolTip(tooltip)
            
        val = QLabel(value)
        val.setFont(ThemeManager.get_display_font(26, weight=QFont.Weight.Bold))
        
        l.addWidget(lbl)
        l.addWidget(val)
        return f

    def _get_time_greeting(self) -> str:
        h = datetime.now().hour
        if h < 12: return "Good morning."
        if h < 17: return "Good afternoon."
        return "Good evening."
        
    def refresh(self):
        self.graph.refresh()
        # Updating the stat cards dynamically would require keeping references to the labels,
        # but rebuilding or restarting the app is usually fine for a dashboard,
        # or we can fully refresh by clearing the layout.
