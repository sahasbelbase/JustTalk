"""Edit selected text by voice: select text, hold the shortcut + Shift, speak an instruction."""

import types

import pytest

from just_talk.ai.prompts import EDIT_SELECTION_STYLE, build_edit_selection_prompt
from just_talk.ai.providers import MultiProviderFormatter
from just_talk.system.clipboard import ClipboardManager
from just_talk.system.inserter import TextInserter


# ── Prompt ─────────────────────────────────────────────────────────────────

def test_edit_prompt_carries_spoken_instruction():
    prompt = build_edit_selection_prompt("  make this shorter  ")
    assert "SPOKEN INSTRUCTION: make this shorter" in prompt
    assert "<transcript>" in prompt


def test_edit_prompt_survives_braces_in_instruction():
    # str.format would raise on these
    prompt = build_edit_selection_prompt("wrap it in {curly} braces")
    assert "{curly}" in prompt


# ── Provider request ───────────────────────────────────────────────────────

def _capturing_formatter(reply):
    f = MultiProviderFormatter(provider_id="gemini", api_key="mock_key")
    seen = {}

    def fake_format_gemini(raw_text, wrapped_instruction, key):
        seen["raw_text"] = raw_text
        seen["instruction"] = wrapped_instruction
        seen["budget"] = f._time_budget(raw_text)
        return reply, True, ""

    f._format_gemini = fake_format_gemini
    return f, seen


def test_edit_request_uses_edit_prompt_without_dictation_rules():
    f, seen = _capturing_formatter("Meet at 10.")
    prompt = build_edit_selection_prompt("make this shorter")
    out, ok, _ = f.format_text(
        "We should probably try to meet at around 10 if that works.",
        style=EDIT_SELECTION_STYLE,
        custom_system_instruction=prompt,
    )
    assert ok and out == "Meet at 10."
    assert seen["instruction"] == prompt
    # Dictation-only directives would contradict "make this shorter"
    assert "DO NOT summarize" not in seen["instruction"]
    assert "acoustic speech" not in seen["instruction"]


def test_edit_request_gets_longer_time_budget():
    f, seen = _capturing_formatter("Hi.")
    f.format_text("Hello there.", style=EDIT_SELECTION_STYLE, custom_system_instruction=build_edit_selection_prompt("shorter"))
    assert seen["budget"] == MultiProviderFormatter.EDIT_SELECTION_BUDGET_SEC

    # A normal dictation right after keeps the snappy budget
    f.format_text("Hello there.", style="subtle")
    assert seen["budget"] == 2.0


# ── Reading the selection ──────────────────────────────────────────────────

def test_copy_selection_returns_selected_text_and_restores_clipboard(monkeypatch):
    ClipboardManager.set_text("user's own clipboard")

    def fake_copy(self):
        ClipboardManager.set_text("the selected sentence")
        return True

    monkeypatch.setattr(TextInserter, "_synthesize_copy", fake_copy)
    assert TextInserter().copy_selection() == "the selected sentence"
    assert ClipboardManager.get_text() == "user's own clipboard"


def test_copy_selection_is_empty_when_nothing_selected():
    # The app ignores Cmd/Ctrl+C, so the clipboard still holds the sentinel
    ClipboardManager.set_text("old clipboard text")
    assert TextInserter().copy_selection(timeout_sec=0.1) == ""
    assert ClipboardManager.get_text() == "old clipboard text"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("const x = 1;\n", True),       # VS Code copies the current line when nothing is selected
        ("const x = 1;\r\n", True),
        ("const x = 1;", False),        # real partial selection
        ("line one\nline two\n", False),  # real multi-line selection
    ],
)
def test_implicit_line_copy_detection(text, expected):
    assert TextInserter.is_implicit_line_copy(text) is expected


# ── Pipeline ───────────────────────────────────────────────────────────────

class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def _fake_app(format_result):
    from just_talk.app.main import JustTalkApp

    bridge = types.SimpleNamespace(
        state_processing=_Signal(), state_inserted=_Signal(), state_copied=_Signal(), state_error=_Signal()
    )
    inserted, saved = [], []
    app = types.SimpleNamespace(
        bridge=bridge,
        config=types.SimpleNamespace(restore_clipboard=True),
        gemini=types.SimpleNamespace(format_text=lambda **kw: format_result),
        inserter=types.SimpleNamespace(
            insert=lambda text, restore_clipboard=True: inserted.append(text) or (True, "inserted", "Notes")
        ),
        db=types.SimpleNamespace(add=lambda **kw: saved.append(kw)),
    )
    app._edit_selected_text = types.MethodType(JustTalkApp._edit_selected_text, app)
    return app, inserted, saved


def test_pipeline_replaces_selection_with_edited_text():
    app, inserted, saved = _fake_app(("Meet at 10.", True, "ok"))
    app._edit_selected_text("We should meet at around 10.", "make this shorter", None, 0.0, "text", None)

    assert inserted == ["Meet at 10."]
    assert app.bridge.state_inserted.calls
    assert saved[0]["action"] == EDIT_SELECTION_STYLE
    assert saved[0]["raw_transcription"] == "make this shorter"
    assert saved[0]["processed_text"] == "Meet at 10."


def test_pipeline_leaves_selection_alone_when_ai_fails():
    app, inserted, saved = _fake_app(("We should meet at around 10.", False, "Timeout"))
    app._edit_selected_text("We should meet at around 10.", "make this shorter", None, 0.0, "text", None)

    assert inserted == []
    assert saved == []
    assert app.bridge.state_error.calls == [("Couldn't edit selection",)]
