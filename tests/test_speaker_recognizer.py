"""Unit tests for WeSpeaker CAM++ SpeakerRecognizer."""

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from just_talk.audio.speaker_recognizer import SpeakerRecognizer, compute_fbank


def test_compute_fbank_dimensions():
    """Verify log-mel filterbank output shape."""
    # 2 seconds of synthetic audio at 16kHz
    audio = np.random.randn(32000).astype(np.float32)
    feats = compute_fbank(audio, sr=16000, n_mels=80)
    assert feats.ndim == 2
    assert feats.shape[1] == 80
    assert feats.shape[0] > 100


def test_speaker_recognizer_availability():
    """Verify is_available handles missing or existing model cleanly."""
    sr = SpeakerRecognizer(model_path="/nonexistent/model.onnx")
    assert sr.is_available() is False


def test_speaker_identification_logic():
    """Verify cosine similarity matching logic with synthetic embeddings."""
    sr = SpeakerRecognizer()
    
    # Create two orthogonal normalized embeddings
    emb_speaker1 = np.zeros(512, dtype=np.float32)
    emb_speaker1[0] = 1.0  # Unit vector on axis 0

    emb_speaker2 = np.zeros(512, dtype=np.float32)
    emb_speaker2[1] = 1.0  # Unit vector on axis 1

    profiles = {
        "Speaker 1": emb_speaker1,
        "Speaker 2": emb_speaker2,
    }

    # Mock extract_embedding to return emb_speaker1
    with patch.object(sr, "extract_embedding", return_value=emb_speaker1):
        speaker, conf = sr.identify_speaker(np.zeros(16000), profiles, threshold=0.7)
        assert speaker == "Speaker 1"
        assert conf >= 0.99

    # Mock extract_embedding to return an unknown random vector
    unknown_emb = np.zeros(512, dtype=np.float32)
    unknown_emb[2] = 1.0  # Orthogonal to both
    with patch.object(sr, "extract_embedding", return_value=unknown_emb):
        speaker, conf = sr.identify_speaker(np.zeros(16000), profiles, threshold=0.7)
        assert speaker is None
        assert conf < 0.1
