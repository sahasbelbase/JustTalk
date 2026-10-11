"""Unit tests for spoken language selection and selective downloads."""

from pathlib import Path
import pytest

from just_talk.config import AppConfig, CORE_SPOKEN_LANGUAGES
from just_talk.stt.model_manager import ModelManager, TIERS


def test_config_spoken_languages_default():
    """Default: English only; Nepali (if added later) uses Kriti once downloaded."""
    config = AppConfig()
    assert config.spoken_languages == ["en"]
    assert config.nepali_asr_engine == "kriti"

    # Minimal models for English only:
    required = config.get_required_model_tiers()
    assert "small.en" in required or "base.en" in required
    assert "large-v3-turbo" not in required


def test_config_spoken_languages_with_nepali():
    """Selecting Nepali needs the multilingual Whisper tier (Kriti is downloaded separately)."""
    config_whisper = AppConfig(spoken_languages=["en", "ne"], nepali_asr_engine="whisper", model_tier="quality")
    assert "quality" in config_whisper.get_required_model_tiers()


def test_config_spoken_languages_multilingual():
    """Verify selecting German/French requires the multilingual tier."""
    config = AppConfig(spoken_languages=["en", "de"], model_tier="quality")
    required = config.get_required_model_tiers()
    assert "quality" in required


def test_model_manager_tiers_include_english():
    assert "small.en" in TIERS
    assert "base.en" in TIERS
    assert "nepali_conformer" not in TIERS


def test_model_manager_language_calculations(tmp_path: Path):
    """Verify ModelManager computes minimal required models and download sizes."""
    mm = ModelManager(models_dir=tmp_path)

    # 1. English only
    en_models = mm.get_models_for_languages(["en"], tier_preference="quality")
    assert en_models == ["small.en"]

    # 2. English + Nepali (out-of-the-box Whisper default)
    ne_models_whisper = mm.get_models_for_languages(["en", "ne"], tier_preference="quality", nepali_engine="whisper")
    assert ne_models_whisper == ["quality"]

    # 3. Nothing downloaded yet on an empty dir
    all_ready, missing = mm.are_required_models_downloaded(["en"], tier_preference="quality")
    assert all_ready is False
    assert "small.en" in missing


def test_retired_conformer_choice_moves_to_kriti(tmp_path, monkeypatch):
    """A config saved while the Ampixa NepaliConformer existed is migrated to Kriti."""
    import json

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"spoken_languages": ["ne"], "nepali_asr_engine": "conformer"}))
    monkeypatch.setattr(AppConfig, "get_config_path", classmethod(lambda cls: cfg_path))

    config = AppConfig.load()
    assert config.nepali_asr_engine == "kriti"
    assert "nepali_conformer" not in config.get_required_model_tiers()
    assert json.loads(cfg_path.read_text())["nepali_asr_engine"] == "kriti"  # persisted


@pytest.mark.parametrize(
    "language, spoken, mode, provider, expected",
    [
        # The reported bug: Nepali-only speaker, dictation language left on English, translate on
        ("en", ["ne"], "translate", "google_web", "ne"),
        # ...but an explicit English dictation language is respected (the same user dictates English)
        ("en", ["ne"], "transcribe", "google_web", "en"),
        ("auto", ["ne"], "transcribe", "os_native", "ne"),
        # Mixed Nepali + English on a single-locale engine -> Nepali locale
        ("ne_en", ["en", "ne"], "transcribe", "google_web", "ne"),
        # Whisper auto-detects mixed speech itself
        ("ne_en", ["en", "ne"], "transcribe", "whisper", None),
        # Unchanged: English speaker, explicit languages
        ("en", ["en"], "transcribe", "google_web", "en"),
        ("de", ["en", "de"], "transcribe", "google_web", "de"),
        ("en", ["en", "ne"], "translate", "whisper", None),
        # English + Nepali speaker translating: don't force Nepali onto their English
        ("en", ["en", "ne"], "translate", "google_web", None),
    ],
)
def test_stt_language_follows_spoken_languages(language, spoken, mode, provider, expected):
    config = AppConfig(language=language, spoken_languages=spoken, stt_provider=provider)
    assert config.stt_language(mode == "translate") == expected


# ── Language setup (one question: which languages do I speak?) ───────────────

def test_typing_choices_follow_spoken_languages():
    from just_talk.language_setup import typing_choices

    assert [c for c, _ in typing_choices(["en"])] == ["en"]
    assert [c for c, _ in typing_choices(["ne"])] == ["ne"]
    assert [c for c, _ in typing_choices(["ne", "en"])] == ["en", "ne", "ne_en"]  # English first, Mixed last
    assert [c for c, _ in typing_choices(["en", "de"])] == ["en", "de"]
    assert [c for c, _ in typing_choices([])] == ["en"]


@pytest.mark.parametrize(
    "spoken, language, expected_spoken, expected_lang",
    [
        # The reported setup: Nepali-only list, typing English. Keep English; add it to the list.
        (["ne"], "en", ["en", "ne"], "en"),
        (["en", "ne"], "ne_en", ["en", "ne"], "ne_en"),
        (["en"], "ne_en", ["en", "ne"], "ne_en"),
        (["en", "de"], "fr", ["en", "de", "fr"], "fr"),
        (["en"], "auto", ["en"], "en"),
        ([], "en", ["en"], "en"),
    ],
)
def test_normalize_never_switches_the_typing_language(spoken, language, expected_spoken, expected_lang):
    from just_talk.language_setup import normalize_language_settings

    config = AppConfig(spoken_languages=spoken, language=language)
    normalize_language_settings(config)
    assert config.language == expected_lang
    assert config.spoken_languages == expected_spoken


def test_english_is_the_default_typing_language():
    from just_talk.language_setup import default_typing_language

    assert AppConfig().language == "en"
    assert default_typing_language(["ne", "en"]) == "en"
    assert default_typing_language(["en"]) == "en"


def test_normalize_leaves_consistent_settings_alone():
    from just_talk.language_setup import normalize_language_settings

    config = AppConfig(spoken_languages=["en", "ne"], language="ne", nepali_asr_engine="kriti")
    assert normalize_language_settings(config) is False


def test_typing_summary_reads_naturally():
    from just_talk.language_setup import typing_summary

    assert "Nepali" in typing_summary(AppConfig(language="ne", spoken_languages=["en", "ne"], nepali_output_mode="romanized"))
    assert "English" in typing_summary(AppConfig(language="ne", spoken_languages=["en", "ne"], speech_mode="translate"))


def test_mixed_mode_sends_confident_english_to_whisper_not_kriti():
    from just_talk.language_setup import english_dominant

    assert english_dominant(("en", 0.9))
    assert not english_dominant(("en", 0.4))      # unsure: stay on Kriti
    assert not english_dominant(("ne", 0.95))
    assert not english_dominant(("hi", 0.8))      # Whisper often calls Nepali "Hindi"
    assert not english_dominant(None)             # no Whisper loaded: behaviour unchanged
