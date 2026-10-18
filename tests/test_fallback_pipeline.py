"""Tests for formatting fallback pipeline and log key redaction."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from just_talk.ai.gemini import GeminiFormatter
from just_talk.database.history import HistoryDatabase
from just_talk.security import CredentialManager


def test_fallback_light_local_cleanup():
    """Verify light local cleanup strips fillers and capitalizes."""
    raw = "um uh we need to submit the report today"
    cleaned = GeminiFormatter.light_local_cleanup(raw)
    assert cleaned == "We need to submit the report today."

    raw2 = "like ah this is ready"
    cleaned2 = GeminiFormatter.light_local_cleanup(raw2)
    assert cleaned2 == "This is ready."

    # Verify URLs and domains never receive trailing periods or improper capitalization
    url_raw = "github.com"
    assert GeminiFormatter.light_local_cleanup(url_raw) == "github.com"

    url_raw_dot = "github.com."
    assert GeminiFormatter.light_local_cleanup(url_raw_dot) == "github.com"

    sentence_url = "Please visit github.com."
    assert GeminiFormatter.light_local_cleanup(sentence_url) == "Please visit github.com"


def test_light_cleanup_ends_nepali_with_a_danda():
    assert GeminiFormatter.light_local_cleanup("मेरो भाइ यहाँ बसिरहेको छ।") == "मेरो भाइ यहाँ बसिरहेको छ।"
    assert GeminiFormatter.light_local_cleanup("२० वटा शब्द हो") == "२० वटा शब्द हो।"


def test_formatting_fallback_inserts_raw_and_saves_history():
    """When Gemini formatting fails, fallback text is used and history records 'inserted (offline)'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_history.db"
        db = HistoryDatabase(db_path=db_path)

        formatter = GeminiFormatter(api_key="mock_key", timeout=0.1)

        # Simulate Gemini connection failure
        with patch("httpx.Client.post", side_effect=Exception("API Error")):
            raw_speech = "um we should meet at five pm"
            cleaned, success, msg = formatter.format_text(raw_speech)

            assert success is False
            assert cleaned == "We should meet at five pm."
            # Verify status and history record
            status_to_save = "inserted (offline)"
            record = db.add(
                raw_transcription=raw_speech,
                processed_text=cleaned,
                action="dictation",
                application="Terminal",
                status=status_to_save,
                duration_ms=120,
            )

            # Ensure raw transcription was preserved unaltered in DB
            assert record.raw_transcription == raw_speech
            assert record.processed_text == "We should meet at five pm."
            assert record.status == "inserted (offline)"

            # Verify it's retrieved in recent items
            recent = db.get_recent(limit=1)
            assert len(recent) == 1
            assert recent[0].raw_transcription == raw_speech
            assert recent[0].status == "inserted (offline)"


def test_key_redaction_in_logs_and_errors():
    """Verify that credentials in exception messages or log strings are redacted."""
    gemini_key = "AQ.MockTestKey0123456789abcdefghij"
    google_key = "AIzaSyD-mockTestKey9876543210ABCDEFGH"

    log_entry_1 = f"Failed to post to https://generativelanguage.googleapis.com with key={gemini_key}"
    log_entry_2 = f"HTTP 401 Unauthorized for client key: {google_key} in request"

    redacted_1 = CredentialManager.redact(log_entry_1)
    redacted_2 = CredentialManager.redact(log_entry_2)

    assert gemini_key not in redacted_1
    assert "[REDACTED_API_KEY]" in redacted_1

    assert google_key not in redacted_2
    assert "[REDACTED_API_KEY]" in redacted_2


def test_translation_pipeline_routing():
    """Verify that speech_mode='translate' routes STT to transcribe and uses translation prompt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_history.db"
        db = HistoryDatabase(db_path=db_path)

        with patch("just_talk.app.main.AppConfig.load") as mock_load, \
             patch("just_talk.app.main.HistoryDatabase", return_value=db), \
             patch("just_talk.app.main.PermissionsManager"), \
             patch("just_talk.app.main.VoiceActivityDetector"), \
             patch("just_talk.app.main.AudioRecorder"), \
             patch("just_talk.app.main.ModelManager"), \
             patch("just_talk.app.main.WhisperSTTEngine") as mock_whisper_cls, \
             patch("just_talk.app.main.MultiProviderFormatter") as mock_formatter_cls, \
             patch("just_talk.app.main.TextInserter") as mock_inserter_cls, \
             patch("just_talk.app.main.NoiseFilter"), \
             patch("just_talk.app.main.SpeakerRecognizer"):

            from just_talk.config import AppConfig
            from just_talk.app.main import JustTalkApp

            cfg = AppConfig(stt_provider="whisper", speech_mode="translate", gemini_enabled=True, offline_mode=False)
            mock_load.return_value = cfg

            app = JustTalkApp()
            app.config = cfg

            mock_stt = mock_whisper_cls.return_value
            mock_stt.transcribe.return_value = "yo meeting ma we will discuss project code"

            mock_gemini = mock_formatter_cls.return_value
            mock_gemini.format_text.return_value = ("In this meeting we will discuss the project code.", True, "")

            mock_inserter = mock_inserter_cls.return_value
            mock_inserter.get_active_app_name.return_value = "VS Code"
            mock_inserter.insert.return_value = (True, "inserted", "VS Code")

            import numpy as np
            sample_audio = np.zeros(16000, dtype=np.float32)

            with patch("just_talk.app.main.CaretLocator.has_active_text_target", return_value=True):
                app._process_audio_pipeline(sample_audio, is_action_mode=False)

            # 1. Verify Whisper was called with task="transcribe" (not "translate" which butchers code-switching)
            mock_stt.transcribe.assert_called()
            call_kwargs = mock_stt.transcribe.call_args.kwargs
            assert call_kwargs.get("task") == "transcribe"
            assert "Namaste" in call_kwargs.get("initial_prompt", "")

            # 2. Verify Gemini received the translation prompt
            mock_gemini.format_text.assert_called()
            gemini_kwargs = mock_gemini.format_text.call_args.kwargs
            instruction = gemini_kwargs.get("custom_system_instruction", "")
            assert "CODE-SWITCHING" in instruction
            assert "Nepali" in instruction

            # 3. Verify final insertion was the translated English text
            mock_inserter.insert.assert_called_with(
                "In this meeting we will discuss the project code.",
                restore_clipboard=True,
            )

            # 4. Verify DB entry was saved with action="translate"
            recent = db.get_recent(limit=1)
            assert len(recent) == 1
            assert recent[0].action == "translate"
            assert recent[0].raw_transcription == "yo meeting ma we will discuss project code"
            assert recent[0].processed_text == "In this meeting we will discuss the project code."


def test_two_phase_pipeline_emission_and_polish():
    """Verify that two-phase emission inserts raw draft instantly and polishes in-place."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_history.db"
        db = HistoryDatabase(db_path=db_path)

        with patch("just_talk.app.main.AppConfig.load") as mock_load, \
             patch("just_talk.app.main.HistoryDatabase", return_value=db), \
             patch("just_talk.app.main.PermissionsManager"), \
             patch("just_talk.app.main.VoiceActivityDetector"), \
             patch("just_talk.app.main.AudioRecorder"), \
             patch("just_talk.app.main.ModelManager"), \
             patch("just_talk.app.main.WhisperSTTEngine") as mock_whisper_cls, \
             patch("just_talk.app.main.MultiProviderFormatter") as mock_formatter_cls, \
             patch("just_talk.app.main.TextInserter") as mock_inserter_cls, \
             patch("just_talk.app.main.NoiseFilter"), \
             patch("just_talk.app.main.SpeakerRecognizer"):

            from just_talk.config import AppConfig
            from just_talk.app.main import JustTalkApp

            cfg = AppConfig(stt_provider="whisper", two_phase_emission=True, gemini_enabled=True, offline_mode=False)
            mock_load.return_value = cfg

            app = JustTalkApp()
            app.config = cfg

            mock_stt = mock_whisper_cls.return_value
            mock_stt.transcribe.return_value = "we are fixing this bug today"

            mock_gemini = mock_formatter_cls.return_value
            mock_gemini.format_text.return_value = ("We are definitely fixing this bug today!", True, "")

            mock_inserter = mock_inserter_cls.return_value
            mock_inserter.get_active_app_name.return_value = "TextEdit"
            mock_inserter.insert.return_value = (True, "inserted", "TextEdit")

            import numpy as np
            sample_audio = np.zeros(16000, dtype=np.float32)

            with patch("just_talk.app.main.CaretLocator.has_active_text_target", return_value=True):
                app._process_audio_pipeline(sample_audio, is_action_mode=False)

            # Verify Two-Phase calls on TextInserter:
            assert mock_inserter.insert.call_count == 2

            # Call 1 (Phase 1 Draft): Raw text inserted immediately without restoring clipboard
            call1 = mock_inserter.insert.call_args_list[0]
            assert "we are fixing this bug today" in call1.args[0].lower()
            assert call1.kwargs.get("restore_clipboard") is False
            assert call1.kwargs.get("replace_previous") is False

            # Call 2 (Phase 2 In-Place Polish): Polished text replaces draft
            call2 = mock_inserter.insert.call_args_list[1]
            assert call2.args[0] == "We are definitely fixing this bug today!"
            assert call2.kwargs.get("restore_clipboard") is True
            assert call2.kwargs.get("replace_previous") is True



def _run_pipeline(cfg, heard, app_name="TextEdit", draft_ok=True, local_reply=None):
    """Run one dictation through the real pipeline with the engines faked; returns (inserter, local runs)."""
    from contextlib import ExitStack
    import types

    import numpy as np

    with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
        db = HistoryDatabase(db_path=Path(tmpdir) / "h.db")
        p = lambda name, **kw: stack.enter_context(patch(f"just_talk.app.main.{name}", **kw))  # noqa: E731
        p("AppConfig.load", return_value=cfg)
        p("HistoryDatabase", return_value=db)
        for name in ("PermissionsManager", "VoiceActivityDetector", "AudioRecorder", "ModelManager",
                     "NoiseFilter", "SpeakerRecognizer"):
            p(name)
        stt = p("WhisperSTTEngine").return_value
        stt.transcribe.return_value = heard
        p("MultiProviderFormatter").return_value.format_text.return_value = ("", False, "AI is off")
        inserter = p("TextInserter").return_value
        inserter.get_active_app_name.return_value = app_name
        inserter.insert.return_value = (True, "inserted", app_name)
        inserter.draft_can_be_undone.return_value = draft_ok
        p("CaretLocator.has_active_text_target", return_value=True)

        from just_talk.app.main import JustTalkApp

        app = JustTalkApp()
        app.config = cfg
        runs = []
        app.local_ai = types.SimpleNamespace(
            is_available=lambda: True,
            run=lambda task, text, ctx="": runs.append(task) or (local_reply or text, True, ""),
        )
        app._process_audio_pipeline(np.zeros(16000, dtype=np.float32), is_action_mode=False)
        return inserter, runs


def test_no_draft_where_undo_cant_take_it_back():
    """In a terminal the draft would stay and the polished text would land right after it."""
    from just_talk.config import AppConfig

    cfg = AppConfig(stt_provider="whisper", two_phase_emission=True, gemini_enabled=False, local_ai=True)
    inserter, runs = _run_pipeline(cfg, "we are fixing this bug today", app_name="Antigravity IDE",
                                   draft_ok=False, local_reply="We are fixing this bug today!")
    assert runs == ["cleanup"]
    assert [c.args[0] for c in inserter.insert.call_args_list] == ["We are fixing this bug today!"]


def test_on_device_ai_stays_off_when_switched_off():
    from just_talk.config import AppConfig

    cfg = AppConfig(stt_provider="whisper", two_phase_emission=False, gemini_enabled=False, local_ai=False)
    inserter, runs = _run_pipeline(cfg, "we are fixing this bug today", local_reply="Rewritten!")
    assert runs == []
    assert inserter.insert.call_args.args[0] == "We are fixing this bug today."


def test_ai_dashes_become_plain_punctuation():
    from just_talk.ai.gemini import without_ai_dashes

    assert without_ai_dashes("The plan—if it works—saves time.") == "The plan, if it works, saves time."
    assert without_ai_dashes("It is fast — and cheap.") == "It is fast, and cheap."
    assert without_ai_dashes("— first\n— second") == "- first\n- second"
    assert without_ai_dashes("Pages 10–20 and 10 – 20.") == "Pages 10–20 and 10 – 20."
    assert without_ai_dashes("A plain - hyphen stays.") == "A plain - hyphen stays."


def test_dictation_never_types_an_em_dash():
    from just_talk.config import AppConfig

    cfg = AppConfig(stt_provider="whisper", two_phase_emission=False, gemini_enabled=False, local_ai=True)
    inserter, _ = _run_pipeline(cfg, "it is fast and cheap", local_reply="It is fast — and cheap.")
    assert inserter.insert.call_args.args[0] == "It is fast, and cheap."


def test_hesitation_sounds_are_removed():
    from just_talk.ai.gemini import without_fillers

    assert without_fillers("Umm so I was thinking ahhh we ship friday") == "So I was thinking we ship friday"
    assert without_fillers("I was, um, thinking hmm about it.") == "I was, thinking about it."
    assert without_fillers("Oh, that's great") == "Oh, that's great"
    assert without_fillers("5 mm screws") == "5 mm screws"
    assert without_fillers("go to the ER now") == "go to the ER now"
    assert without_fillers("buy AAA batteries, I'm OOO, use MM/DD") == "buy AAA batteries, I'm OOO, use MM/DD"
    assert without_fillers("Aaah I forgot") == "I forgot"
    assert without_fillers("it was er fine") == "it was fine"
    assert without_fillers("उम्म म भोलि अहह आउँछु") == "म भोलि आउँछु"
    assert without_fillers("उम् बाबा अस्पताल जानुभएको छ") == "बाबा अस्पताल जानुभएको छ"  # how Kriti wrote it
    assert without_fillers("- eggs umm\n- milk") == "- eggs\n- milk"


def test_a_spoken_web_address_is_typed_as_is():
    """"youtube.com" came out as "YouTube.com." which the address bar can't open."""
    from just_talk.config import AppConfig

    cfg = AppConfig(stt_provider="whisper", two_phase_emission=False, gemini_enabled=False, local_ai=True)
    inserter, runs = _run_pipeline(cfg, "youtube.com", local_reply="YouTube.com.")
    assert runs == [] and inserter.insert.call_args.args[0] == "youtube.com"
    inserter, runs = _run_pipeline(cfg, "the site is youtube.com", local_reply="The site is YouTube.com.")
    assert runs == ["cleanup"]  # a sentence that only mentions an address is still cleaned up


def test_text_filters_leave_real_words_and_code_alone():
    """From a review of today's changes: these used to be changed."""
    from just_talk.ai.gemini import is_web_address, without_ai_dashes, without_fillers

    assert without_fillers("    x = 1\n    y  = 2") == "    x = 1\n    y  = 2"  # code indentation
    assert without_fillers("  - sub\n- eggs umm\n- milk") == "  - sub\n- eggs\n- milk"
    assert without_fillers("she said uh-huh") == "she said uh-huh"
    assert without_fillers("UM students meet") == "UM students meet"
    assert without_ai_dashes("Open Mon–Fri, A–Z") == "Open Mon–Fri, A–Z"
    assert without_ai_dashes("Note: — check this") == "Note: check this"
    for word in ("Node.js", "U.S.", "i.e.", "3.5", "v2.3", "Mr.Smith"):
        assert not is_web_address(word), word
    for address in ("youtube.com", "github.com/sahas", "daraz.com.np", "hello@gmail.com", "https://x.y/z"):
        assert is_web_address(address), address


def test_ai_text_filters_skip_code():
    """A variable called "um" in Python must survive."""
    from just_talk.config import AppConfig

    cfg = AppConfig(stt_provider="whisper", two_phase_emission=False, gemini_enabled=False, local_ai=True)
    with patch("just_talk.app.main.detect_context", return_value=type("C", (), {"context": "python", "app_name": "PyCharm", "recommended_nepali_mode": "english", "file_ext": ".py"})()):
        inserter, _ = _run_pipeline(cfg, "um equals five", local_reply="um = 5")
    assert inserter.insert.call_args.args[0] == "um = 5"
