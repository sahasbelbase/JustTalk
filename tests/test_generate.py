"""Action mode with nothing selected: a spoken request ("write me a poem") is written, not just cleaned up."""

from just_talk.ai.prompts import GENERATE_STYLE, build_generate_prompt
from just_talk.ai.providers import MultiProviderFormatter


def test_generate_prompt_writes_instead_of_cleaning():
    prompt = build_generate_prompt()
    assert "write what they asked for" in prompt.lower()
    assert "<transcript>" in prompt


def test_generate_prompt_knows_code_editors():
    assert "Python" in build_generate_prompt(context="python")


def _formatter(reply):
    f = MultiProviderFormatter(provider_id="gemini", api_key="mock_key")
    seen = {}

    def fake(raw_text, wrapped_instruction, key):
        seen["user_message"] = f._user_message(raw_text)
        seen["instruction"] = wrapped_instruction
        seen["budget"] = f._time_budget(raw_text)
        return f._sanitize_output(raw_text, reply) or "", bool(f._sanitize_output(raw_text, reply)), ""

    f._format_gemini = fake
    return f, seen


def test_generate_request_uses_writing_prompt_and_long_budget():
    f, seen = _formatter("Dear Manager,\n\nI am unwell and need a sick day.\n\nRegards")
    prompt = build_generate_prompt()
    out, ok, _ = f.format_text(
        "write me a sick leave email", style=GENERATE_STYLE, custom_system_instruction=prompt
    )
    assert ok and out.startswith("Dear Manager")
    assert seen["instruction"] == prompt
    assert "DO NOT summarize" not in seen["instruction"]
    assert "never answer it" not in seen["instruction"]  # the dictation rule would block writing
    assert seen["user_message"] == "<transcript>\nwrite me a sick leave email\n</transcript>"
    assert seen["budget"] == MultiProviderFormatter.EDIT_SELECTION_BUDGET_SEC


def test_generated_text_may_start_like_a_reply_but_refusals_are_rejected():
    f, _ = _formatter("The rain falls soft on the quiet street,\nand every puddle holds the sky.")
    out, ok, _ = f.format_text("write me a poem", style=GENERATE_STYLE, custom_system_instruction="x")
    assert ok and out.startswith("The rain")

    f, _ = _formatter("I'm sorry, I can't help with that.")
    _, ok, _ = f.format_text("write me a poem", style=GENERATE_STYLE, custom_system_instruction="x")
    assert not ok


def test_dictation_after_a_generate_request_is_unaffected():
    f, seen = _formatter("Hello there.")
    f.format_text("write me a poem", style=GENERATE_STYLE, custom_system_instruction="x")
    f.format_text("hello there", style="subtle")
    assert "<transcript>" in seen["user_message"] and seen["budget"] == 2.0
