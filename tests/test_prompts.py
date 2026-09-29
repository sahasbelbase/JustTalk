"""Tests for voice keyboard prompts and prompt builder."""

import pytest
from just_talk.ai.prompts import (
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


def test_build_prompt_translate():
    prompt = build_prompt("translate", target_language="Spanish")
    assert "Spanish" in prompt
    assert "{target_language}" not in prompt

    with pytest.raises(ValueError):
        build_prompt("translate")
