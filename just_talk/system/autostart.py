"""System startup / launch-at-login manager for macOS and Windows."""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path


class AutostartManager:
    """Manages system-level autostart (LaunchAgent on macOS, Startup-folder shortcut on Windows)."""

    MACOS_LABEL = "com.justtalk.desktop"
    WINDOWS_SHORTCUT_NAME = "Just Talk"

    @classmethod
    def get_macos_plist_path(cls) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{cls.MACOS_LABEL}.plist"

    @classmethod
    def get_windows_shortcut_path(cls) -> Path:
        # Same name the installer's "startup" task uses, so both stay in sync.
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return (
            Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            / f"{cls.WINDOWS_SHORTCUT_NAME}.lnk"
        )

    @classmethod
    def _windows_launch_target(cls) -> tuple[str, str]:
        if getattr(sys, "frozen", False):
            return sys.executable, "--minimized"
        # Dev run: pythonw avoids a console window at login
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pythonw) if pythonw.exists() else sys.executable
        return exe, "-m just_talk.app.main --minimized"

    @classmethod
    def _create_windows_shortcut(cls, shortcut: Path) -> bool:
        import subprocess

        target, args = cls._windows_launch_target()
        # Paths go through env vars so quotes/spaces in them can't break the script
        script = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:JT_LNK); "
            "$s.TargetPath = $env:JT_TARGET; $s.Arguments = $env:JT_ARGS; "
            "$s.WorkingDirectory = $env:JT_DIR; $s.Save()"
        )
        env = dict(os.environ, JT_LNK=str(shortcut), JT_TARGET=target, JT_ARGS=args,
                   JT_DIR=str(Path(target).parent))
        try:
            shortcut.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                env=env,
                capture_output=True,
                timeout=15,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return shortcut.exists()
        except Exception as e:
            print(f"[Autostart] Failed to create startup shortcut: {e}", file=sys.stderr)
            return False

    @classmethod
    def _remove_windows_run_value(cls) -> None:
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, "JustTalk")
        except OSError:
            pass

    @classmethod
    def is_autostart_enabled(cls) -> bool:
        """Check if launch at startup is currently configured in the OS."""
        if sys.platform == "darwin":
            return cls.get_macos_plist_path().exists()

        if sys.platform == "win32":
            return cls.get_windows_shortcut_path().exists()

        return False

    @classmethod
    def set_autostart(cls, enabled: bool) -> bool:
        """Enable or disable launching JustTalk when the user logs in."""
        if sys.platform == "darwin":
            plist_path = cls.get_macos_plist_path()
            if not enabled:
                try:
                    if plist_path.exists():
                        plist_path.unlink()
                    return True
                except Exception as e:
                    print(f"[Autostart] Failed to remove LaunchAgent plist: {e}", file=sys.stderr)
                    return False

            # Enable: determine executable path
            app_bundle_bin = Path("/Applications/JustTalk.app/Contents/MacOS/JustTalk")
            if app_bundle_bin.exists():
                args = [str(app_bundle_bin), "--minimized"]
            elif getattr(sys, "frozen", False):
                args = [sys.executable, "--minimized"]
            else:
                args = [sys.executable, "-m", "just_talk.app.main", "--minimized"]

            plist_content = {
                "Label": cls.MACOS_LABEL,
                "ProgramArguments": args,
                "RunAtLoad": True,
                "ProcessType": "Interactive",
            }

            try:
                plist_path.parent.mkdir(parents=True, exist_ok=True)
                with open(plist_path, "wb") as f:
                    plistlib.dump(plist_content, f)
                return True
            except Exception as e:
                print(f"[Autostart] Failed to create LaunchAgent plist: {e}", file=sys.stderr)
                return False

        if sys.platform == "win32":
            # Legacy builds wrote a Run registry value. Unsigned apps writing Run keys
            # get flagged by Defender as persistence and the exe is quarantined, so
            # we now use a Startup-folder shortcut and remove any old Run value.
            cls._remove_windows_run_value()
            shortcut = cls.get_windows_shortcut_path()
            if not enabled:
                try:
                    shortcut.unlink(missing_ok=True)
                    return True
                except Exception as e:
                    print(f"[Autostart] Failed to remove startup shortcut: {e}", file=sys.stderr)
                    return False
            return cls._create_windows_shortcut(shortcut)

        return False
