"""Unit tests for spoken language selection, selective downloads, and Ampixa NepaliConformer."""

from pathlib import Path
import numpy as np

from just_talk.config import AppConfig, CORE_SPOKEN_LANGUAGES
from just_talk.stt.model_manager import ModelManager, TIERS
from just_talk.stt.nepali_conformer import NepaliConformerEngine


def test_config_spoken_languages_default():
    """Verify default spoken languages is English only."""
    config = AppConfig()
    assert config.spoken_languages == ["en"]
    assert config.nepali_asr_engine == "conformer"

    # Minimal models for English only:
    required = config.get_required_model_tiers()
    assert "small.en" in required or "base.en" in required
    assert "large-v3-turbo" not in required
    assert "nepali_conformer" not in required


def test_config_spoken_languages_with_nepali():
    """Verify selecting Nepali adds Ampixa NepaliConformer to required models."""
    config = AppConfig(spoken_languages=["en", "ne"], nepali_asr_engine="conformer")
    required = config.get_required_model_tiers()
    assert "nepali_conformer" in required
    assert "small.en" in required


def test_config_spoken_languages_multilingual():
    """Verify selecting German/French requires the multilingual tier."""
    config = AppConfig(spoken_languages=["en", "de"], model_tier="quality")
    required = config.get_required_model_tiers()
    assert "quality" in required


def test_model_manager_tiers_include_conformer_and_english():
    """Verify TIERS dictionary contains nepali_conformer, small.en, base.en."""
    assert "nepali_conformer" in TIERS
    assert "small.en" in TIERS
    assert "base.en" in TIERS

    conformer_info = TIERS["nepali_conformer"]
    assert "Ampixa" in conformer_info.display_name
    assert conformer_info.disk_size_mb == 462


def test_model_manager_language_calculations(tmp_path: Path):
    """Verify ModelManager computes minimal required models and download sizes."""
    mm = ModelManager(models_dir=tmp_path)

    # 1. English only
    en_models = mm.get_models_for_languages(["en"], tier_preference="quality")
    assert en_models == ["small.en"]

    # 2. English + Nepali
    ne_models = mm.get_models_for_languages(["en", "ne"], tier_preference="quality")
    assert "nepali_conformer" in ne_models
    assert "small.en" in ne_models

    # 3. Check download size
    size_mb = mm.get_total_download_size_mb(ne_models)
    assert size_mb > 500  # 462 + 461 = 923 MB

    # 4. Check are_required_models_downloaded on empty dir
    all_ready, missing = mm.are_required_models_downloaded(["en", "ne"], tier_preference="quality")
    assert all_ready is False
    assert "nepali_conformer" in missing
    assert "small.en" in missing


def test_nepali_conformer_engine_lifecycle(tmp_path: Path):
    """Verify NepaliConformerEngine initializes and can handle transcribe calls."""
    mm = ModelManager(models_dir=tmp_path)
    engine = NepaliConformerEngine(model_manager=mm)
    assert not engine.is_loaded()

    # Empty audio returns empty string
    empty_result = engine.transcribe(np.zeros(0, dtype=np.float32))
    assert empty_result == ""
