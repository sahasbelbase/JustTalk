"""One source of truth for language settings.

Users answer one question ("which languages do I speak?") and pick what they're typing in right
now from those languages only. This module derives the valid typing choices and repairs saved
settings that contradict each other (for example Spoken Languages = Nepali only while the active
language is English, which sent Nepali speech to an English recogniser).
"""

from __future__ import annotations

from typing import List, Tuple

from .config import ADDITIONAL_LANGUAGES, CORE_SPOKEN_LANGUAGES

MIXED_NEPALI_ENGLISH = "ne_en"

_SHORT_NAMES = {
    "en": "English",
    "ne": "नेपाली",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
    "zh": "中文",
}


def language_label(code: str) -> str:
    if code == MIXED_NEPALI_ENGLISH:
        return "Mixed"
    if code in _SHORT_NAMES:
        return _SHORT_NAMES[code]
    for name, c in ADDITIONAL_LANGUAGES:
        if c == code:
            return name.split(" (")[0]
    for item in CORE_SPOKEN_LANGUAGES:
        if item["code"] == code:
            return item["name"]
    return code


def spoken_or_default(spoken: List[str] | None) -> List[str]:
    langs = [c for c in (spoken or []) if c]
    return list(dict.fromkeys(langs)) or ["en"]


def typing_choices(spoken: List[str] | None) -> List[Tuple[str, str]]:
    """(code, label) for each language the user can type in right now, English first."""
    langs = spoken_or_default(spoken)
    ordered = (["en"] if "en" in langs else []) + [c for c in langs if c != "en"]
    choices = [(c, language_label(c)) for c in ordered]
    if "en" in langs and "ne" in langs:
        choices.append((MIXED_NEPALI_ENGLISH, "Mixed"))
    return choices


def default_typing_language(spoken: List[str] | None) -> str:
    langs = spoken_or_default(spoken)
    return "en" if "en" in langs else langs[0]


def normalize_language_settings(config) -> bool:
    """
    Make the saved language settings consistent. Returns True if anything changed.
    - spoken languages are never empty
    - the active typing language is one of the typing choices
    - the Nepali engine is a supported value
    """
    changed = False
    langs = spoken_or_default(getattr(config, "spoken_languages", None))
    if langs != list(getattr(config, "spoken_languages", None) or []):
        config.spoken_languages = langs
        changed = True

    # The typing language is what the user actively chose, so it wins: a language missing from
    # "languages I speak" is added rather than switching them to something else. (A Nepali-only
    # list with English typing means they also speak English, not that they want Nepali.)
    lang = (getattr(config, "language", None) or "").lower()
    if lang in ("", "auto", "none"):
        config.language = default_typing_language(langs)
        changed = True
    else:
        needed = ["en", "ne"] if lang == MIXED_NEPALI_ENGLISH else [lang]
        missing = [c for c in needed if c not in langs]
        if missing:
            langs = langs + missing
            langs = (["en"] if "en" in langs else []) + [c for c in langs if c != "en"]
            config.spoken_languages = langs
            changed = True

    engine = getattr(config, "nepali_asr_engine", "kriti")
    if engine not in ("kriti", "whisper"):
        # "conformer" (retired Ampixa model) and anything unknown
        config.nepali_asr_engine = "kriti" if engine == "conformer" else "whisper"
        changed = True
    return changed


def typing_summary(config) -> str:
    """One line describing what will happen, for Home and the tray."""
    lang = getattr(config, "language", "en")
    translate = getattr(config, "speech_mode", "transcribe") == "translate"
    if translate:
        if lang == "en":
            return "You speak English; it's typed in English."
        return f"You speak {language_label(lang) if lang != MIXED_NEPALI_ENGLISH else 'Nepali and English'}; it's typed in English."
    if lang == MIXED_NEPALI_ENGLISH:
        return "Nepali and English, typed as you speak them."
    if lang == "ne":
        mode = getattr(config, "nepali_output_mode", "auto")
        style = {
            "romanized": "in Romanized Nepali (k cha)",
            "devanagari": "in Devanagari (के छ)",
            "english": "translated to English",
        }.get(mode, "in Romanized or Devanagari depending on the app")
        return f"Nepali, typed {style}."
    return f"{language_label(lang)}, typed as you speak."
