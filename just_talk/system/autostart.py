"""System startup / launch-at-login manager for macOS and Windows."""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path


class AutostartManager:
    """Manages system-level autostart (LaunchAgent on macOS, Run key on Windows)."""

    MACOS_LABEL = "com.justtalk.desktop"

    @classmethod
    def get_macos_plist_path(cls) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{cls.MACOS_LABEL}.plist"

    @classmethod
    def is_autostart_enabled(cls) -> bool:
        """Check if launch at startup is currently configured in the OS."""
        if sys.platform == "darwin":
            return cls.get_macos_plist_path().exists()

        if sys.platform == "win32":
            try:
                import winreg

                try:
                    key = winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Run",
                        0,
                        winreg.KEY_READ,
                    )
                except FileNotFoundError:
                    return False

                try:
                    val, _ = winreg.QueryValueEx(key, "JustTalk")
                    return bool(val)
                except FileNotFoundError:
                    return False
                finally:
                    winreg.CloseKey(key)
            except Exception:
                return False

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
            try:
                import winreg

                key = winreg.CreateKeyEx(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0,
                    winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
                )
                try:
                    if enabled:
                        exe_path = sys.executable
                        cmd = f'"{exe_path}" --minimized'
                        winreg.SetValueEx(key, "JustTalk", 0, winreg.REG_SZ, cmd)
                    else:
                        try:
                            winreg.DeleteValue(key, "JustTalk")
                        except FileNotFoundError:
                            pass
                    return True
                finally:
                    winreg.CloseKey(key)
            except Exception as e:
                print(f"[Autostart] Windows registry update failed: {e}", file=sys.stderr)
                return False

        return False
