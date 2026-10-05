"""Tests for TextInserter and clipboard preservation."""

from unittest.mock import patch
from just_talk.system.clipboard import ClipboardManager
from just_talk.system.inserter import TextInserter


def test_clipboard_set_get():
    test_str = "Just Talk Unit Test Clipboard"
    assert ClipboardManager.set_text(test_str) is True
    assert ClipboardManager.get_text() == test_str


def test_text_inserter_empty():
    inserter = TextInserter()
    success, status, app = inserter.insert("")
    assert success is True
    assert status == "inserted"


def test_text_inserter_active():
    from just_talk.system.caret_locator import CaretLocator

    inserter = TextInserter()
    test_phrase = "Hello world from Just Talk"

    # Mock keyboard synthesis and active target to test genuine insertion path
    with patch.object(CaretLocator, "_last_has_text_target", True), patch.object(inserter._keyboard, "press"), patch.object(inserter._keyboard, "release"):
        success, status, app = inserter.insert(test_phrase, restore_clipboard=False)
        assert success is True
        assert status == "inserted"
        assert ClipboardManager.get_text() == test_phrase


def test_text_inserter_clipboard_fallback():
    from just_talk.system.caret_locator import CaretLocator

    inserter = TextInserter()
    test_phrase = "Text copied when no active target"

    # Simulate CaretLocator determining there is no active text target (e.g. desktop/Finder)
    with patch.object(CaretLocator, "_last_has_text_target", False):
        success, status, app = inserter.insert(test_phrase, restore_clipboard=False)
        assert success is True
        assert status == "clipboard"
        assert ClipboardManager.get_text() == test_phrase


def test_text_inserter_two_phase_draft_and_polish():
    from just_talk.system.caret_locator import CaretLocator

    inserter = TextInserter()
    ClipboardManager.set_text("Original User Clipboard")
    inserter.capture_active_target()
    assert inserter._original_clipboard == "Original User Clipboard"
    assert inserter._has_active_draft is False

    # 1. Phase 1: Draft emitted with restore_clipboard=False
    with patch.object(CaretLocator, "_last_has_text_target", True), \
         patch.object(inserter, "_synthesize_paste", return_value=True), \
         patch.object(inserter, "undo_last_paste") as mock_undo:
        ok, status, _ = inserter.insert("draft words", restore_clipboard=False, replace_previous=False)
        assert ok is True
        assert status == "inserted"
        assert inserter._has_active_draft is True
        assert mock_undo.call_count == 0

        # 2. Phase 2: In-place polish with replace_previous=True
        ok, status, _ = inserter.insert("Polished words.", restore_clipboard=True, replace_previous=True)
        assert ok is True
        assert status == "inserted"
        assert mock_undo.call_count == 1
        assert inserter._has_active_draft is False


def test_text_inserter_cancel_draft():
    from just_talk.system.caret_locator import CaretLocator

    inserter = TextInserter()
    ClipboardManager.set_text("Initial Clipboard Content")
    inserter.capture_active_target()

    # Emit draft
    with patch.object(CaretLocator, "_last_has_text_target", True), \
         patch.object(inserter, "_synthesize_paste", return_value=True), \
         patch.object(inserter, "undo_last_paste") as mock_undo:
        inserter.insert("some draft", restore_clipboard=False)
        assert inserter._has_active_draft is True

        # Cancel draft
        inserter.cancel_draft()
        assert mock_undo.call_count == 1
        assert inserter._has_active_draft is False
        assert ClipboardManager.get_text() == "Initial Clipboard Content"

