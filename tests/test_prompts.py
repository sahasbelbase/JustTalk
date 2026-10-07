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


def test_strict_preservation_directives():
    subtle = build_prompt("subtle")
    assert "resolve self-corrections" in subtle.lower()
    assert "do not summarize" in subtle.lower()
    assert "do not remove information" in subtle.lower()
    assert "preserve every single detail" in subtle.lower()

    auto = build_prompt("auto")
    assert "do not summarize" in auto.lower()
    assert "do not delete information" in auto.lower()

    translate = build_prompt("translate", target_language="English")
    assert "do not summarize" in translate.lower()


def test_nepglish_prompt_custom_styles():
    prompt_cha = build_prompt("nepglish", romanized_style="cha")
    assert "Romanized Nepali (Nepglish)" in prompt_cha
    assert "'cha'" in prompt_cha
    assert "k cha" in prompt_cha
    assert "thik cha" in prompt_cha

    prompt_chha = build_prompt("romanized", romanized_style="chha")
    assert "'chha'" in prompt_chha
    assert "k chha" in prompt_chha

    prompt_xa = build_prompt("ne_romanized", romanized_style="xa")
    assert "'xa'" in prompt_xa
    assert "k xa" in prompt_xa


def test_devanagari_prompt():
    prompt_dev = build_prompt("devanagari")
    assert "Nepali Devanagari" in prompt_dev
    assert "नेपाली लिपि" in prompt_dev
    assert "purnabiram" in prompt_dev
    assert "do not summarize" in prompt_dev.lower()



def test_meta_reply_from_request_like_speech_is_rejected():
    from just_talk.ai.prompts import is_meta_reply

    raw = "see what does the project give me an overview see in detail and let me know what do you think of this project"
    assert is_meta_reply(raw, "I will translate the spoken transcript into clean, natural, and fluent English.")
    assert is_meta_reply(raw, "I'm sorry, but I can't review a project from here.")
    assert is_meta_reply(raw, "Here is the cleaned transcript: See what the project does.")


def test_meta_reply_keeps_real_dictation():
    from just_talk.ai.prompts import is_meta_reply

    raw = "see what does the project give me an overview see in detail and let me know what do you think of this project"
    assert not is_meta_reply(raw, "See what the project does, give me a detailed overview, and let me know what you think of it.")
    # Speaker genuinely talking about transcripts or translation
    assert not is_meta_reply("i will translate the document tomorrow", "I will translate the document tomorrow.")
    assert not is_meta_reply("ma bholi aauchu", "I'll come tomorrow.")


def test_transcript_is_fenced_and_tags_stripped():
    from just_talk.ai.prompts import strip_transcript_tags, wrap_transcript

    assert wrap_transcript("hello") == "<transcript>\nhello\n</transcript>"
    assert strip_transcript_tags("<transcript>\nHello.\n</transcript>") == "Hello."
