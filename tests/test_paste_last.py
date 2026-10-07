"""Paste last dictation: Ctrl+Cmd+V (macOS) / Win+Alt+V (Windows) re-types the latest dictation."""

import sys
import types

from pynput import keyboard

from just_talk.shortcuts.fallback_hook import PynputHotkeyMonitor
from just_talk.shortcuts.mac_hook import MacHotkeyMonitor


# ── Controller ─────────────────────────────────────────────────────────────

class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def _fake_app(history_texts):
    from just_talk.app.main import JustTalkApp

    inserted, captured = [], []
    app = types.SimpleNamespace(
        bridge=types.SimpleNamespace(state_inserted=_Signal(), state_copied=_Signal(), state_error=_Signal()),
        config=types.SimpleNamespace(restore_clipboard=True),
        db=types.SimpleNamespace(
            get_recent=lambda limit=1: [types.SimpleNamespace(processed_text=t) for t in history_texts[:limit]]
        ),
        inserter=types.SimpleNamespace(
            wait_for_modifiers_released=lambda: None,
            capture_active_target=lambda: captured.append(True),
            insert=lambda text, restore_clipboard=True: inserted.append(text) or (True, "inserted", "Notes"),
        ),
    )
    for name in ("last_dictation_text", "_paste_last_worker", "copy_last_dictation"):
        setattr(app, name, types.MethodType(getattr(JustTalkApp, name), app))
    return app, inserted, captured


def test_paste_last_types_most_recent_dictation_into_focused_app():
    app, inserted, captured = _fake_app(["Newest dictation.", "Older one."])
    app._paste_last_worker()
    assert inserted == ["Newest dictation."]
    assert captured, "must re-capture the app focused now, not the one from the last dictation"
    assert app.bridge.state_inserted.calls


def test_paste_last_with_empty_history_shows_message():
    app, inserted, _ = _fake_app([])
    app._paste_last_worker()
    assert inserted == []
    assert app.bridge.state_error.calls == [("Nothing to paste yet",)]


def test_copy_last_puts_dictation_on_clipboard():
    from just_talk.system.clipboard import ClipboardManager

    app, _, _ = _fake_app(["Copy me."])
    app.copy_last_dictation()
    assert ClipboardManager.get_text() == "Copy me."
    assert app.bridge.state_copied.calls


def test_paste_last_ignored_while_recording(monkeypatch):
    from just_talk.app.main import JustTalkApp

    started = []
    monkeypatch.setattr("threading.Thread.start", lambda self: started.append(True))
    app = types.SimpleNamespace(recorder=types.SimpleNamespace(is_recording=True), _paste_last_worker=lambda: None)
    JustTalkApp.paste_last_dictation(app)
    assert started == []


# ── Windows hotkey (pynput) ────────────────────────────────────────────────

def _monitor(events):
    return PynputHotkeyMonitor(
        trigger_key="right_alt",
        action_key="right_alt_shift",
        push_to_talk=True,
        on_start_recording=lambda action: events.append(("start", action)),
        on_stop_recording=lambda: events.append(("stop",)),
        on_cancel_recording=lambda: events.append(("cancel",)),
        on_paste_last=lambda: events.append(("paste_last",)),
    )


def test_windows_win_alt_v_triggers_paste_last(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    events = []
    m = _monitor(events)
    m._on_press(keyboard.Key.cmd)
    m._on_press(keyboard.Key.alt_l)
    m._on_press(keyboard.KeyCode.from_vk(0x56))
    assert events == [("paste_last",)]


def test_windows_paste_last_with_right_alt_cancels_accidental_recording(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    events = []
    m = _monitor(events)
    m._on_press(keyboard.Key.cmd)
    m._on_press(keyboard.Key.alt_r)  # Right Alt is also the dictation key
    m._on_press(keyboard.KeyCode.from_vk(0x56))
    assert events == [("start", False), ("cancel",), ("paste_last",)]


def test_windows_plain_v_and_auto_repeat_do_not_trigger(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    events = []
    m = _monitor(events)
    m._on_press(keyboard.KeyCode.from_vk(0x56))
    assert events == []

    m._on_press(keyboard.Key.cmd)
    m._on_press(keyboard.Key.alt_l)
    m._on_press(keyboard.KeyCode.from_vk(0x56))
    m._on_press(keyboard.KeyCode.from_vk(0x56))  # held key auto-repeat
    assert events == [("paste_last",)]


# ── macOS hotkey ───────────────────────────────────────────────────────────

def _mac_monitor(events):
    return MacHotkeyMonitor(
        on_start_recording=lambda action: events.append(("start", action)),
        on_stop_recording=lambda: events.append(("stop",)),
        on_cancel_recording=lambda: events.append(("cancel",)),
        on_paste_last=lambda: events.append(("paste_last",)),
    )


def test_mac_combo_requires_ctrl_and_cmd():
    m = _mac_monitor([])
    assert m._is_paste_last_combo(ctrl_down=True, cmd_down=True)
    assert not m._is_paste_last_combo(ctrl_down=False, cmd_down=True)  # plain Cmd+V is a normal paste
    assert not m._is_paste_last_combo(ctrl_down=True, cmd_down=False)


def test_mac_paste_last_fires_once_when_both_monitors_see_the_key():
    events = []
    m = _mac_monitor(events)
    m._fire_paste_last()  # NSEvent monitor
    m._fire_paste_last()  # Quartz tap, same key press
    assert events == [("paste_last",)]


def test_mac_paste_last_disabled_without_callback():
    m = MacHotkeyMonitor(on_start_recording=lambda a: None, on_stop_recording=lambda: None)
    assert not m._is_paste_last_combo(ctrl_down=True, cmd_down=True)
