"""Kriti offline Nepali engine: verified download from our release, and safe fallbacks."""

import hashlib

import httpx
import numpy as np
import pytest

from just_talk.stt.kriti_engine import (
    KRITI_FILES,
    KritiEngine,
    download_kriti,
    is_kriti_downloaded,
    kriti_model_dir,
)
from just_talk.stt.kriti_onnx import FeatureExtractor, mel_filterbank


def _fake_release(files, tamper=None):
    sums = "\n".join(f"{hashlib.sha256(data).hexdigest()}  {name}" for name, data in files.items())
    served = dict(files)
    if tamper:
        served[tamper] = b"tampered"

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        if name == "SHA256SUMS.txt":
            return httpx.Response(200, text=sums)
        if name in served:
            body = served[name]
            return httpx.Response(200, content=b"" if request.method == "HEAD" else body,
                                  headers={"content-length": str(len(body))})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def release_files():
    return {name: f"content of {name}".encode() * 50 for name in KRITI_FILES}


def _patch_client(monkeypatch, transport):
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=transport, **kw))


def test_download_verifies_and_installs_every_file(tmp_path, monkeypatch, release_files):
    _patch_client(monkeypatch, _fake_release(release_files))
    seen = []
    ok, msg = download_kriti(tmp_path, progress=seen.append)
    assert ok, msg
    assert is_kriti_downloaded(tmp_path)
    for name, data in release_files.items():
        assert (kriti_model_dir(tmp_path) / name).read_bytes() == data
    assert seen and seen[-1] == pytest.approx(1.0)


def test_tampered_file_is_rejected_and_not_installed(tmp_path, monkeypatch, release_files):
    _patch_client(monkeypatch, _fake_release(release_files, tamper="encoder.int8.onnx"))
    ok, msg = download_kriti(tmp_path)
    assert not ok and "integrity" in msg
    assert not (kriti_model_dir(tmp_path) / "encoder.int8.onnx").exists()
    assert not is_kriti_downloaded(tmp_path)


def test_engine_falls_back_quietly_when_not_downloaded(tmp_path):
    engine = KritiEngine(tmp_path)
    assert not engine.is_available()
    assert engine.transcribe(np.ones(16000, dtype=np.float32)) == ""


def test_engine_never_translates(tmp_path):
    """Kriti only transcribes Nepali; translation stays with the other engines."""
    engine = KritiEngine(tmp_path)
    engine._model = object()  # would crash if used
    assert engine.transcribe(np.ones(16000, dtype=np.float32), task="translate") == ""


def test_mel_filterbank_shape_and_coverage():
    fb = mel_filterbank(16000, 512, 80, 0.0, 8000.0)
    assert fb.shape == (80, 257)
    assert (fb >= 0).all()
    assert (fb.sum(axis=1) > 0).all()  # every mel band covers some FFT bins


def test_features_have_nemo_frame_count_and_normalisation():
    fx = FeatureExtractor({"sample_rate": 16000, "window_size": 0.025, "window_stride": 0.01, "n_fft": 512,
                           "features": 80, "normalize": "per_feature", "log": True, "preemph": 0.97},
                          stft_pad_mode="reflect")
    audio = (0.1 * np.random.default_rng(1).standard_normal(32000)).astype(np.float32)
    feats = fx(audio)
    assert feats.shape == (80, 32000 // 160 + 1)
    assert np.abs(feats.mean(axis=1)).max() < 1e-4
