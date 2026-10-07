"""Voice isolation: speaker decisions, enrollment quality, profile storage and "that was me" recovery."""

import sqlite3
import time
import types

import numpy as np
import pytest

from just_talk.audio.voice_match import (
    DEFAULT_ACCEPT,
    VoiceProfile,
    adapt_profile,
    check_take_quality,
    combine_enrollment,
    decide,
    speech_only,
)

SR = 16000
rng = np.random.default_rng(7)


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def _speechlike(seconds, amp=0.2):
    t = np.arange(int(SR * seconds)) / SR
    envelope = 0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)  # syllable-rate modulation
    return (amp * envelope * np.sin(2 * np.pi * 180 * t) + 0.01 * rng.standard_normal(t.size)).astype(np.float32)


def _room(seconds, amp=0.002):
    return (amp * rng.standard_normal(int(SR * seconds))).astype(np.float32)


def _with_score(base, score):
    """A unit vector whose dot product with `base` is exactly `score`."""
    base = _unit(base)
    other = _unit(rng.standard_normal(base.size))
    other = _unit(other - np.dot(other, base) * base)
    return _unit(score * base + np.sqrt(1 - score**2) * other)


# ── speech_only ───────────────────────────────────────────────────────────

def test_speech_only_drops_silence_around_speech():
    audio = np.concatenate([_room(1.5), _speechlike(1.5), _room(1.5)])
    kept = speech_only(audio)
    assert 1.3 * SR <= len(kept) <= 1.9 * SR


def test_speech_only_falls_back_to_full_audio_when_too_little_speech():
    audio = _room(2.0)
    assert len(speech_only(audio)) == len(audio)


# ── decide ────────────────────────────────────────────────────────────────

def test_decide_match_uncertain_other_with_enrolled_threshold():
    me = _unit(rng.standard_normal(512))
    profile = VoiceProfile("Sahas", me, accept_threshold=0.60, sample_count=3)
    accept, reject = profile.thresholds
    assert reject == pytest.approx(0.35)

    assert decide(_with_score(me, 0.70), [profile]).action == "match"
    assert decide(_with_score(me, 0.70), [profile]).speaker == "Sahas"
    assert decide(_with_score(me, 0.45), [profile]).action == "uncertain"  # kept, not tagged
    assert decide(_with_score(me, 0.20), [profile]).action == "other"


def test_legacy_profile_uses_conservative_defaults():
    """Old single-take profiles scored the user as low as 0.23; only clearly different voices are dropped."""
    me = _unit(rng.standard_normal(512))
    legacy = VoiceProfile("Sahas", me)  # no threshold stored
    accept, reject = legacy.thresholds
    assert accept == DEFAULT_ACCEPT
    assert reject <= 0.30
    assert decide(_with_score(me, 0.45), [legacy]).action == "uncertain"


def test_decide_picks_the_closest_profile():
    a, b = _unit(rng.standard_normal(512)), _unit(rng.standard_normal(512))
    profiles = [VoiceProfile("A", a, 0.5), VoiceProfile("B", b, 0.5)]
    assert decide(_with_score(b, 0.8), profiles).speaker == "B"


# ── enrollment ────────────────────────────────────────────────────────────

def test_combine_enrollment_sets_threshold_below_take_consistency():
    me = _unit(rng.standard_normal(512))
    takes = [_with_score(me, 0.9) for _ in range(3)]
    profile, accept, consistency = combine_enrollment(takes)
    assert np.linalg.norm(profile) == pytest.approx(1.0, abs=1e-5)
    assert 0.40 <= accept <= 0.70
    assert accept < consistency


def test_combine_enrollment_flags_inconsistent_takes():
    takes = [_unit(rng.standard_normal(512)) for _ in range(3)]  # unrelated voices
    _, _, consistency = combine_enrollment(takes)
    assert consistency < 0.5


def test_adapt_profile_moves_toward_confirmed_sample():
    me = _unit(rng.standard_normal(512))
    sample = _with_score(me, 0.4)
    updated = adapt_profile(me, sample, sample_count=3)
    assert np.dot(updated, sample) > np.dot(me, sample)
    assert np.linalg.norm(updated) == pytest.approx(1.0, abs=1e-5)


@pytest.mark.parametrize(
    "audio, expected",
    [
        (np.zeros(SR * 5, dtype=np.float32), "No sound"),
        (np.clip(_speechlike(5, amp=2.0), -1, 1), "clipping"),
        (np.concatenate([_room(4.5), _speechlike(0.5)]), "Not enough speech"),
        (_speechlike(5, amp=0.2) + (0.12 * rng.standard_normal(SR * 5)).astype(np.float32), "background noise"),
    ],
)
def test_take_quality_problems_are_explained(audio, expected):
    assert expected in (check_take_quality(audio) or "")


def test_good_take_passes_quality_check():
    audio = np.concatenate([_room(0.5), _speechlike(4.0), _room(0.5)])
    assert check_take_quality(audio) is None


# ── storage ───────────────────────────────────────────────────────────────

def test_old_database_gains_threshold_columns(tmp_path):
    from just_talk.database.history import HistoryDatabase

    path = tmp_path / "history.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE voice_profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, embedding BLOB NOT NULL)")
    con.execute("INSERT INTO voice_profiles VALUES ('1', 'Sahas', '2026-10-01', ?)", (_unit(rng.standard_normal(512)).tobytes(),))
    con.commit()
    con.close()

    db = HistoryDatabase(path)
    rec = db.get_voice_profile_records()[0]
    assert rec["name"] == "Sahas" and rec["threshold"] is None and rec["sample_count"] == 1

    emb = _unit(rng.standard_normal(512))
    db.save_voice_profile("Sahas", emb, threshold=0.58, sample_count=3)
    rec = db.get_voice_profile_records()[0]
    assert rec["threshold"] == pytest.approx(0.58) and rec["sample_count"] == 3
    np.testing.assert_allclose(rec["embedding"], emb)

    db.update_voice_profile_embedding("Sahas", _unit(rng.standard_normal(512)), 4)
    rec = db.get_voice_profile_records()[0]
    assert rec["sample_count"] == 4 and rec["threshold"] == pytest.approx(0.58)  # threshold kept


# ── "that was me" recovery ────────────────────────────────────────────────

def _recovery_app(ignored_age_sec):
    from just_talk.app.main import JustTalkApp

    calls, learned = [], []
    audio = _speechlike(2.0)
    emb = _unit(rng.standard_normal(512))
    app = types.SimpleNamespace(
        IGNORED_VOICE_RECOVERY_SEC=JustTalkApp.IGNORED_VOICE_RECOVERY_SEC,
        _last_ignored=(audio, emb, time.time() - ignored_age_sec, False),
        _learn_voice_sample=lambda e: learned.append(e),
        _process_audio_pipeline=lambda a, action, force_accept_speaker=False: calls.append((a, action, force_accept_speaker)),
        inserter=types.SimpleNamespace(wait_for_modifiers_released=lambda: None, capture_active_target=lambda: None,
                                       insert=lambda text, restore_clipboard=True: (True, "inserted", "Notes")),
        last_dictation_text=lambda: "Older dictation.",
        bridge=types.SimpleNamespace(state_inserted=types.SimpleNamespace(emit=lambda *a: None),
                                     state_copied=types.SimpleNamespace(emit=lambda *a: None),
                                     state_error=types.SimpleNamespace(emit=lambda *a: None)),
        config=types.SimpleNamespace(restore_clipboard=True),
    )
    return app, calls, learned, audio, emb


def test_paste_last_right_after_ignore_recovers_and_learns():
    from just_talk.app.main import JustTalkApp

    app, calls, learned, audio, emb = _recovery_app(ignored_age_sec=5)
    JustTalkApp._paste_last_worker(app)
    assert len(calls) == 1 and calls[0][0] is audio and calls[0][2] is True  # re-run, speaker check skipped
    assert len(learned) == 1 and learned[0] is emb
    assert app._last_ignored is None


def test_paste_last_long_after_ignore_pastes_normally():
    from just_talk.app.main import JustTalkApp

    app, calls, learned, _, _ = _recovery_app(ignored_age_sec=600)
    JustTalkApp._paste_last_worker(app)
    assert calls == [] and learned == []


def test_learning_updates_closest_profile(tmp_path):
    from just_talk.app.main import JustTalkApp
    from just_talk.database.history import HistoryDatabase

    db = HistoryDatabase(tmp_path / "h.db")
    me = _unit(rng.standard_normal(512))
    db.save_voice_profile("Sahas", me, threshold=0.6, sample_count=3)
    db.save_voice_profile("Colleague", _unit(rng.standard_normal(512)), threshold=0.6, sample_count=3)
    app = types.SimpleNamespace(db=db)
    JustTalkApp._learn_voice_sample(app, _with_score(me, 0.5))
    recs = {r["name"]: r for r in db.get_voice_profile_records()}
    assert recs["Sahas"]["sample_count"] == 4
    assert recs["Colleague"]["sample_count"] == 3


# ── enrollment dialog (offscreen, fake microphone) ────────────────────────

class _FakeRecognizer:
    def __init__(self, embeddings):
        self._embs = list(embeddings)

    def is_available(self):
        return True

    def extract_embedding(self, audio):
        return self._embs.pop(0)


def _dialog(tmp_path, embeddings, monkeypatch):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from just_talk.app import voice_enroll_dialog as ved
    from just_talk.database.history import HistoryDatabase

    monkeypatch.setattr(ved, "SpeakerRecognizer", lambda: _FakeRecognizer(embeddings))
    db = HistoryDatabase(tmp_path / "h.db")
    dlg = ved.VoiceEnrollDialog(db, types.SimpleNamespace(audio_device_index=None), mode="enroll")
    return dlg, db


def test_enrollment_dialog_saves_three_take_profile(tmp_path, monkeypatch):
    me = _unit(rng.standard_normal(512))
    dlg, db = _dialog(tmp_path, [_with_score(me, 0.9) for _ in range(3)], monkeypatch)
    good = np.concatenate([_room(0.5), _speechlike(4.0), _room(0.5)])
    for _ in range(3):
        assert dlg._step == "record"
        dlg._on_take_finished(good)
    assert dlg._step == "save"
    dlg.name_input.setText("Sahas")
    dlg._on_action()
    rec = db.get_voice_profile_records()[0]
    assert rec["name"] == "Sahas" and rec["sample_count"] == 3 and rec["threshold"] is not None


def test_enrollment_dialog_rejects_bad_take_and_inconsistent_takes(tmp_path, monkeypatch):
    dlg, db = _dialog(tmp_path, [_unit(rng.standard_normal(512)) for _ in range(3)], monkeypatch)
    dlg._on_take_finished(np.zeros(SR * 5, dtype=np.float32))  # silent take
    assert "No sound" in dlg.status.text() and len(dlg.takes) == 0

    good = np.concatenate([_room(0.5), _speechlike(4.0), _room(0.5)])
    for _ in range(3):
        dlg._on_take_finished(good)
    assert dlg._step == "retry"  # three unrelated voices
    assert db.get_voice_profile_records() == []
