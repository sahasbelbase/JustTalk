"""Shared test safety net.

Tests must never touch the real clipboard or send real keystrokes: TextInserter posts
Cmd/Ctrl+V, Cmd/Ctrl+C and Cmd/Ctrl+Z straight to the OS (CGEventPost / keybd_event), which pastes
test text into whatever app the developer has focused.
"""

import pytest


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
