"""Voice profile: scoring read-aloud takes, the setup session, saving, and engine choice."""

from types import SimpleNamespace

import numpy as np
import pytest

from just_talk.profile.engines import apply_choice, can_apply, current_engine_id
from just_talk.profile.scoring import MISHEARD, MISSED, OK, score_take, skeleton_key
from just_talk.profile.scripts import BASE, EN, MIXED, NE, focus_of, word_prompts
from just_talk.profile.session import ProfileSession, languages_to_profile
from just_talk.profile.store import VoiceProfile, save_clip


def statuses(score):
    return [w.status for w in score.words]


# ── Scoring ───────────────────────────────────────────────────────────────────

def test_english_perfect_take_scores_full():
    s = score_take("Can we move the review meeting to Thursday afternoon?", "can we move the review meeting to thursday afternoon", EN)
    assert s.accuracy == 1.0
    assert set(statuses(s)) == {OK}


def test_english_mishearing_is_recorded():
    s = score_take("I will visit the village.", "I will bisit the village", EN)
    assert s.words[2].status == MISHEARD
    assert s.mishearings == [("bisit", "visit")]
    assert s.accuracy == pytest.approx(4 / 5)


def test_inserted_words_lower_accuracy():
    s = score_take("Send the file.", "send the the file", EN)
    assert s.inserted == 1
    assert s.accuracy == pytest.approx(3 / 4)


def test_partial_take_moves_the_frontier():
    s = score_take("I will visit the village on Wednesday.", "I will visit", EN)
    assert s.frontier == 2
    assert s.words[5].status == MISSED


def test_devanagari_spelling_variants_are_not_errors():
    s = score_take("हामी अर्को हप्ता पोखरा घुम्न जाँदैछौं।", "हामी अर्को हप्ता पोखरा घुम्न जांदैछौ", NE)
    assert s.accuracy == 1.0


def test_devanagari_real_mistakes_are_caught():
    # Whisper's take on the user's own test clip: बोली (speech) is not भोलि (tomorrow)
    s = score_take("म भोलि अफिस जान्छु अनि रिपोर्ट पठाउँछु।", "मा बोली आफिस जान्चू औनि रिपोर्ट पठाऊंचू", NE)
    assert s.words[1].status == MISHEARD
    assert s.words[0].status == MISHEARD  # मा is a different word from म
    assert s.accuracy < 0.3


def test_devanagari_word_breaks_do_not_matter():
    s = score_take("आज को काम सकियो।", "आजको काम सकियो", NE)
    assert s.accuracy == 1.0


def test_nepglish_heard_in_devanagari_matches_romanized_script():
    s = score_take(
        "Aaja ko meeting ma hami project ko update discuss garchau.",
        "आजको मिटिङमा हामी प्रोजेक्टको अपडेट डिस्कस गर्छौं।",
        MIXED,
    )
    assert s.mode == "skeleton"
    assert s.accuracy == 1.0


@pytest.mark.parametrize("a,b", [("meeting", "मिटिङ"), ("feature", "फिचर"), ("review", "रिभ्यु"), ("chha", "छ"), ("very", "भेरी")])
def test_skeleton_keys_agree_across_scripts(a, b):
    assert skeleton_key(a) == skeleton_key(b)


def test_empty_heard_text_misses_everything():
    s = score_take("Send the file.", "", EN)
    assert s.accuracy == 0.0
    assert s.frontier == -1


# ── Scripts ───────────────────────────────────────────────────────────────────

def test_focus_detects_nepali_english_sounds():
    assert "v_w" in focus_of("village")
    assert "th" in focus_of("Thursday")
    assert "s_cluster" in focus_of("school")
    assert "z" in focus_of("zoo")


def test_word_prompts_use_personal_words():
    prompts = word_prompts(["Sahas", "Naamche", " "], [EN])
    assert len(prompts) == 2
    assert "Sahas" in prompts[0].text and prompts[0].kind == "word"


# ── Session ───────────────────────────────────────────────────────────────────

def test_languages_to_profile_adds_mixed_for_bilinguals():
    assert languages_to_profile(["en"]) == [EN]
    assert languages_to_profile(["en", "ne"]) == [EN, NE, MIXED]
    assert languages_to_profile(["ne"]) == [NE]


def _read_all(session, heard_for):
    clip = 0
    while (p := session.next_prompt()) is not None:
        clip += 1
        cid = f"c{clip}"
        session.start_take(p, cid)
        for engine, fn in heard_for.items():
            session.add_result(cid, engine, fn(p))
    return clip


def test_session_runs_base_set_and_summarises():
    session = ProfileSession([EN], current_engine={EN: "apple"})
    n = _read_all(session, {"apple": lambda p: p.text})
    assert n == len(BASE[EN])  # perfect reading needs no follow-ups
    [s] = session.summary()
    assert s.best == "apple" and s.best_accuracy == 1.0
    assert not s.suggest_switch


def test_session_adds_followups_for_misheard_sounds():
    def mishear_v(p):
        return " ".join("b" + w[1:] if w.lower().startswith(("v", "w")) else w for w in p.text.split())

    session = ProfileSession([EN], current_engine={EN: "apple"})
    n = _read_all(session, {"apple": mishear_v})
    assert n > len(BASE[EN])
    followups = [t for t in session.takes.values() if t.prompt.kind == "followup"]
    assert any(t.prompt.focus == "v_w" for t in followups)


def test_session_recommends_clearly_better_engine():
    session = ProfileSession([NE], current_engine={NE: "whisper:quality"})
    _read_all(session, {"whisper:quality": lambda p: "गलत", "kriti": lambda p: p.text})
    [s] = session.summary()
    assert s.best == "kriti"
    assert s.suggest_switch


def test_session_keeps_current_engine_when_close():
    session = ProfileSession([EN], current_engine={EN: "apple"})
    first = {}

    def nearly(p):
        # whisper is perfect, apple misses one word in the first sentence only
        if not first:
            first["done"] = True
            words = p.text.split()
            return " ".join(words[:-1])
        return p.text

    _read_all(session, {"apple": nearly, "whisper:quality": lambda p: p.text})
    [s] = session.summary()
    assert s.best == "apple"


def test_engine_with_no_output_is_left_out():
    session = ProfileSession([EN], current_engine={EN: "apple"})
    _read_all(session, {"apple": lambda p: "", "whisper:small.en": lambda p: p.text})
    [s] = session.summary()
    assert "apple" not in s.accuracy
    assert s.best == "whisper:small.en"


def test_keep_training_adds_sentences_below_target():
    session = ProfileSession([EN], current_engine={EN: "apple"})
    _read_all(session, {"apple": lambda p: " ".join(p.text.split()[:-2])})
    assert session.keep_training() > 0
    assert session.next_prompt().kind == "extra"


def test_profile_round_trip(tmp_path):
    session = ProfileSession([EN], personal_words=["Sahas"], current_engine={EN: "apple"})
    _read_all(session, {"apple": lambda p: p.text.replace("Sahas", "Saas")})
    profile = session.to_profile({"apple": "Apple"}, {})
    assert profile.words == ["Sahas"]
    assert {"heard": "Saas", "meant": "Sahas", "language": EN, "count": 1, "confirmed": False} in profile.mishearings
    profile.save(tmp_path)
    loaded = VoiceProfile.load(tmp_path)
    assert loaded.languages[EN]["engine"] == "apple"
    assert loaded.accuracy(EN) == profile.accuracy(EN)


def test_profile_keeps_earlier_clips_and_counts_repeat_mishearings(tmp_path):
    first = ProfileSession([EN], personal_words=["Sahas"], current_engine={EN: "apple"})
    _read_all(first, {"apple": lambda p: p.text.replace("Sahas", "Saas")})
    p1 = first.to_profile({}, {})
    second = ProfileSession([EN], personal_words=["Sahas"], current_engine={EN: "apple"})
    # different clip ids so both sessions' clips are kept
    clip = 0
    while (p := second.next_prompt()) is not None:
        clip += 1
        second.start_take(p, f"s{clip}")
        second.add_result(f"s{clip}", "apple", p.text.replace("Sahas", "Saas"))
    p2 = second.to_profile({}, {}, previous=p1)
    assert len(p2.clips) == len(p1.clips) + clip
    entry = next(m for m in p2.mishearings if m["meant"] == "Sahas")
    assert entry["count"] == 2


def test_save_clip_writes_wav(tmp_path):
    rel = save_clip(np.zeros(1600, dtype=np.float32), "abc", tmp_path)
    assert (tmp_path / rel).exists()


# ── Engine choice ─────────────────────────────────────────────────────────────

def cfg(**kw):
    base = dict(stt_provider="os_native", model_tier="quality", nepali_asr_engine="kriti",
                spoken_languages=["en"], stt_model_source="bundled", offline_mode=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_current_engine_for_nepali_prefers_downloaded_kriti():
    assert current_engine_id(cfg(), NE, kriti_available=True) == "kriti"
    assert current_engine_id(cfg(stt_provider="whisper"), NE, kriti_available=False) == "whisper:quality"


def test_apply_whisper_for_english_switches_main_engine():
    c = cfg()
    assert apply_choice(c, EN, "whisper:quality") is True
    assert c.stt_provider == "whisper" and c.model_tier == "quality"


def test_english_only_whisper_not_offered_when_it_would_also_get_nepali():
    c = cfg(spoken_languages=["en", "ne"], nepali_asr_engine="whisper")
    assert not can_apply(c, EN, "whisper:small.en")
    c.nepali_asr_engine = "kriti"
    assert can_apply(c, EN, "whisper:small.en")


def test_apply_kriti_for_nepali_only_touches_nepali_engine():
    c = cfg(nepali_asr_engine="whisper", stt_provider="whisper")
    assert apply_choice(c, NE, "kriti") is False
    assert c.nepali_asr_engine == "kriti" and c.stt_provider == "whisper"


# ── Roles ─────────────────────────────────────────────────────────────────────

def test_compound_words_split_or_joined_by_the_engine_still_count():
    s = score_take("Open a pull request on GitHub.", "open a pull request on git hub", EN)
    assert s.accuracy == 1.0
    s = score_take("It needs more white space.", "it needs more whitespace", EN)
    assert s.accuracy == 1.0


def test_role_jargon_mishearing_is_learned():
    # The user's own example: "push to git" heard as "push to gate"
    session = ProfileSession([EN], role="software", current_engine={EN: "apple"})
    _read_all(session, {"apple": lambda p: p.text.replace("git ", "gate ")})
    [s] = session.summary()
    assert ("gate", "git") in s.mishearings
    assert session.to_profile({}, {}).role == "software"


def test_role_sentences_are_read_in_each_language():
    session = ProfileSession([EN, NE, MIXED], role="software")
    kinds = [(p.language, p.kind) for p in session.queue]
    assert (EN, "role") in kinds and (MIXED, "role") in kinds
    assert (NE, "role") not in kinds


def test_every_role_has_terms_and_sentences():
    from just_talk.profile.scripts import ROLES, role_terms

    for role in ROLES:
        assert role_terms(role.id)
        assert len(role.english) >= 2 and len(role.mixed) >= 2


# ── Using the profile while dictating ─────────────────────────────────────────

def test_speaker_context_names_role_words_and_mixups():
    from just_talk.ai.prompts import speaker_context_block

    block = speaker_context_block("Software engineer", ["git", "GitHub", "git"], [("gate", "git")])
    assert "Software engineer" in block
    assert block.count("git,") == 1  # duplicates removed
    assert '"gate" when they said "git"' in block
    assert speaker_context_block() == ""


def test_formatter_appends_speaker_context_to_dictation_prompt(monkeypatch):
    from just_talk.ai.providers import MultiProviderFormatter

    seen = {}
    f = MultiProviderFormatter(provider_id="gemini", api_key="test-key", model_name="m")

    def fake_gemini(raw_text, wrapped_instruction, key):
        seen["system"] = wrapped_instruction
        return raw_text, True, ""

    monkeypatch.setattr(f, "_format_gemini", fake_gemini)
    f.format_text("push to gate", speaker_context="ABOUT THE SPEAKER: software")
    assert "ABOUT THE SPEAKER" in seen["system"]
    f.format_text("push to gate")
    assert "ABOUT THE SPEAKER" not in seen["system"]


def test_engines_compared_on_fewer_sentences_are_judged_on_shared_ones():
    session = ProfileSession([EN], current_engine={EN: "apple"})
    n = 0
    while (p := session.next_prompt()) is not None:
        n += 1
        session.start_take(p, f"c{n}")
        # apple misses the last word everywhere; turbo only ran on the first two sentences, perfectly
        session.add_result(f"c{n}", "apple", " ".join(p.text.split()[:-1]))
        if n <= 2:
            session.add_result(f"c{n}", "whisper:quality", p.text)
    s = next(x for x in session.summary() if x.language == EN)
    assert s.best == "whisper:quality"
    assert s.in_use == "apple"


def test_digits_count_as_number_words():
    assert score_take("The meeting is at ten.", "the meeting is at 10", EN).accuracy == 1.0


def test_roman_nasal_matches_devanagari():
    assert score_take("Ma report pathaunchu.", "म रिपोर्ट पठाउँछु", MIXED).accuracy == 1.0


def test_mixups_skip_off_script_takes():
    session = ProfileSession([EN], current_engine={EN: "apple"})
    p = session.next_prompt()
    session.start_take(p, "a")
    session.add_result("a", "apple", "completely different words were said here instead")
    p2 = session.next_prompt()
    session.start_take(p2, "b")
    session.add_result("b", "apple", p2.text.replace("check", "chek").replace("the", "da"))
    [s] = session.summary()
    meant = [m for _, m in s.mishearings]
    assert "check" in meant
    assert not any(m in p.text and m not in p2.text for m in meant)  # nothing from the garbled take


def test_apple_recognizer_gets_vocabulary_as_contextual_strings():
    """Apple ignores Whisper prompts; contextual strings are how it learns to expect "git"."""
    import sys as _sys
    from unittest.mock import MagicMock, patch

    from just_talk.stt.mac_native_engine import MacNativeSTTEngine

    speech = MagicMock()
    request = speech.SFSpeechURLRecognitionRequest.alloc.return_value.initWithURL_.return_value
    recognizer = MagicMock()
    recognizer.supportsOnDeviceRecognition.return_value = True

    def run_task(req, handler):
        result = MagicMock()
        result.bestTranscription.return_value.formattedString.return_value = "push to git"
        result.bestTranscription.return_value.segments.return_value = []
        result.isFinal.return_value = True
        handler(result, None)
        return MagicMock()

    recognizer.recognitionTaskWithRequest_resultHandler_.side_effect = run_task
    engine = MacNativeSTTEngine(offline_mode=True)
    engine.vocabulary = ["git", "GitHub"]
    with patch.dict(_sys.modules, {"Speech": speech, "Foundation": MagicMock()}):
        text, ok = engine._recognize_native_chunk(recognizer, np.zeros(16000, dtype=np.float32), "en-US")
    request.setContextualStrings_.assert_called_once_with(["git", "GitHub"])
    assert ok and text == "push to git"


def test_vocabulary_terms_merge_own_words_and_role():
    from just_talk.profile.scripts import vocabulary_terms

    terms = vocabulary_terms(cfg(custom_vocabulary="Sahas, git", user_role="software"))
    assert terms[0] == "Sahas" and terms.count("git") == 1 and "GitHub" in terms


def test_word_every_engine_heard_differently_is_a_reading_slip_not_a_mixup():
    session = ProfileSession([EN], current_engine={EN: "whisper:small.en"})
    p = session.next_prompt()  # "I will visit the village on Wednesday with my whole family."
    session.start_take(p, "a")
    slip = p.text.replace("whole", "full")          # both engines agree: the speaker said "full"
    session.add_result("a", "whisper:small.en", slip.replace("village", "billage"))
    session.add_result("a", "whisper:quality", slip)  # turbo heard "village" right
    [s] = session.summary()
    meant = [m for _, m in s.mishearings]
    assert "village" in meant   # one engine got it, so the other one misheard
    assert "whole" not in meant  # nobody heard "whole": a reading slip



# ── Learning from the user's own data ─────────────────────────────────────────

from just_talk.profile.learner import Learner, shaped_terms


def test_shaped_terms_find_names_and_jargon_without_word_lists():
    assert shaped_terms("Push it to GitHub, update LinkedIn and build the DMG. I think it's OK.") == ["GitHub", "LinkedIn", "DMG"]


def test_a_word_seen_once_is_not_used_until_seen_again(tmp_path):
    learner = Learner(tmp_path / "learned.json")
    learner.observe_dictation("open github", "Open GitHub.")
    assert "GitHub" not in learner.known_terms()
    learner.observe_dictation("check github", "Check GitHub.")
    assert "GitHub" in learner.known_terms()


def test_review_learns_git_from_the_users_own_history(tmp_path):
    learner = Learner(tmp_path / "learned.json")
    history = [
        ("After this is finished build DMZEXE run it and push to the gate", "After this is finished, build DMZ.exe, run it, and push to the gate."),
        ("Can you send the build to the git push", "Can you send the build to the git push?"),
    ]
    sent = {}

    def ask(system, user):
        sent["user"] = user
        return '```json\n{"terms": ["git", "GitHub"], "mixups": [{"heard": "gate", "meant": "git", "evidence": "push to the gate"}]}\n```'

    assert learner.review(history, ask) == (2, 1)
    assert "push to the gate" in sent["user"]
    assert ("gate", "git") in learner.known_mixups()
    assert "git" in learner.known_terms()
    assert Learner.load(tmp_path / "learned.json").known_mixups() == [("gate", "git")]


def test_cleanup_swaps_into_known_words_become_mixups(tmp_path):
    learner = Learner(tmp_path / "learned.json")
    learner.add_term("git", "review")
    learner.observe_dictation("push to the gate", "Push to the git.")
    learner.observe_dictation("open the gate now", "Open the git now.")
    assert ("gate", "git") in learner.known_mixups()


def test_single_unconfirmed_setup_mixup_waits_for_more_evidence(tmp_path):
    learner = Learner(tmp_path / "learned.json")
    learner.learn_from_setup([{"heard": "da", "meant": "the"}, {"heard": "bery", "meant": "very", "confirmed": True}])
    assert ("bery", "very") in learner.known_mixups()
    assert ("da", "the") not in learner.known_mixups()


def test_forgotten_items_are_never_relearned(tmp_path):
    learner = Learner(tmp_path / "learned.json")
    learner.add_mixup("gate", "git", "review")
    learner.forget_mixup("gate", "git")
    learner.add_mixup("gate", "git", "review")
    assert learner.known_mixups() == []
    learner.forget_term("Naamche")
    learner.add_term("Naamche", "review")
    assert "Naamche" not in learner.known_terms()


def test_review_ignores_a_reply_that_is_not_json(tmp_path):
    learner = Learner(tmp_path / "learned.json")
    assert learner.review([("a", "b")], lambda s, u: "Sorry, I can't help with that.") == (0, 0)


def test_role_seed_words_step_aside_once_own_words_are_learned(tmp_path):
    from just_talk.profile.scripts import vocabulary_terms

    learner = Learner(tmp_path / "learned.json")
    c = cfg(custom_vocabulary="", user_role="software")
    assert "Docker" in vocabulary_terms(c, learner)  # day one: role seed
    for i in range(10):
        learner.add_term(f"Term{i}", "review")
    terms = vocabulary_terms(c, learner)
    assert "Term0" in terms and "Docker" not in terms


def test_sound_overlap_separates_same_speech_from_different_speech():
    from just_talk.profile.scoring import sound_overlap

    kriti = "हेलो क्यान यु हेल मी विद दिस फर्स्ट आइ वान्ट यु टु लिस्ट डाउन फाइभ अफ माइ आइटम्स्"
    assert sound_overlap("Hello, can you help me with this? First, I want you to list down five of my items.", kriti) > 0.8
    nepali = "के खाने होला आज कस्तो मोमो खान मन लागिरहेको छ"
    assert sound_overlap("I want to eat something today and I am hungry", nepali) < 0.4
    assert sound_overlap("", nepali) == 0.0
