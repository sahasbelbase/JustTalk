"""History View with filtering, context chips, and day grouping."""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QIcon, QPainter, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QComboBox, QTextEdit, QGridLayout
)

from ..config import AppConfig
from ..database.history import HistoryDatabase, HistoryItem
from .theme import ThemeManager
from . import icons


# Same colors as ConventionsView
_CTX_COLORS = {
    "sql":        ("#A85E00", "rgba(255,149,0,.12)"),
    "python":     ("#1A7D35", "rgba(52,199,89,.12)"),
    "javascript": ("#7A6A00", "rgba(255,214,10,.15)"),
    "typescript": ("#005DC4", "rgba(0,122,255,.10)"),
    "java":       ("#8B3A00", "rgba(255,100,0,.12)"),
    "csharp":     ("#5B2EA6", "rgba(150,80,230,.12)"),
    "go":         ("#005F80", "rgba(0,150,200,.12)"),
    "rust":       ("#8B2500", "rgba(200,60,0,.12)"),
    "php":        ("#4A3F8A", "rgba(120,100,220,.12)"),
    "text":       ("#48484A", "rgba(60,60,67,.08)"),
}
_CTX_COLORS_DARK = {
    "sql":        ("#FFAA40", "rgba(255,159,10,.14)"),
    "python":     ("#30D158", "rgba(48,209,88,.12)"),
    "javascript": ("#FFD60A", "rgba(255,214,10,.14)"),
    "typescript": ("#6C8EEF", "rgba(108,142,239,.14)"),
    "java":       ("#FF9F0A", "rgba(255,159,10,.14)"),
    "csharp":     ("#BF5AF2", "rgba(191,90,242,.14)"),
    "go":         ("#64D2FF", "rgba(100,210,255,.14)"),
    "rust":       ("#FF6B40", "rgba(255,107,64,.14)"),
    "php":        ("#A78BFA", "rgba(167,139,250,.14)"),
    "text":       ("rgba(255,255,255,.55)", "rgba(255,255,255,.07)"),
}

class ContextChip(QLabel):
    """A small colored tag for the context."""
    def __init__(self, context: str, is_dark: bool = False):
        super().__init__(context.capitalize() if context != "text" else "Prose")
        self.setFont(ThemeManager.get_ui_font(11, weight=QFont.Weight.Medium))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setContentsMargins(6, 2, 6, 2)
        
        colors = _CTX_COLORS_DARK if is_dark else _CTX_COLORS
        fg, bg = colors.get(context, colors["text"])
        
        self.setStyleSheet(f"""
            QLabel {{
                color: {fg};
                background-color: {bg};
                border-radius: 4px;
            }}
        """)


def _change_label(item: HistoryItem) -> str:
    """"Translated" or "AI Refined" when the typed text differs from what was heard by more than
    punctuation and capitals; "" otherwise."""
    if item.action == "translate":
        return "Translated"
    words = lambda t: re.sub(r"[^\w\s]", "", t.lower()).split()  # noqa: E731
    return "AI Refined" if words(item.raw_transcription) != words(item.processed_text) else ""


class HistoryEntryWidget(QFrame):
    """A single history entry, expandable to show raw vs formatted side-by-side diff."""
    
    deleted = Signal(str)
    
    def __init__(self, item: HistoryItem, config: AppConfig, parent=None):
        super().__init__(parent)
        self.item = item
        self.config = config
        self.is_expanded = False
        
        self.setObjectName("historyCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(8)
        
        # Header row (always visible)
        self.hdr_frame = QWidget()
        self.hdr_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        hdr = QHBoxLayout(self.hdr_frame)
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(10)
        
        # Expand/collapse chevron
        self.chevron = QLabel()
        self.chevron.setPixmap(icons.pixmap("chevron-right", icons.ICON_MUTED, 14))
        hdr.addWidget(self.chevron)

        time_lbl = QLabel(item.formatted_time)
        time_lbl.setObjectName("mutedLabel")
        time_lbl.setFont(ThemeManager.get_mono_font(11))
        hdr.addWidget(time_lbl)
        
        # App Badge
        app_lbl = QLabel(item.application)
        app_lbl.setObjectName("badge")
        app_lbl.setFont(ThemeManager.get_ui_font(11, weight=QFont.Weight.Medium))
        hdr.addWidget(app_lbl)
        
        # Context Chip
        chip = ContextChip(item.context, is_dark=ThemeManager.is_dark(config.appearance))
        hdr.addWidget(chip)

        # Only when the AI actually changed the words (not just a final period)
        change = _change_label(item)
        if change:
            ai_pill = QLabel(f"✦ {change}")
            ai_pill.setObjectName("accentPill")
            ai_pill.setFont(ThemeManager.get_mono_font(10, weight=QFont.Weight.Bold))
            hdr.addWidget(ai_pill)
        
        hdr.addStretch()
        
        word_lbl = QLabel(f"{item.word_count} words")
        word_lbl.setObjectName("mutedLabel")
        word_lbl.setFont(ThemeManager.get_mono_font(11))
        hdr.addWidget(word_lbl)
        
        # Copy button
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setObjectName("secondaryBtn")
        self.copy_btn.setIcon(icons.icon("copy", size=12))
        self.copy_btn.setStyleSheet("padding: 3px 8px; font-size: 11px;")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.clicked.connect(self._copy_formatted)
        hdr.addWidget(self.copy_btn)
        
        # Delete button
        del_btn = QPushButton()
        del_btn.setObjectName("deleteBtn")
        del_btn.setIcon(icons.icon("close", size=13))
        del_btn.setToolTip("Delete Entry")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.clicked.connect(lambda: self.deleted.emit(self.item.id))
        hdr.addWidget(del_btn)
        
        self._layout.addWidget(self.hdr_frame)
        
        # Collapsed Preview
        self.preview_lbl = QLabel(item.processed_text.replace("\n", " ")[:160] + ("…" if len(item.processed_text) > 160 else ""))
        self.preview_lbl.setFont(ThemeManager.get_ui_font(13))
        self.preview_lbl.setWordWrap(True)
        self.preview_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._layout.addWidget(self.preview_lbl)
        
        # Expanded Side-by-Side Diff Comparison Panel
        self.detail_area = QWidget()
        detail_layout = QHBoxLayout(self.detail_area)
        detail_layout.setContentsMargins(0, 6, 0, 0)
        detail_layout.setSpacing(12)
        
        # LEFT: Raw Speech Transcript Panel
        raw_panel = QFrame()
        raw_panel.setObjectName("diffRawPanel")
        raw_layout = QVBoxLayout(raw_panel)
        raw_layout.setContentsMargins(12, 10, 12, 10)
        raw_layout.setSpacing(6)

        raw_hdr_row = QHBoxLayout()
        raw_hdr = QLabel("What you said")
        raw_hdr.setFont(ThemeManager.get_ui_font(12, weight=QFont.Weight.DemiBold))
        raw_hdr_row.addWidget(raw_hdr)
        raw_hdr_row.addStretch()
        raw_layout.addLayout(raw_hdr_row)
        
        raw_text = QTextEdit()
        raw_text.setReadOnly(True)
        raw_text.setPlainText(item.raw_transcription)
        raw_text.setFont(ThemeManager.get_mono_font(12))
        raw_text.setFixedHeight(95)
        raw_layout.addWidget(raw_text)


        detail_layout.addWidget(raw_panel, 1)
        
        # RIGHT: Formatted Output Panel
        fmt_panel = QFrame()
        fmt_panel.setObjectName("diffFormattedPanel")
        fmt_layout = QVBoxLayout(fmt_panel)
        fmt_layout.setContentsMargins(12, 10, 12, 10)
        fmt_layout.setSpacing(6)

        fmt_hdr_row = QHBoxLayout()
        fmt_hdr = QLabel("What was typed")
        fmt_hdr.setFont(ThemeManager.get_ui_font(12, weight=QFont.Weight.DemiBold))
        fmt_hdr_row.addWidget(fmt_hdr)
        fmt_hdr_row.addStretch()
        fmt_layout.addLayout(fmt_hdr_row)
        
        fmt_text = QTextEdit()
        fmt_text.setReadOnly(True)
        fmt_text.setPlainText(item.processed_text)
        fmt_text.setFont(ThemeManager.get_mono_font(12) if item.context != "text" else ThemeManager.get_ui_font(13))
        fmt_text.setFixedHeight(95)
        fmt_layout.addWidget(fmt_text)

        fmt_footer_row = QHBoxLayout()
        fmt_footer_row.addStretch()
        
        re_copy_btn = QPushButton("Copy Text")
        re_copy_btn.setObjectName("primaryBtn")
        re_copy_btn.setIcon(icons.icon("copy", active_color="#FFFFFF", size=11))
        re_copy_btn.setStyleSheet("padding: 2px 10px; font-size: 11px;")
        re_copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        re_copy_btn.clicked.connect(self._copy_formatted)
        fmt_footer_row.addWidget(re_copy_btn)

        fmt_layout.addLayout(fmt_footer_row)
        detail_layout.addWidget(fmt_panel, 1)
        
        self.detail_area.hide()
        self._layout.addWidget(self.detail_area)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_expand()
        super().mousePressEvent(event)

    def _toggle_expand(self):
        self.is_expanded = not self.is_expanded
        self.detail_area.setVisible(self.is_expanded)
        self.preview_lbl.setVisible(not self.is_expanded)
        self.chevron.setPixmap(
            icons.pixmap("chevron-down" if self.is_expanded else "chevron-right", icons.ICON_MUTED, 14)
        )
        
    def _copy_formatted(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.item.processed_text)
        self.copy_btn.setText("Copied!")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy"))


class HistoryView(QWidget):
    """The main History screen with interactive diff cards and filters."""

    def __init__(self, db: HistoryDatabase, config: AppConfig, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        
        self._build_ui()
        self.refresh()
        
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 28, 36, 28)
        root.setSpacing(16)
        
        # 1. Header Row
        hdr = QHBoxLayout()
        title = QLabel("Dictation History")
        title.setFont(ThemeManager.get_display_font(26, weight=QFont.Weight.Bold))
        hdr.addWidget(title)
        hdr.addStretch()
        
        clear_btn = QPushButton("Clear History")
        clear_btn.setObjectName("dangerBtn")
        clear_btn.setIcon(icons.icon("delete", color="#EF4444", active_color="#EF4444", size=14))
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_history)
        hdr.addWidget(clear_btn)
        root.addLayout(hdr)
        
        # 2. Filter Toolbar
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(10)
        
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search transcriptions…")
        self.search_box.setFixedWidth(260)
        self.search_box.textChanged.connect(self.refresh)
        filter_bar.addWidget(self.search_box)
        
        self.ctx_combo = QComboBox()
        self.ctx_combo.addItem("All Contexts", "")
        for k in _CTX_COLORS.keys():
            self.ctx_combo.addItem(k.upper() if k != "text" else "Prose", k)
        self.ctx_combo.currentIndexChanged.connect(self.refresh)
        filter_bar.addWidget(self.ctx_combo)
        
        self.app_combo = QComboBox()
        self.app_combo.addItem("All Apps", "")
        self.app_combo.currentIndexChanged.connect(self.refresh)
        filter_bar.addWidget(self.app_combo)
        
        filter_bar.addStretch()

        auto_save_lbl = QLabel("Auto-saves in local database")
        auto_save_lbl.setObjectName("mutedLabel")
        auto_save_lbl.setFont(ThemeManager.get_mono_font(10))
        filter_bar.addWidget(auto_save_lbl)

        root.addLayout(filter_bar)
        
        # 3. Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 4, 0, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch()
        self.scroll.setWidget(self.list_container)
        
        root.addWidget(self.scroll, 1)

    def refresh(self):
        query = self.search_box.text().strip()
        ctx_filter = self.ctx_combo.currentData()
        app_filter = self.app_combo.currentData()
        
        if query:
            items = self.db.search(query, limit=200)
        else:
            items = self.db.get_recent(limit=200)
            
        # Apply filters
        if ctx_filter:
            items = [x for x in items if x.context == ctx_filter]
        if app_filter:
            items = [x for x in items if x.application == app_filter]
            
        # Clear list
        while self.list_layout.count() > 1: # keep stretch
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        # Re-populate app dropdown based on available apps if no search
        if not query and not app_filter:
            apps = sorted(list(set(x.application for x in self.db.get_recent(limit=500))))
            self.app_combo.blockSignals(True)
            self.app_combo.clear()
            self.app_combo.addItem("All Apps", "")
            for a in apps:
                self.app_combo.addItem(a, a)
            self.app_combo.blockSignals(False)

        if not items:
            empty = QLabel("No dictations found.")
            empty.setObjectName("mutedLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setFont(ThemeManager.get_ui_font(14))
            self.list_layout.insertWidget(self.list_layout.count() - 1, empty)
            return

        # Group by day
        by_day = {}
        for it in items:
            try:
                dt = datetime.fromisoformat(it.timestamp)
                ds = dt.strftime("%Y-%m-%d")
            except Exception:
                ds = "Unknown"
            if ds not in by_day:
                by_day[ds] = []
            by_day[ds].append(it)
            
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        for ds, day_items in by_day.items():
            # Day header with count
            day_title = "Today" if ds == today_str else ds
            hdr_text = f"{day_title} · {len(day_items)} transcription{'s' if len(day_items) != 1 else ''}"
            hdr = QLabel(hdr_text)
            hdr.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.Bold))
            hdr.setContentsMargins(0, 14, 0, 4)
            self.list_layout.insertWidget(self.list_layout.count() - 1, hdr)
            
            for it in day_items:
                w = HistoryEntryWidget(it, self.config, self)
                w.deleted.connect(self._on_item_deleted)
                self.list_layout.insertWidget(self.list_layout.count() - 1, w)

    def _on_item_deleted(self, item_id: str):
        if self.db.delete(item_id):
            self.refresh()
            
    def _clear_history(self):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Clear History", "Are you sure you want to delete all history? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            with self.db._get_connection() as conn:
                conn.execute("DELETE FROM history")
                conn.commit()
            self.refresh()
