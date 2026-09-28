"""Native, minimalist history viewer window."""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..database.history import HistoryDatabase, HistoryItem
from ..system.clipboard import ClipboardManager


class HistoryWindow(QDialog):
    """Clean desktop window for viewing past voice input generations."""

    def __init__(self, db: HistoryDatabase, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db = db
        self._current_items = []

        self.setWindowTitle("Just Talk — History")
        self.resize(780, 520)
        self.setMinimumSize(600, 400)
        self._setup_ui()
        self.load_history()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Top Bar: Search and Actions
        top_bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search history...")
        self.search_input.textChanged.connect(self._on_search)
        top_bar.addWidget(self.search_input)

        clear_btn = QPushButton("Clear History")
        clear_btn.clicked.connect(self._on_clear_history)
        top_bar.addWidget(clear_btn)
        main_layout.addLayout(top_bar)

        # Splitter: Table List on Left, Detail Pane on Right
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Table
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Time", "Action", "Final Text"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.table)

        # Detail Panel
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        detail_layout.setSpacing(8)

        # Meta labels
        self.meta_label = QLabel("Select an entry to view details.")
        self.meta_label.setStyleSheet("color: #888; font-size: 11px;")
        detail_layout.addWidget(self.meta_label)

        # Processed text section
        detail_layout.addWidget(QLabel("Final Formatted Text:"))
        self.processed_view = QTextEdit()
        self.processed_view.setReadOnly(True)
        detail_layout.addWidget(self.processed_view)

        # Raw transcript section
        detail_layout.addWidget(QLabel("Raw Speech Transcription:"))
        self.raw_view = QTextEdit()
        self.raw_view.setReadOnly(True)
        self.raw_view.setMaximumHeight(90)
        self.raw_view.setStyleSheet("color: #aaa; background-color: #1a1a1e;")
        detail_layout.addWidget(self.raw_view)

        # Copy button
        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(self._on_copy_selected)
        detail_layout.addWidget(copy_btn)

        splitter.addWidget(detail_widget)
        splitter.setSizes([450, 330])
        main_layout.addWidget(splitter)

        # Styling
        self.setStyleSheet("""
            QDialog {
                background-color: #18181c;
                color: #e4e4e7;
            }
            QLineEdit, QTextEdit, QTableWidget {
                background-color: #222228;
                border: 1px solid #33333d;
                border-radius: 6px;
                color: #f4f4f5;
                padding: 6px;
            }
            QHeaderView::section {
                background-color: #202026;
                color: #a1a1aa;
                border: none;
                padding: 6px;
                font-weight: bold;
            }
            QPushButton {
                background-color: #2a2a34;
                border: 1px solid #3f3f4e;
                border-radius: 6px;
                color: #f4f4f5;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #383846;
            }
            QTableWidget::item:selected {
                background-color: #3b82f6;
                color: white;
            }
        """)

    def load_history(self) -> None:
        self._current_items = self.db.get_recent(limit=150)
        self._populate_table(self._current_items)

    def _on_search(self, text: str) -> None:
        if not text.strip():
            self.load_history()
            return
        self._current_items = self.db.search(text.strip())
        self._populate_table(self._current_items)

    def _populate_table(self, items: list[HistoryItem]) -> None:
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(item.formatted_time))
            self.table.setItem(row, 1, QTableWidgetItem(item.action.capitalize()))
            self.table.setItem(row, 2, QTableWidgetItem(item.processed_text))

        if items:
            self.table.selectRow(0)

    def _on_selection_changed(self) -> None:
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        if 0 <= row < len(self._current_items):
            item = self._current_items[row]
            self.processed_view.setPlainText(item.processed_text)
            self.raw_view.setPlainText(item.raw_transcription)
            self.meta_label.setText(
                f"Target App: {item.application}  •  Status: {item.status.capitalize()}  •  ID: {item.id[:8]}"
            )

    def _on_copy_selected(self) -> None:
        text = self.processed_view.toPlainText()
        if text:
            ClipboardManager.set_text(text)
            QMessageBox.information(self, "Copied", "Text copied to clipboard.")

    def _on_clear_history(self) -> None:
        reply = QMessageBox.question(
            self,
            "Clear History",
            "Are you sure you want to permanently clear all dictation history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.clear()
            self.load_history()
            self.processed_view.clear()
            self.raw_view.clear()
            self.meta_label.setText("History cleared.")
