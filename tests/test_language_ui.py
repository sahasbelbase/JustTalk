"""Simplified language UI: one "I speak" list, a Typing In switch on Home and in the tray."""

import tempfile
from pathlib import Path

import pytest

from just_talk.config import AppConfig


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _window(qapp, **cfg):
    from just_talk.ai.providers import MultiProviderFormatter
    from just_talk.app.main_window import MainWindow
    from just_talk.database.history import HistoryDatabase
    from just_talk.stt.model_manager import ModelManager

    config = AppConfig(**cfg)
    config.save = lambda: None
    d = Path(tempfile.mkdtemp())
    return MainWindow(
        config=config,
        db=HistoryDatabase(d / "h.db"),
        model_manager=ModelManager(models_dir=d),
        gemini=MultiProviderFormatter(provider_id="gemini"),
        on_config_changed=lambda c: None,
    )


def test_english_only_user_sees_no_nepali_options(qapp):
    w = _window(qapp, spoken_languages=["en"], language="en")
    assert list(w._typing_buttons) == ["en"]
    assert w.nepali_group.isHidden()
    assert w.home_kriti_banner.isHidden()


def test_ticking_nepali_adds_typing_choices_and_nepali_options(qapp):
    w = _window(qapp, spoken_languages=["en"], language="en")
    w.settings_lang_checkboxes["ne"].setChecked(True)
    assert list(w._typing_buttons) == ["en", "ne", "ne_en"]
    assert not w.nepali_group.isHidden()
    assert w.config.language == "en"  # English stays the default; Nepali is never forced
    assert not w.home_kriti_banner.isHidden()  # Kriti selected but not downloaded yet


def test_unticking_the_language_you_type_in_moves_you_to_one_you_speak(qapp):
    w = _window(qapp, spoken_languages=["en", "ne"], language="ne")
    w.settings_lang_checkboxes["ne"].setChecked(False)
    assert w.config.language == "en"
    assert list(w._typing_buttons) == ["en"]


def test_typing_switch_and_translate(qapp):
    w = _window(qapp, spoken_languages=["en", "ne"], language="en")
    w._typing_buttons["ne"].click()
    assert w.config.language == "ne"
    assert w._typing_buttons["ne"].isChecked() and not w._typing_buttons["en"].isChecked()
    assert "Nepali" in w.home_mode_desc.text()

    w.translate_check.setChecked(True)
    assert w.config.speech_mode == "translate"
    w.set_translate(False)
    assert w.config.speech_mode == "transcribe" and not w.translate_check.isChecked()


def test_nepali_engine_choice(qapp):
    w = _window(qapp, spoken_languages=["en", "ne"], language="ne", nepali_asr_engine="kriti")
    assert w.nepali_kriti_radio.isChecked()
    w.nepali_same_radio.setChecked(True)
    assert w.config.nepali_asr_engine == "whisper"
    assert w.kriti_row.isHidden()


def test_tray_offers_the_same_typing_choices(qapp):
    from PySide6.QtGui import QIcon

    from just_talk.app.tray import SystemTrayManager

    chosen = []
    config = AppConfig(spoken_languages=["en", "ne"], language="en")
    tray = SystemTrayManager(
        config=config, icon=QIcon(), on_open_main=lambda s: None, on_toggle_gemini=lambda b: None,
        on_change_tier=lambda t: None, on_quit=lambda: None,
        on_set_typing_language=chosen.append, on_set_translate=lambda on: None,
    )
    typing_menu = next(a.menu() for a in tray._menu.actions() if a.text() == "Typing In")
    labels = [a.text() for a in typing_menu.actions() if a.text()]
    assert labels[:3] == ["English", "नेपाली", "Mixed (Nepali + English)"]
    assert "Translate to English" in labels
    next(a for a in typing_menu.actions() if a.text() == "नेपाली").trigger()
    assert chosen == ["ne"]
