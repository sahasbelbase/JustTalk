"""Shared test safety net.

Tests must never touch the real clipboard or send real keystrokes: TextInserter posts
Cmd/Ctrl+V, Cmd/Ctrl+C and Cmd/Ctrl+Z straight to the OS (CGEventPost / keybd_event), which pastes
test text into whatever app the developer has focused.

Nor the developer's own app data: AppConfig().save() and CredentialManager write to
~/Library/Application Support/JustTalk (config.json, .credentials), so a test run reset the
installed app's settings and deleted its stored API keys.
"""

import pytest

from just_talk.config import get_app_data_dir

# Downloaded speech models are a cache, not settings: the live Whisper test may read them from here
REAL_MODELS_DIR = get_app_data_dir() / "models"


@pytest.fixture(autouse=True)
def _no_real_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))


@pytest.fixture(autouse=True)
def _no_real_clipboard_or_keystrokes(monkeypatch):
    from just_talk.system.clipboard import ClipboardManager
    from just_talk.system.inserter import TextInserter

    fake_clipboard = {"text": ""}

    def fake_set(text):
        fake_clipboard["text"] = text
        return True

    monkeypatch.setattr(ClipboardManager, "get_text", staticmethod(lambda: fake_clipboard["text"]))
    monkeypatch.setattr(ClipboardManager, "set_text", staticmethod(fake_set))
    monkeypatch.setattr(TextInserter, "_synthesize_paste", lambda self: True)
    monkeypatch.setattr(TextInserter, "_reactivate_target_window", lambda self: None)
    monkeypatch.setattr(TextInserter, "undo_last_paste", lambda self: None)
    monkeypatch.setattr(TextInserter, "_synthesize_copy", lambda self: True)
    monkeypatch.setattr(TextInserter, "_modifiers_down", staticmethod(lambda: False))
    yield
