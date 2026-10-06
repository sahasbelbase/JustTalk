"""Tests that long dictation with pauses keeps every part of the speech."""

from unittest.mock import MagicMock

import numpy as np

from just_talk.audio.vad import VoiceActivityDetector
from just_talk.stt.google_web_engine import GoogleWebSTTEngine
from just_talk.stt.long_form import IncrementalTranscriber
from just_talk.stt.mac_native_engine import MacNativeSTTEngine, UtteranceTracker

SR = 16000


def _speech(sec: float) -> np.ndarray:
    t = np.arange(int(sec * SR)) / SR
    return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _silence(sec: float) -> np.ndarray:
    return np.zeros(int(sec * SR), dtype=np.float32)


def test_split_short_audio_is_untouched():
    audio = _speech(3.0)
    chunks = VoiceActivityDetector.split_on_pauses(audio, max_chunk_sec=15.0)
    assert len(chunks) == 1 and len(chunks[0]) == len(audio)


def test_split_cuts_at_pause_and_keeps_all_speech():
    audio = np.concatenate([_speech(10.0), _silence(1.0), _speech(10.0)])
    chunks = VoiceActivityDetector.split_on_pauses(audio, max_chunk_sec=15.0)
    assert len(chunks) == 2
    # Cut lands inside the pause, not mid-word
    assert 10.0 <= len(chunks[0]) / SR <= 11.0
    assert sum(len(c) for c in chunks) == len(audio)


def test_split_drops_long_silent_gap():
    audio = np.concatenate([_speech(8.0), _silence(20.0), _speech(8.0)])
    chunks = VoiceActivityDetector.split_on_pauses(audio, max_chunk_sec=10.0)
    speech_samples = sum(int(np.count_nonzero(c)) for c in chunks)
    assert speech_samples >= 2 * int(8.0 * SR) - 4  # sine has exact zero crossings
    assert all(np.max(np.abs(c)) > 0 for c in chunks)


def test_google_engine_stitches_chunks():
    engine = GoogleWebSTTEngine()
    engine.load()
    engine._recognizer = MagicMock()
    engine._recognizer.recognize_google.side_effect = ["first part", "second part"]

    audio = np.concatenate([_speech(10.0), _silence(1.0), _speech(10.0)])
    assert engine.transcribe(audio, language="en") == "first part second part"


def test_google_engine_network_failure_mid_dictation_returns_empty():
    import speech_recognition as sr

    engine = GoogleWebSTTEngine()
    engine.load()
    engine._recognizer = MagicMock()
    engine._recognizer.recognize_google.side_effect = ["first part", sr.RequestError("down")]

    audio = np.concatenate([_speech(10.0), _silence(1.0), _speech(10.0)])
    assert engine.transcribe(audio, language="en") == ""


def test_mac_merge_keeps_utterance_before_pause():
    committed = []
    latest = ""
    for partial in ["Hello", "Hello there", "Hello there how are you", "I am", "I am fine"]:
        latest = MacNativeSTTEngine.merge_utterances(committed, latest, partial)
    assert committed == ["Hello there how are you"]
    assert latest == "I am fine"


def test_mac_merge_treats_revisions_as_same_utterance():
    committed = []
    latest = ""
    for partial in ["Their is", "There is a", "There is a cat"]:
        latest = MacNativeSTTEngine.merge_utterances(committed, latest, partial)
    assert committed == []
    assert latest == "There is a cat"


def test_incremental_partial_keeps_earlier_speech():
    calls = []

    def fake_transcribe(audio, **kwargs):
        calls.append(len(audio))
        return f"seg{len(calls)}"

    inc = IncrementalTranscriber(fake_transcribe, window_sec=6.0)
    long_audio = np.concatenate([_speech(5.0), _silence(0.5), _speech(5.0)])

    text = inc.update(long_audio)
    # Earlier speech was committed once, the tail decoded live; both are kept.
    assert text == "seg1 seg2"
    assert len(calls) == 2 and calls[0] + calls[1] == len(long_audio)

    # New recording (shorter buffer) resets the cache
    assert inc.update(_speech(1.0)) == "seg3"


def test_tracker_keeps_utterances_across_pause_with_same_first_word():
    t = UtteranceTracker()
    for text, span in [("The plan", (0.2, 0.8)), ("The plan is good", (0.2, 1.6)),
                       ("The next", (6.1, 6.6)), ("The next step", (6.1, 7.2))]:
        t.add(text, span)
    assert t.text() == "The plan is good The next step"


def test_tracker_ignores_resent_utterance_and_revisions():
    # Replays the doubling seen in a real 52s dictation: Apple re-sent finished
    # utterances ("And", "The problem ...") after the next one had started.
    t = UtteranceTracker()
    seq = [
        ("We need to improve the dictation activity", (0.0, 2.5)),
        ("And", (4.0, 4.2)),
        ("And", (4.0, 4.2)),
        ("The problem is now", (6.0, 7.0)),
        ("The problem is now I am seeing double of everything", (6.0, 9.5)),
        ("Like", (12.0, 12.3)),
        ("The problem is now I am seeing double of everything", (6.0, 9.5)),
        ("Like whenever I say and", (12.0, 13.8)),
    ]
    for text, span in seq:
        t.add(text, span)
    assert t.text() == (
        "We need to improve the dictation activity And "
        "The problem is now I am seeing double of everything Like whenever I say and"
    )


def test_tracker_cumulative_result_replaces_covered_utterances():
    t = UtteranceTracker()
    t.add("first part", (0.0, 1.0))
    t.add("second part", (3.0, 4.0))
    t.add("first part second part", (0.0, 4.0))  # Apple returns everything so far
    assert t.text() == "first part second part"


def test_merge_without_timestamps_ignores_resent_utterance():
    committed = []
    latest = ""
    for partial in ["The problem is double", "Like", "The problem is double", "Like whenever"]:
        latest = MacNativeSTTEngine.merge_utterances(committed, latest, partial)
    assert committed == ["The problem is double"]
    assert latest == "Like whenever"

def test_mac_merge_keeps_short_utterance_when_next_is_longer():
    committed = []
    latest = ""
    for partial in ["Okay", "So the plan for tomorrow is"]:
        latest = MacNativeSTTEngine.merge_utterances(committed, latest, partial)
    assert committed == ["Okay"]
    assert latest == "So the plan for tomorrow is"


def test_mac_merge_keeps_longer_new_utterance_without_timestamps():
    committed = []
    latest = ""
    for partial in ["Hello there", "Then we should review every open pull request today"]:
        latest = MacNativeSTTEngine.merge_utterances(committed, latest, partial)
    assert committed == ["Hello there"]


def test_mac_chunk_error_uses_fallback_but_keeps_partial_when_fallback_empty():
    engine = MacNativeSTTEngine(offline_mode=False)
    engine._is_loaded = True
    engine._supported_locales = {"en-US"}
    engine.fallback_engine = MagicMock()

    import sys as _sys
    speech = MagicMock()
    speech.SFSpeechRecognizer.authorizationStatus.return_value = 3
    rec = MagicMock()
    rec.isAvailable.return_value = True
    speech.SFSpeechRecognizer.alloc.return_value.initWithLocale_.return_value = rec
    foundation = MagicMock()

    from unittest.mock import patch
    with patch.dict(_sys.modules, {"Speech": speech, "Foundation": foundation}), \
         patch.object(MacNativeSTTEngine, "is_available", return_value=True), \
         patch.object(MacNativeSTTEngine, "_recognize_native_chunk", return_value=("partial words", False)):
        engine.fallback_engine.transcribe.return_value = "full fallback words"
        assert engine.transcribe(_speech(2.0), language="en") == "full fallback words"
        engine.fallback_engine.transcribe.return_value = ""
        assert engine.transcribe(_speech(2.0), language="en") == "partial words"


def test_tracker_untimed_partials_then_timed_final_do_not_duplicate():
    t = UtteranceTracker()
    t.add("The problem", None)
    t.add("The problem is now", None)
    t.add("The problem is now I am seeing double", (6.0, 9.0))
    t.add("The problem is now I am seeing double", None)  # re-sent without timings
    assert t.text() == "The problem is now I am seeing double"
