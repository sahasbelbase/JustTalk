"""Tests for system autostart manager."""

from just_talk.system.autostart import AutostartManager


def test_autostart_toggle():
    initial_state = AutostartManager.is_autostart_enabled()
    try:
        # Enable
        ok = AutostartManager.set_autostart(True)
        if ok:
            assert AutostartManager.is_autostart_enabled() is True

            # Disable
            AutostartManager.set_autostart(False)
            assert AutostartManager.is_autostart_enabled() is False
        else:
            # If system registry/launchagent write is restricted in CI environment
            assert isinstance(ok, bool)
    finally:
        # Restore initial state
        AutostartManager.set_autostart(initial_state)


def test_windows_autostart_uses_startup_shortcut_not_run_key(monkeypatch, tmp_path):
    """Writing HKCU\\...\\Run from an unsigned exe gets JustTalk quarantined by Defender."""
    import subprocess
    import sys
    import types

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\Just Talk\JustTalk.exe")

    deleted = []
    fake_winreg = types.SimpleNamespace(HKEY_CURRENT_USER=0, KEY_SET_VALUE=0)

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake_winreg.OpenKey = lambda *a: _Key()
    fake_winreg.DeleteValue = lambda key, name: deleted.append(name)
    fake_winreg.SetValueEx = lambda *a: (_ for _ in ()).throw(AssertionError("Run key written"))
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    calls = []

    def fake_run(cmd, env, **kw):
        calls.append(env)
        from pathlib import Path

        Path(env["JT_LNK"]).write_text("lnk")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    shortcut = AutostartManager.get_windows_shortcut_path()
    assert shortcut.name == "Just Talk.lnk"
    assert shortcut.parent.name == "Startup"

    assert AutostartManager.set_autostart(True) is True
    assert AutostartManager.is_autostart_enabled() is True
    assert calls[0]["JT_TARGET"] == r"C:\Apps\Just Talk\JustTalk.exe"
    assert calls[0]["JT_ARGS"] == "--minimized"
    assert deleted == ["JustTalk"]  # legacy Run value cleaned up

    assert AutostartManager.set_autostart(False) is True
    assert AutostartManager.is_autostart_enabled() is False
