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


def test_mixed_dictation_is_routed_per_stretch_of_speech(monkeypatch):
    from just_talk.audio.vad import VoiceActivityDetector

    app, np = _bare_app()
    nepali_piece, english_piece = np.full(16000, 0.1, np.float32), np.full(16000, 0.2, np.float32)
    monkeypatch.setattr(VoiceActivityDetector, "split_on_pauses", classmethod(lambda cls, a, **kw: [nepali_piece, english_piece]))

    class Apple:
        def transcribe(self, piece, language=None, confidences=None):
            if piece[0] > 0.15:
                confidences.append(0.9)
                return "So my name is Sahas and I am from Kathmandu."
            confidences.append(0.3)
            return "Hello Kesha Hur Bouklieva"

    class Kriti:
        def transcribe(self, piece, language=None):
            return "सो माइ नेम इज सहस एन्ड आई एम फ्रम काठमाडौँ" if piece[0] > 0.15 else "हेलो के छ हलखबर भोक लागिरहेको छ"

    app.stt_engine, app.kriti = Apple(), Kriti()
    segments = app._mixed_transcribe(np.zeros(32000, np.float32))
    assert segments == [("हेलो के छ हलखबर भोक लागिरहेको छ", "ne"), ("So my name is Sahas and I am from Kathmandu.", "en")]


def test_only_nepali_stretches_are_translated():
    app, _ = _bare_app()
    calls = []

    class Local:
        def run(self, task, text, context=""):
            calls.append(text)
            return "Hello, how are you? I'm hungry.", True, ""

    app.local_ai = Local()
    text, ok, _ = app._translate_segments([("हेलो के छ हलखबर भोक लागिरहेको छ", "ne"), ("So my name is Sahas.", "en")])
    assert ok and text == "Hello, how are you? I'm hungry. So my name is Sahas."
    assert calls == ["हेलो के छ हलखबर भोक लागिरहेको छ"]
