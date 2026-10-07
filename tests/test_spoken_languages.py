"""Unit tests for spoken language selection, selective downloads, and Ampixa NepaliConformer."""

from pathlib import Path
import numpy as np

from just_talk.config import AppConfig, CORE_SPOKEN_LANGUAGES
from just_talk.stt.model_manager import ModelManager, TIERS
from just_talk.stt.nepali_conformer import NepaliConformerEngine


def test_config_spoken_languages_default():
    """Verify default spoken languages is English only with whisper engine."""
    config = AppConfig()
    assert config.spoken_languages == ["en"]
    assert config.nepali_asr_engine == "whisper"

    # Minimal models for English only:
    required = config.get_required_model_tiers()
    assert "small.en" in required or "base.en" in required
    assert "large-v3-turbo" not in required
    assert "nepali_conformer" not in required


def test_config_spoken_languages_with_nepali():
    """Verify selecting Nepali uses Whisper out-of-the-box or Conformer if explicitly configured."""
    # Out-of-the-box default: uses multilingual Whisper tier
    config_whisper = AppConfig(spoken_languages=["en", "ne"], nepali_asr_engine="whisper", model_tier="quality")
    req_whisper = config_whisper.get_required_model_tiers()
    assert "quality" in req_whisper
    assert "nepali_conformer" not in req_whisper

    # Explicit conformer engine
    config_conf = AppConfig(spoken_languages=["en", "ne"], nepali_asr_engine="conformer")
    required = config_conf.get_required_model_tiers()
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

    # 2. English + Nepali (out-of-the-box Whisper default)
    ne_models_whisper = mm.get_models_for_languages(["en", "ne"], tier_preference="quality", nepali_engine="whisper")
    assert ne_models_whisper == ["quality"]

    # 3. English + Nepali (explicit Conformer engine)
    ne_models_conf = mm.get_models_for_languages(["en", "ne"], tier_preference="quality", nepali_engine="conformer")
    assert "nepali_conformer" in ne_models_conf
    assert "small.en" in ne_models_conf

    # 4. Check download size for conformer
    size_mb = mm.get_total_download_size_mb(ne_models_conf)
    assert size_mb > 500  # 462 + 461 = 923 MB

    # 5. Check are_required_models_downloaded on empty dir for conformer
    all_ready, missing = mm.are_required_models_downloaded(["en", "ne"], tier_preference="quality", nepali_engine="conformer")
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


def test_saved_conformer_choice_falls_back_to_whisper_without_runtime(tmp_path, monkeypatch):
    """The gated .nemo download can't run without NeMo, so a saved 'conformer' choice is migrated."""
    import json

    import just_talk.stt.model_manager as mm_mod

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"spoken_languages": ["ne"], "nepali_asr_engine": "conformer"}))
    monkeypatch.setattr(AppConfig, "get_config_path", classmethod(lambda cls: cfg_path))
    monkeypatch.setattr(mm_mod, "nepali_conformer_runtime_available", lambda: False)

    config = AppConfig.load()
    assert config.nepali_asr_engine == "whisper"
    assert "nepali_conformer" not in config.get_required_model_tiers()  # no 462 MB download that can't run
    assert json.loads(cfg_path.read_text())["nepali_asr_engine"] == "whisper"  # persisted


def test_saved_conformer_choice_kept_when_runtime_present(tmp_path, monkeypatch):
    import json

    import just_talk.stt.model_manager as mm_mod

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"nepali_asr_engine": "conformer"}))
    monkeypatch.setattr(AppConfig, "get_config_path", classmethod(lambda cls: cfg_path))
    monkeypatch.setattr(mm_mod, "nepali_conformer_runtime_available", lambda: True)

    assert AppConfig.load().nepali_asr_engine == "conformer"


def test_conformer_engine_reports_unavailable_without_nemo(tmp_path, monkeypatch):
    """No more fake 'Hybrid Bridge' ready state that silently used Whisper."""
    mm = ModelManager(models_dir=tmp_path)
    engine = NepaliConformerEngine(model_manager=mm)
    model_dir = mm.get_model_path("nepali_conformer")
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "nepali_conformer_offline.nemo").write_bytes(b"0" * 2048)
    monkeypatch.setattr(mm, "is_model_downloaded", lambda tier: True)

    import builtins

    real_import = builtins.__import__

    def no_nemo(name, *args, **kwargs):
        if name.startswith("nemo"):
            raise ImportError("No module named 'nemo'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_nemo)
    assert engine.load() is False
    assert not engine.is_loaded()
    assert "NeMo" in engine.loading_status
