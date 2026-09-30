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
