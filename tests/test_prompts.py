"""Tests for voice keyboard prompts and prompt builder."""

import pytest
from just_talk.ai.prompts import (
    SYSTEM_PROMPT_AUTO,
    SYSTEM_PROMPT_CONCISE,
    SYSTEM_PROMPT_FORMAL,
    SYSTEM_PROMPT_SUBTLE,
    SYSTEM_PROMPT_TRANSLATE,
    build_prompt,
)


def test_build_prompt_modes():
    assert build_prompt("subtle") == SYSTEM_PROMPT_SUBTLE
    assert build_prompt("formal") == SYSTEM_PROMPT_FORMAL
    assert build_prompt("concise") == SYSTEM_PROMPT_CONCISE
    assert build_prompt("auto") == SYSTEM_PROMPT_AUTO
    # Safe fallback on unknown style
    assert build_prompt("unknown_style") == SYSTEM_PROMPT_SUBTLE


def test_build_prompt_translate():
    prompt = build_prompt("translate", target_language="Spanish")
    assert "Spanish" in prompt
    assert "{target_language}" not in prompt

    with pytest.raises(ValueError):
        build_prompt("translate")


def test_translate_prompt_code_switching_directives():
    prompt = build_prompt("translate", target_language="English")
    assert "English" in prompt
    assert "CODE-SWITCHING" in prompt
    assert "Nepali" in prompt
    assert "disfluencies" in prompt.lower()
