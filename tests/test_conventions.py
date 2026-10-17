"""Tests for Writing Conventions configuration view."""

import pytest
from PySide6.QtWidgets import QApplication

from just_talk.app.conventions_view import ConventionsView, _DEFAULTS
from just_talk.config import AppConfig


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_conventions_view_init(qapp):
    config = AppConfig()
    saved_conventions = []
    view = ConventionsView(config=config, on_save=lambda c: saved_conventions.append(c))

    assert view._current_ctx == "sql"
    assert "Live Preview: SQL Context" in view.preview_title.text()
    assert "SELECT *" in view._preview_output.toPlainText()


def test_conventions_context_switch(qapp):
    config = AppConfig()
    view = ConventionsView(config=config)

    # Switch to python
    idx = view._lang_combo.findData("python")
    assert idx >= 0
    view._lang_combo.setCurrentIndex(idx)

    assert view._current_ctx == "python"
    assert "Live Preview: Python Context" in view.preview_title.text()
    assert "def calculate_discount" in view._preview_output.toPlainText()


def test_conventions_option_change_and_dynamic_preview(qapp):
    config = AppConfig()
    view = ConventionsView(config=config)

    # Change SQL keyword case to lower
    view._on_option_changed("keyword_case", "lower")
    assert view._conventions["sql"]["keyword_case"] == "lower"
    assert "select *" in view._preview_output.toPlainText()

    # Turn off schema prefix
    view._on_option_changed("schema_prefix", False)
    assert "dbo." not in view._preview_output.toPlainText()


def test_conventions_rule_filtering(qapp):
    config = AppConfig()
    view = ConventionsView(config=config)

    # Filter rules for "naming"
    view._filter_rules("naming")
    visible_keys = [k for k, frame in view._rule_widgets if not frame.isHidden()]
    assert "naming_style" in visible_keys
    assert "dialect" not in visible_keys

    # Clear filter
    view._filter_rules("")
    assert all(not frame.isHidden() for _, frame in view._rule_widgets)


def test_conventions_reset_current(qapp):
    config = AppConfig()
    view = ConventionsView(config=config)

    view._on_option_changed("keyword_case", "lower")
    assert view._conventions["sql"]["keyword_case"] == "lower"

    view._reset_current()
    assert view._conventions["sql"]["keyword_case"] == _DEFAULTS["sql"]["keyword_case"]
    assert "SELECT *" in view._preview_output.toPlainText()
