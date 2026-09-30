"""OS permission verification and prompt dialogs (macOS Accessibility & Microphone)."""

from __future__ import annotations

import sys
from typing import Tuple


class PermissionsManager:
    """Verifies and prompts for necessary operating system permissions."""

    @staticmethod
    def check_accessibility(prompt_if_needed: bool = False) -> bool:
        """
        Check if application has macOS Accessibility permissions.
        On Windows / Linux, returns True.
        """
        if sys.platform != "darwin":
            return True

        try:
            from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

            # Only prompt if explicitly requested (e.g. from Settings button)
            options = {kAXTrustedCheckOptionPrompt: prompt_if_needed}
            trusted = AXIsProcessTrustedWithOptions(options)
            return bool(trusted)
        except Exception:
            # Fallback if pyobjc is not loaded
            return True

    @staticmethod
    def request_accessibility() -> bool:
        """Trigger native macOS Accessibility prompt dialog."""
        return PermissionsManager.check_accessibility(prompt_if_needed=True)

    @staticmethod
    def open_accessibility_settings() -> None:
        """Open macOS System Settings directly to Privacy & Security > Accessibility."""
        if sys.platform == "darwin":
            import subprocess

            PermissionsManager.request_accessibility()
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
                check=False,
            )

    @staticmethod
    def check_input_monitoring() -> bool:
        """
        Check if application has macOS Input Monitoring permissions.
        Uses Quartz CGPreflightListenEventAccess and IOHIDCheckAccess as fallback.
        On Windows / Linux, returns True.
        """
        if sys.platform != "darwin":
            return True

        try:
            import Quartz
            if hasattr(Quartz, "CGPreflightListenEventAccess"):
                return bool(Quartz.CGPreflightListenEventAccess())
        except Exception:
            pass

        try:
            import ctypes
            import ctypes.util

            iokit_path = ctypes.util.find_library("IOKit")
            if iokit_path:
                iokit = ctypes.cdll.LoadLibrary(iokit_path)
                check_access = iokit.IOHIDCheckAccess
                check_access.restype = ctypes.c_bool
                check_access.argtypes = [ctypes.c_uint32]
                return bool(check_access(1))  # 1 = kIOHIDRequestTypeListenEvent
        except Exception:
            pass

        return True

    @staticmethod
    def request_input_monitoring() -> bool:
        """Trigger native macOS Input Monitoring prompt or deep link to System Settings."""
        if sys.platform != "darwin":
            return True

        try:
            import Quartz
            if hasattr(Quartz, "CGRequestListenEventAccess"):
                Quartz.CGRequestListenEventAccess()
        except Exception:
            pass

        try:
            import ctypes
            import ctypes.util

            iokit_path = ctypes.util.find_library("IOKit")
            if iokit_path:
                iokit = ctypes.cdll.LoadLibrary(iokit_path)
                req_access = iokit.IOHIDRequestAccess
                req_access.restype = ctypes.c_bool
                req_access.argtypes = [ctypes.c_uint32]
                req_access(1)
        except Exception:
            pass

        return PermissionsManager.check_input_monitoring()

    @staticmethod
    def open_input_monitoring_settings() -> None:
        """Open macOS System Settings directly to Privacy & Security > Input Monitoring."""
        if sys.platform == "darwin":
            import subprocess

            PermissionsManager.request_input_monitoring()
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"],
                check=False,
            )

    @staticmethod
    def open_keyboard_settings() -> None:
        """Open macOS System Settings to Keyboard (for configuring Globe/Fn key)."""
        if sys.platform == "darwin":
            import subprocess

            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.keyboard"],
                check=False,
            )

    @staticmethod
    def is_fn_emoji_disabled() -> bool:
        """
        Check if macOS Globe/Fn key is set to 'Do Nothing' (AppleFnUsageType = 0),
        preventing it from opening the macOS Emoji & Symbols palette.
        """
        if sys.platform != "darwin":
            return True

        import subprocess

        try:
            res = subprocess.run(
                ["defaults", "read", "com.apple.HIToolbox", "AppleFnUsageType"],
                capture_output=True,
                text=True,
                check=False,
            )
            # "0" means Do Nothing; "2" (or absent) means Show Emoji & Symbols
            return res.returncode == 0 and res.stdout.strip() == "0"
        except Exception:
            return False

    @staticmethod
    def disable_fn_emoji_popup() -> bool:
        """
        Set macOS Globe/Fn key behavior to 'Do Nothing' (AppleFnUsageType = 0).
        This stops macOS from popping up the Emoji & Symbols window when pressing Fn.
        """
        if sys.platform != "darwin":
            return True

        import subprocess

        try:
            res = subprocess.run(
                ["defaults", "write", "com.apple.HIToolbox", "AppleFnUsageType", "-int", "0"],
                capture_output=True,
                check=False,
            )
            return res.returncode == 0
        except Exception as e:
            print(f"[PermissionsManager] Failed to update AppleFnUsageType: {e}", file=sys.stderr)
            return False

    @staticmethod
    def enable_fn_emoji_popup() -> bool:
        """Restore macOS default Globe/Fn key behavior to 'Show Emoji & Symbols' (2)."""
        if sys.platform != "darwin":
            return True

        import subprocess

        try:
            res = subprocess.run(
                ["defaults", "write", "com.apple.HIToolbox", "AppleFnUsageType", "-int", "2"],
                capture_output=True,
                check=False,
            )
            return res.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _get_av_capture():
        """Resolve AVCaptureDevice and AVMediaTypeAudio safely."""
        try:
            from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
            return AVCaptureDevice, AVMediaTypeAudio
        except Exception:
            pass

        try:
            import objc
            from Foundation import NSBundle

            bundle = NSBundle.bundleWithPath_("/System/Library/Frameworks/AVFoundation.framework")
            if bundle:
                bundle.load()
            AVCaptureDevice = objc.lookUpClass("AVCaptureDevice")
            return AVCaptureDevice, "soun"
        except Exception:
            return None, None

    @staticmethod
    def request_microphone() -> None:
        """Request microphone access or open Privacy & Security > Microphone if blocked."""
        if sys.platform == "darwin":
            import subprocess

            dev_class, media_audio = PermissionsManager._get_av_capture()
            if dev_class and media_audio:
                try:
                    status = dev_class.authorizationStatusForMediaType_(media_audio)
                    if status == 0:  # NotDetermined: trigger macOS native prompt dialog
                        dev_class.requestAccessForMediaType_completionHandler_(
                            media_audio, lambda granted: None
                        )
                        return
                except Exception:
                    pass

            # If denied or framework unavailable, direct user to System Settings
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"],
                check=False,
            )
        elif sys.platform == "win32":
            import os
            os.system("start ms-settings:privacy-microphone")

    @staticmethod
    def check_microphone() -> Tuple[bool, str]:
        """
        Verify microphone access.
        On macOS, queries AVCaptureDevice authorization status.
        On Windows, verifies that active audio input devices are detected.
        Returns:
            Tuple[is_authorized: bool, status_message: str]
        """
        if sys.platform == "win32":
            try:
                import sounddevice as sd
                devices = sd.query_devices()
                input_devs = [d for d in devices if d.get("max_input_channels", 0) > 0]
                if not input_devs:
                    return False, "No active microphone detected. Check Windows Sound settings."
                return True, "Microphone ready (Windows manages access automatically in Privacy Settings)."
            except Exception:
                return True, "Microphone access allowed."

        if sys.platform != "darwin":
            return True, "Microphone access allowed."

        dev_class, media_audio = PermissionsManager._get_av_capture()
        if not dev_class or not media_audio:
            return True, "Microphone status undetermined."

        try:
            # 0=NotDetermined, 1=Restricted, 2=Denied, 3=Authorized
            status = dev_class.authorizationStatusForMediaType_(media_audio)
            if status == 3:  # Authorized
                return True, "Microphone authorized."
            elif status == 2:  # Denied
                return False, "Microphone access denied in System Settings > Privacy & Security > Microphone."
            elif status == 1:  # Restricted
                return False, "Microphone access is restricted by system policy."
            elif status == 0:  # NotDetermined
                dev_class.requestAccessForMediaType_completionHandler_(
                    media_audio, lambda granted: None
                )
                return False, "Microphone permission requested. Please click Allow on the macOS dialog."
        except Exception as e:
            print(f"[PermissionsManager] Microphone check error: {e}", file=sys.stderr)

        return True, "Microphone status verified."

    @staticmethod
    def check_all_permissions() -> dict[str, bool]:
        """Return boolean status dictionary of all required OS permissions."""
        mic_ok, _ = PermissionsManager.check_microphone()
        return {
            "accessibility": PermissionsManager.check_accessibility(prompt_if_needed=False),
            "input_monitoring": PermissionsManager.check_input_monitoring(),
            "microphone": mic_ok,
            "fn_emoji_disabled": PermissionsManager.is_fn_emoji_disabled(),
        }

    @staticmethod
    def all_permissions_granted() -> bool:
        """Return True if all critical permissions (Accessibility, Input Monitoring, Microphone) are granted."""
        p = PermissionsManager.check_all_permissions()
        return bool(p["accessibility"] and p["input_monitoring"] and p["microphone"])

    @staticmethod
    def ensure_healthy_input_volume(min_level: int = 60, target_level: int = 85) -> None:
        """Ensure macOS input volume is not muted or stuck at near-silent levels."""
        if sys.platform != "darwin":
            return
        import subprocess
        try:
            res = subprocess.run(
                ["osascript", "-e", "input volume of (get volume settings)"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            if res.returncode == 0 and res.stdout.strip().isdigit():
                cur_vol = int(res.stdout.strip())
                if cur_vol < min_level:
                    subprocess.run(
                        ["osascript", "-e", f"set volume input volume {target_level}"],
                        capture_output=True,
                        timeout=1.0,
                    )
                    print(f"[PermissionsManager] Raised microphone input volume from {cur_vol}% to {target_level}%.", file=sys.stderr)
        except Exception:
            pass


