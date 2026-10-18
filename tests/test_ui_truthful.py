"""The revamped screens: settings menu goes where it says, Home and History show real data."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from just_talk.config import AppConfig
from just_talk.database.history import HistoryDatabase, HistoryItem


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _window():
    from just_talk.ai.providers import MultiProviderFormatter
    from just_talk.app.main_window import MainWindow
    from just_talk.stt.model_manager import ModelManager

    config = AppConfig()
    config.save = lambda: None
    d = Path(tempfile.mkdtemp())
    return MainWindow(
        config=config,
        db=HistoryDatabase(d / "h.db"),
        model_manager=ModelManager(models_dir=d),
        gemini=MultiProviderFormatter(provider_id="gemini"),
        on_config_changed=lambda c: None,
    )


def test_each_settings_menu_entry_opens_its_own_section(qapp):
    w = _window()
    for btn in w.subnav_group.buttons():
        label = btn.text().strip().replace("&&", "&")
        for sec in w.settings_sections:
            sec.set_expanded(False)
        btn.click()
        opened = [s.title for s in w.settings_sections if not s.content_widget.isHidden()]
        assert len(opened) == 1 and label in opened[0], (label, opened)


def test_activity_grid_starts_on_sunday_and_ends_this_week(qapp):
    from just_talk.app.home_view import ContributionGraphWidget

    g = ContributionGraphWidget(HistoryDatabase(Path(tempfile.mkdtemp()) / "h.db"), AppConfig())
    for width in (500, 900, 2000):
        g.resize(width, 160)
        start, weeks = g._grid()
        assert start.weekday() == 6  # Sunday, the row the "Mon" label sits under is Monday
        assert start <= datetime.now().date() < start + timedelta(weeks=weeks)
        assert 38 + weeks * (g.cell_size + g.cell_margin) <= max(width, 38 + g.cell_size + g.cell_margin)


def test_history_marks_only_real_ai_changes():
    from just_talk.app.history_view import _change_label

    item = lambda raw, out, action="format": HistoryItem("1", "2026-10-18T10:00:00+00:00", action, raw, out, "App", "inserted")  # noqa: E731
    assert _change_label(item("we should meet at five", "We should meet at five.")) == ""
    assert _change_label(item("we should meet at five um", "We should meet at five.")) == "AI Refined"
    assert _change_label(item("म भोलि जान्छु", "I'll go tomorrow.", "translate")) == "Translated"
