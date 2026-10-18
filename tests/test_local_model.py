"""On-device AI: prompt shape, answer checks, and which dictations it handles."""

from types import SimpleNamespace

from just_talk.ai.local_model import LocalModel, build_prompt, check_output
from just_talk.app.main import JustTalkApp


def test_prompt_disables_thinking_and_keeps_a_stable_prefix():
    a = build_prompt("translate", "म भोलि आउँछु", "ABOUT THE SPEAKER: software")
    b = build_prompt("translate", "अर्को कुरा", "ABOUT THE SPEAKER: software")
    assert a.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
    prefix = a.split("<|im_start|>user")[0]
    assert b.startswith(prefix)  # same system turn, so llama.cpp reuses its cache


def test_good_answers_pass():
    assert check_output("translate", "म भोलि अफिस जान्छु अनि रिपोर्ट पठाउँछु।", "I will go to the office tomorrow and send the report.") is None
    assert check_output("cleanup", "um so send the file to the team", "So, send the file to the team.") is None


def test_bad_answers_are_rejected():
    src = "सबै सबै सबै सबैलाई सबैलाई सबै"
    assert check_output("translate", src, "All all all all all all all all all all all all all all") is not None
    assert check_output("translate", "नमस्ते तपाईंलाई कस्तो छ", "नमस्ते how are you") == "left Devanagari untranslated"
    assert check_output("cleanup", "send it now please", "Output only the cleaned text: Send it now, please.") == "repeated its instructions"
    assert check_output("cleanup", "send the report to the team before friday", "Done.") is not None
    assert check_output("cleanup", "anything", "") == "empty"


def test_words_the_speaker_said_are_not_mistaken_for_prompt_leaks():
    assert check_output("cleanup", "can you translate this file for me", "Can you translate this file for me?") is None


def test_local_model_is_unavailable_without_the_download(tmp_path):
    assert not LocalModel(tmp_path).is_available()
    text, ok, msg = LocalModel(tmp_path).run("cleanup", "hello there")
    assert not ok and text == "hello there"


def test_local_model_handles_english_cleanup_and_translation_only():
    pick = JustTalkApp._local_task
    english = SimpleNamespace(target_language=None)
    assert pick(SimpleNamespace(target_language="English"), "translate", "म आउँछु", False) == "translate"
    assert pick(SimpleNamespace(target_language="Spanish"), "translate", "hello", False) is None
    assert pick(english, "format", "send the file", False) == "cleanup"
    assert pick(english, "format", "म आउँछु", False) is None  # Nepali-script output stays with the cloud model
    assert pick(english, "format", "send the file", True) is None  # Action Mode stays with the cloud model


def test_english_text_in_translate_mode_is_only_cleaned_up():
    from types import SimpleNamespace
    from just_talk.app.main import JustTalkApp

    intent = SimpleNamespace(target_language="English")
    assert JustTalkApp._local_task(intent, "translate", "push the changes to git", False) == "cleanup"


def test_instructions_the_speaker_read_out_are_not_a_leak():
    from just_talk.ai.local_model import check_output

    src = "ट्रान्सलेट दिस नेपाली डिक्टेसन किप एभ्रि डिटेल्स आउटपुट ओन्ली द ट्रान्सलेसन तिमीले कोड पुस गर्यौ"
    out = "Translate this Nepali dictation, keep every details, output only the translation. Did you push the code?"
    assert check_output("translate", src, out) is None
    # but instructions the speaker never said still count as a leak
    assert check_output("translate", "म भोलि अफिस जान्छु अनि रिपोर्ट पठाउँछु", "Output only: I will go to the office tomorrow.") is not None


def _bare_app():
    import numpy as np
    from types import SimpleNamespace
    from just_talk.app.main import JustTalkApp

    app = object.__new__(JustTalkApp)
    app.config = SimpleNamespace(user_role="", custom_vocabulary="")
    app.learner = SimpleNamespace(known_terms=lambda limit=80: [], known_mixups=lambda limit=30: [])
    return app, np


def _mixed_engines(app):
    class Apple:
        def transcribe(self, piece, language=None, confidences=None):
            if piece.max() > 0.15:
                confidences.append(0.9)
                return "So my name is Sahas and I am from Kathmandu."
            confidences.append(0.3)
            return "Hello Kesha Hur Bouklieva"

    class Kriti:
        def transcribe(self, piece, language=None):
            if piece.max() > 0.15:
                return "सो माइ नेम इज सहस एन्ड आई एम फ्रम काठमाडौँ"
            return "म भोलि अफिस जान्छु" if piece.max() > 0.11 else "हेलो के छ हलखबर भोक लागिरहेको छ"

    app.stt_engine, app.kriti = Apple(), Kriti()
    app.config.voice_isolation_enabled = False


def _nepali_then_english(np, sec=10):
    """Nepali-ish audio, a pause, English-ish audio: one cut at the pause."""
    quiet = np.zeros(8000, np.float32)
    return np.concatenate([np.full(16000 * sec, 0.1, np.float32), quiet, np.full(16000 * sec, 0.2, np.float32)])


def test_mixed_dictation_is_routed_per_stretch_of_speech():
    app, np = _bare_app()
    _mixed_engines(app)
    segments = app._mixed_transcribe(_nepali_then_english(np, sec=5))
    assert segments == [("हेलो के छ हलखबर भोक लागिरहेको छ", "ne"), ("So my name is Sahas and I am from Kathmandu.", "en")]


def test_mixed_stretches_recognized_while_talking_are_not_redone():
    from just_talk.app.main import MIXED_PIECE_SEC
    from just_talk.stt.long_form import EarlyPieces

    app, np = _bare_app()
    _mixed_engines(app)
    audio = _nepali_then_english(np, sec=5)
    calls = []
    piece = app._mixed_piece
    early = EarlyPieces(lambda a: calls.append(len(a)) or piece(a), max_piece_sec=MIXED_PIECE_SEC)
    early.update(audio[: 16000 * 9])  # the Nepali stretch is finished; the English one isn't yet
    assert len(early) == 1 and len(calls) == 1
    segments = app._mixed_transcribe(audio, early)
    assert segments == [("हेलो के छ हलखबर भोक लागिरहेको छ", "ne"), ("So my name is Sahas and I am from Kathmandu.", "en")]
    assert len(calls) == 2  # only the English stretch was left after the user stopped


def test_mixed_live_preview_shows_english_stretches_in_english():
    """While talking, the HUD used to show only Kriti, so English came out in Nepali letters."""
    from just_talk.app.main import MIXED_PIECE_SEC, _MixedEarly
    from just_talk.stt.long_form import EarlyPieces

    app, np = _bare_app()
    _mixed_engines(app)
    quiet = np.zeros(8000, np.float32)
    audio = np.concatenate([np.full(16000 * 5, 0.2, np.float32), quiet, np.full(16000 * 3, 0.1, np.float32)])
    early = _MixedEarly(EarlyPieces(app._mixed_piece, max_piece_sec=MIXED_PIECE_SEC), translate=False)
    early.pieces.update(audio)  # the English stretch is finished; the Nepali one is still being spoken
    shown = app._mixed_preview(early, audio, lambda a: app.kriti.transcribe(a))
    assert shown == "So my name is Sahas and I am from Kathmandu. हेलो के छ हलखबर भोक लागिरहेको छ"


def test_early_pieces_cut_the_same_pieces_as_split_on_pauses():
    import numpy as np
    from just_talk.audio.vad import VoiceActivityDetector
    from just_talk.stt.long_form import EarlyPieces

    rng = np.random.default_rng(0)
    audio = np.concatenate([np.concatenate([rng.normal(0, 0.1, 16000 * n).astype(np.float32), np.zeros(4000, np.float32)])
                            for n in (3, 6, 2, 9, 4, 7)])
    early = EarlyPieces(lambda a: len(a), max_piece_sec=8.0)
    for end in range(16000, len(audio), 8000):  # the recording growing every half second
        early.update(audio[:end])
    spans = [(a, b) for a, b, _ in early.finish(audio)]
    assert [audio[a:b].tolist() for a, b in spans] == [
        c.tolist() for c in VoiceActivityDetector.split_on_pauses(audio, max_chunk_sec=8.0, min_chunk_sec=1.0)
    ]
    early.update(audio)  # after finish, nothing more is added
    assert len(early) == len(spans)


def test_nepali_stretches_are_translated_and_english_ones_cleaned_up():
    app, _ = _bare_app()
    calls = []

    class Local:
        def run(self, task, text, context=""):
            calls.append((task, text))
            return {"translate": "Hello, how are you? I'm hungry.", "cleanup": "So my name is Sahas. I push to git."}[task], True, ""

    app.local_ai = Local()
    text, ok, _ = app._translate_segments(
        [("हेलो के छ हलखबर भोक लागिरहेको छ", "ne"), ("So my name is Sahas", "en"), ("I push to get", "en")]
    )
    assert ok and text == "Hello, how are you? I'm hungry. So my name is Sahas. I push to git."
    assert calls == [("translate", "हेलो के छ हलखबर भोक लागिरहेको छ"), ("cleanup", "So my name is Sahas I push to get")]


def test_one_rejected_run_doesnt_send_the_whole_dictation_out_raw():
    """A 100-word English story lost all its cleanup because one run was rejected."""
    app, _ = _bare_app()

    class Local:
        def run(self, task, text, context=""):
            if task == "translate":
                return text, False, "length doesn't match what was said"
            return "So today I found out.", True, ""

    app.local_ai = Local()
    text, ok, _ = app._translate_segments([("so today i found out", "en"), ("अब यो", "ne")])
    assert ok and text == "So today I found out. अब यो।"
    app.local_ai.run = lambda task, text, context="": (text, False, "rejected")
    assert app._translate_segments([("अब यो", "ne")])[1] is False  # nothing to keep: the caller falls back


def test_long_nepali_is_translated_a_few_stretches_at_a_time():
    """The on-device model drops sentences from 200-word Nepali, so runs are capped in words."""
    app, _ = _bare_app()
    calls = []

    class Local:
        def run(self, task, text, context=""):
            calls.append((task, len(text.split())))
            return "ok.", True, ""

    app.local_ai = Local()
    stretch = " ".join(["शब्द"] * 15)
    text, ok, _ = app._translate_segments([(stretch, "ne")] * 5 + [("So my name is Sahas", "en")])
    assert ok and text == "ok. ok. ok. ok."
    assert calls == [("translate", 30), ("translate", 30), ("translate", 15), ("cleanup", 5)]


def test_runs_translated_while_talking_are_not_translated_again(monkeypatch):
    import sys
    from just_talk.app.main import MIXED_PIECE_SEC, _MixedEarly
    main_mod = sys.modules["just_talk.app.main"]  # just_talk.app.main is also a function name
    from just_talk.stt.long_form import EarlyPieces

    app, np = _bare_app()
    _mixed_engines(app)
    calls = []

    class Local:
        def run(self, task, text, context=""):
            calls.append(task)
            return {"translate": "Hello, how are you? I'm hungry.", "cleanup": "So my name is Sahas."}[task], True, ""

    app.local_ai = Local()
    quiet = np.zeros(8000, np.float32)
    audio = np.concatenate([_nepali_then_english(np, sec=5), quiet, np.full(16000 * 5, 0.12, np.float32)])  # NE, EN, NE

    class Recorder:
        """Recording that grows by a second per poll, then stops."""
        def __init__(self):
            self.n = 0
        @property
        def is_recording(self):
            return self.n * 16000 < len(audio)
        def get_current_audio(self):
            self.n += 1
            return audio[: self.n * 16000]

    app.recorder = Recorder()
    monkeypatch.setattr(main_mod.time, "sleep", lambda s: None)
    early = _MixedEarly(EarlyPieces(app._mixed_piece, max_piece_sec=MIXED_PIECE_SEC), translate=True)
    app._early_mixed_loop(early)
    assert calls == ["translate"]  # the first Nepali run was finished (English followed), so it was done early

    segments = app._mixed_transcribe(audio, early.pieces)
    assert [lang for _, lang in segments] == ["ne", "en", "ne"]
    text, ok, _ = app._translate_segments(segments, early.translated)
    assert ok and text == "Hello, how are you? I'm hungry. So my name is Sahas. Hello, how are you? I'm hungry."
    assert calls == ["translate", "cleanup", "translate"]  # the first run wasn't translated twice


def test_git_is_fixed_only_where_it_can_only_mean_git():
    from just_talk.profile.scripts import fix_known_mishearings

    dev = ["git", "GitHub", "pull request"]
    assert fix_known_mishearings("Then push the changes to get and open a pull request.", dev) == \
        "Then push the changes to git and open a pull request."
    assert fix_known_mishearings("Can you push it to the gate?", dev) == "Can you push it to git?"
    assert fix_known_mishearings("Pull from get hub first.", dev) == "Pull from GitHub first."
    assert fix_known_mishearings("I want to get the file.", dev) == "I want to get the file."
    assert fix_known_mishearings("Get the changes and commit them.", dev) == "Get the changes and commit them."
    assert fix_known_mishearings("Push the changes to get.", []) == "Push the changes to get."  # not a developer


def test_long_english_is_cleaned_up_a_few_stretches_at_a_time():
    """A 96 s English story was one 260-word call; the model cut it short and was rejected."""
    app, _ = _bare_app()
    calls = []

    class Local:
        def run(self, task, text, context=""):
            calls.append((task, len(text.split())))
            return text, True, ""

    app.local_ai = Local()
    stretch = " ".join(["word"] * 20)
    text, ok, _ = app._translate_segments([(stretch, "en")] * 5)
    assert ok and len(text.split()) == 100
    assert calls == [("cleanup", 40), ("cleanup", 40), ("cleanup", 20)]


def test_english_that_apple_was_unsure_of_is_still_english_when_kriti_wrote_english_words():
    """15 Oct English story: Apple at 0.49-0.74 with repeated words, so these went to Kriti and
    the model invented sentences. Kriti's own words (द, एन्ड, इज, no Nepali) say it was English."""
    app, _ = _bare_app()
    english_story = ("Although he said and disappeared in the clouds the next morning", 0.49,
                     "अभोभ ही सेड एन्ड डिसिप्लिन इन टु क्लाउड द नेक्स्ट मर्निङ रोहन")
    nepali_story = ("This bike start got office going", 0.54, "त्यसपछि मैले बाइक स्टार्ट गरेँ र म अफिस गएँ")
    sure_apple = ("The boy who", 0.97, "कुटिर दबाइ")
    segments = app._segments_from([(0, 16000, r) for r in (english_story, nepali_story, sure_apple)])
    assert [lang for _, lang in segments] == ["en", "ne", "en"]


def test_language_words_tell_kriti_english_from_nepali():
    from just_talk.profile.scoring import language_words

    en, ne = language_words("एन्ड द लेक लुक्स लाइक एन वाइज ए")
    assert en >= 0.3 and ne == 0
    en, ne = language_words("छ महिना अगाडि म एउटा ताल गएको थिएँ")
    assert en == 0 and ne > 0


def test_asks_for_list_in_both_languages():
    from just_talk.ai.local_model import asks_for_list

    assert asks_for_list("make a list of the bugs")
    assert asks_for_list("first fix login and second fix logout")
    assert asks_for_list("मलाई एउटा लिस्ट चाहियो")
    assert asks_for_list("पहिलो काम र दोस्रो काम")
    assert not asks_for_list("send the file to the team")
    assert not asks_for_list("first fix login")
    assert not asks_for_list("म भोलि आउँछु")


def test_unasked_lists_are_rejected_for_translate_and_cleanup_only():
    bulleted = "- fix login\n- fix logout"
    for task in ("translate", "cleanup"):
        assert check_output(task, "fix login and fix logout", bulleted) == "made a list nobody asked for"
        assert check_output(task, "make a list: fix login, fix logout", bulleted) is None
    assert check_output("cleanup", "fix login and fix logout", "1. fix login\n2. fix logout") == "made a list nobody asked for"
    assert check_output("edit", "fix login and fix logout", bulleted) is None


def test_a_leading_yes_or_no_is_never_dropped():
    from just_talk.ai.local_model import keep_leading_answer

    assert keep_leading_answer("cleanup", "Yes I think I do", "I think I do.") == "Yes, I think I do."
    assert keep_leading_answer("cleanup", "no we should wait", "We should wait.") == "No, we should wait."
    assert keep_leading_answer("cleanup", "Yes I think I do", "Yes, I think I do.") == "Yes, I think I do."
    assert keep_leading_answer("cleanup", "the yes vote", "The yes vote.") == "The yes vote."
    assert keep_leading_answer("translate", "हो", "Yes.") == "Yes."
