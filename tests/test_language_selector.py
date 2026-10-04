"""Unit tests for SearchableLanguageComboBox."""

import pytest
from PySide6.QtWidgets import QApplication

# Ensure QApplication exists for widgets
app = QApplication.instance() or QApplication([])

from just_talk.app.language_selector import SearchableLanguageComboBox


def test_language_selector_init_and_selection():
    combo = SearchableLanguageComboBox()
    assert combo.count() >= 8

    # Default selection
    combo.set_current_language("ne_en")
    assert combo.get_current_language() == "ne_en"
    assert "Nepglish" in combo.currentText()

    combo.set_current_language("es")
    assert combo.get_current_language() == "es"
    assert "Spanish" in combo.currentText()


def test_language_selector_search_matching():
    combo = SearchableLanguageComboBox()
    # Test typing / matching "nepali"
    combo._match_and_select("nepali")
    assert combo.get_current_language() in ("ne", "ne_en")

    combo._match_and_select("german")
    assert combo.get_current_language() == "de"

    combo._match_and_select("french")
    assert combo.get_current_language() == "fr"
