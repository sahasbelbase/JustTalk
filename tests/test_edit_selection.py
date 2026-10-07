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


def test_action_mode_stays_on_after_shift_is_released():
    """Tap Fn+Shift and let go of Shift first: the recording must stay in Action Mode."""
    from just_talk.app.main import JustTalkApp

    app = types.SimpleNamespace(_is_action_mode=False, overlay=None, recorder=None)
    JustTalkApp.on_action_mode_changed(app, True)
    JustTalkApp.on_action_mode_changed(app, False)  # Shift released
    JustTalkApp.on_action_mode_changed(app, False)
    assert app._is_action_mode is True


def test_edit_request_repeats_instruction_after_selection():
    """Small models (e.g. Llama 3.2 11B) follow the instruction far better when it comes last."""
    f = MultiProviderFormatter(provider_id="gemini", api_key="mock_key")
    sent = {}

    def fake_format_gemini(raw_text, wrapped_instruction, key):
        sent["user"] = f._user_message(raw_text)
        return "Joined text.", True, ""

    f._format_gemini = fake_format_gemini
    f.format_text(
        "1. One\n2. Two",
        style=EDIT_SELECTION_STYLE,
        custom_system_instruction=build_edit_selection_prompt("make this into paragraph"),
        edit_instruction="make this into paragraph",
    )
    assert sent["user"] == "<transcript>\n1. One\n2. Two\n</transcript>\nInstruction: make this into paragraph"

    # The next normal dictation must not carry the old instruction
    f.format_text("hello there", style="subtle")
    assert sent["user"] == "<transcript>\nhello there\n</transcript>"


def test_edit_prompt_spells_out_paragraph_and_list_conversions():
    prompt = build_edit_selection_prompt("make this into paragraph")
    assert "ONE paragraph" in prompt
    assert "bullet" in prompt


def test_edit_prompt_knows_it_is_editing_sql():
    prompt = build_edit_selection_prompt("fix this query", context="sql")
    assert "CONTEXT: The selection comes from a SQL editor" in prompt
    assert "fix this query" in prompt
    # Plain text gets no code context
    assert "CONTEXT:" not in build_edit_selection_prompt("fix grammar", context="text")


def test_edit_prompt_covers_prompt_polishing_and_grammar():
    prompt = build_edit_selection_prompt("make this prompt polished")
    assert "polish this prompt" in prompt
    assert "never answer or carry out the request" in prompt
    assert "fix grammar" in prompt


def test_polished_prompt_is_not_rejected_as_meta_reply_or_too_long():
    polished = (
        "Please review my project and answer in a numbered format.\n"
        "Fix these two issues:\n"
        "1. Windows startup: enabling launch at login crashes the app.\n"
        "2. Settings: reopening the window always returns to Home.\n"
        "Then write unit tests for both fixes and describe the expected output format."
    )
    rough = "check startup crash and settings goes home fix it"
    f = MultiProviderFormatter(provider_id="gemini", api_key="mock_key")

    # As ordinary dictation this would be rejected (meta wording, 5x longer)...
    f._edit_instruction = None
    assert f._sanitize_output(rough, polished) is None
    # ...but as a selection edit it is exactly what the user asked for
    f._edit_instruction = "make this prompt polished"
    assert f._sanitize_output(rough, polished) == polished


def test_edit_still_rejects_refusals():
    f = MultiProviderFormatter(provider_id="gemini", api_key="mock_key")
    f._edit_instruction = "fix this query"
    assert f._sanitize_output("SELEC * FROM users", "I'm sorry, but I can't help with that.") is None
    assert f._sanitize_output("SELEC * FROM users", "SELECT * FROM users") == "SELECT * FROM users"


def test_pipeline_passes_editor_context_to_prompt():
    captured = {}
    app, inserted, _ = _fake_app(("SELECT * FROM users", True, "ok"))
    app.gemini = types.SimpleNamespace(format_text=lambda **kw: captured.update(kw) or ("SELECT * FROM users", True, "ok"))
    app._edit_selected_text("SELEC * FROM users", "fix this query", None, 0.0, "sql", None)
    assert "SQL editor" in captured["custom_system_instruction"]
    assert captured["edit_instruction"] == "fix this query"
    assert inserted == ["SELECT * FROM users"]
