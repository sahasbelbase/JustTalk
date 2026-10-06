"""Searchable language selection dropdown with auto-completion and fast filtering."""

from __future__ import annotations

from typing import List, Optional, Tuple
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QCompleter, QLineEdit

from ..config import SUPPORTED_LANGUAGES
from .theme import ThemeManager


class SearchableLanguageComboBox(QComboBox):
    """
    Searchable dropdown allowing users to either pick from the supported
    languages list or type to filter (e.g. typing 'nep' highlights Nepali).
    """

    language_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        # Populate supported languages
        for display_name, code in SUPPORTED_LANGUAGES:
            self.addItem(display_name, code)

        # Setup searchable completer with substring matching
        completer = QCompleter(self)
        completer.setModel(self.model())
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompleter(completer)

        # Configure LineEdit
        line_edit = self.lineEdit()
        if line_edit:
            line_edit.setPlaceholderText("Search languages")
            line_edit.returnPressed.connect(self._on_enter_pressed)
            line_edit.editingFinished.connect(self._on_editing_finished)

        self.currentIndexChanged.connect(self._on_index_changed)

    def _on_index_changed(self, idx: int) -> None:
        code = self.itemData(idx)
        if code:
            self.language_changed.emit(code)

    def _on_enter_pressed(self) -> None:
        text = self.currentText().strip().lower()
        self._match_and_select(text)

    def _on_editing_finished(self) -> None:
        text = self.currentText().strip().lower()
        self._match_and_select(text)

    def _match_and_select(self, query: str) -> None:
        if not query:
            return
        # Find exact or substring match in display names or codes
        for i in range(self.count()):
            name = self.itemText(i).lower()
            code = str(self.itemData(i)).lower()
            if query == code or query in name:
                self.setCurrentIndex(i)
                self.setEditText(self.itemText(i))
                return

    def get_current_language(self) -> str:
        """Return the active language code (e.g. 'en', 'ne_en', 'es')."""
        val = self.currentData()
        if val is not None:
            return str(val)
        return "en"

    def set_current_language(self, code: str) -> None:
        """Set the active language by code without triggering spurious edits."""
        idx = self.findData(code)
        if idx >= 0:
            self.blockSignals(True)
            self.setCurrentIndex(idx)
            self.setEditText(self.itemText(idx))
            self.blockSignals(False)
