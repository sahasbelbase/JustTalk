"""The main window hides to the tray on close, but must not block a real quit (Cmd+Q / logout)."""

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    from just_talk.ai.gemini import GeminiFormatter
    from just_talk.app.main_window import MainWindow
    from just_talk.config import AppConfig
    from just_talk.database.history import HistoryDatabase
    from just_talk.stt.model_manager import ModelManager

    win = MainWindow(
        config=AppConfig(),
        db=HistoryDatabase(str(tmp_path / "h.db")),
        model_manager=ModelManager(models_dir=tmp_path / "models"),
        gemini=GeminiFormatter(),
    )
    yield app, win
    app.is_quitting = False


def test_closing_window_hides_to_tray(window):
    app, win = window
    app.is_quitting = False
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert not ev.isAccepted()


def test_app_quit_is_not_cancelled_by_window(window):
    app, win = window
    app.is_quitting = True
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert ev.isAccepted()
