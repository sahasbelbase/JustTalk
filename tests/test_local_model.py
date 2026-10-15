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
            return "सो माइ नेम इज सहस एन्ड आई एम फ्रम काठमाडौँ" if piece.max() > 0.15 else "हेलो के छ हलखबर भोक लागिरहेको छ"

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
