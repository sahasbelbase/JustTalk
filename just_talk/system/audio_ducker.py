"""System Audio Ducker — temporarily mutes computer audio output (music, movies, videos, Reels) while recording."""

from __future__ import annotations

import atexit
import subprocess
import sys
from typing import Optional


class SystemAudioDucker:
    """
    Temporarily mutes computer sound output (music, YouTube, movies, Instagram Reels, Zoom)
    while the user holds the push-to-talk shortcut key, and seamlessly restores audio when released.

    Supported on both macOS (.dmg) and Windows (.exe):
    - macOS: Pre-compiled NSAppleScript (sub-millisecond execution, ~0.8ms) with osascript fallback.
    - Windows: Direct Windows CoreAudio WASAPI IAudioEndpointVolume (sub-millisecond execution, ~0.5ms)
               with virtual key event VK_VOLUME_MUTE fallback.
    - Linux: pactl / amixer Master sink controls.

    Prevents laptop/desktop speaker audio from bleeding into the microphone and being transcribed.
    """

    def __init__(self) -> None:
        self._is_ducked: bool = False
        self._was_already_muted: bool = False

        # macOS pre-compiled scripts
        self._script_mute = None
        self._script_unmute = None
        self._script_get = None

        # Windows WASAPI endpoints
        self._win_endpoint_volume = None
        self._win_set_mute = None
        self._win_get_mute = None

        if sys.platform == "darwin":
            self._init_macos()
        elif sys.platform == "win32":
            self._init_windows()

        # Always guarantee system audio is restored if app terminates while recording
        atexit.register(self.unmute)

    def _init_macos(self) -> None:
        """Pre-compile macOS NSAppleScript instances for sub-millisecond execution latency."""
        try:
            from Foundation import NSAppleScript

            self._script_mute = NSAppleScript.alloc().initWithSource_("set volume output muted true")
            self._script_unmute = NSAppleScript.alloc().initWithSource_("set volume output muted false")
            self._script_get = NSAppleScript.alloc().initWithSource_("output muted of (get volume settings)")
        except Exception as e:
            print(f"[AudioDucker] Failed to initialize NSAppleScript ({e}), will use osascript fallback", file=sys.stderr)

    def _init_windows(self) -> None:
        """Initialize Windows CoreAudio (WASAPI) endpoint volume controller via pure ctypes."""
        try:
            import ctypes
            from ctypes import POINTER, byref, c_void_p, c_int, Structure
            from ctypes.wintypes import DWORD, BOOL

            class GUID(Structure):
                _fields_ = [
                    ("Data1", DWORD),
                    ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            def _guid(s: str) -> GUID:
                import uuid
                u = uuid.UUID(s)
                return GUID(
                    u.time_low,
                    u.time_mid,
                    u.time_hi_version,
                    u.clock_seq_hi_variant,
                    u.clock_seq_low,
                    *u.node.to_bytes(6, "big"),
                )

            CLSID_MMDeviceEnumerator = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
            IID_IMMDeviceEnumerator = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
            IID_IAudioEndpointVolume = _guid("5CDF2C82-841E-4546-9722-0CF74078229A")

            ole32 = ctypes.oledll.ole32
            ole32.CoInitialize(None)

            enumerator = c_void_p()
            hr = ole32.CoCreateInstance(
                byref(CLSID_MMDeviceEnumerator),
                None,
                1,  # CLSCTX_INPROC_SERVER
                byref(IID_IMMDeviceEnumerator),
                byref(enumerator),
            )
            if hr == 0 and enumerator.value:
                enum_vtable = ctypes.cast(
                    ctypes.cast(enumerator, POINTER(c_void_p)).contents,
                    POINTER(c_void_p),
                )
                GetDefaultAudioEndpoint_proto = ctypes.WINFUNCTYPE(
                    c_int, c_void_p, c_int, c_int, POINTER(c_void_p)
                )
                GetDefaultAudioEndpoint = GetDefaultAudioEndpoint_proto(enum_vtable[4])

                device = c_void_p()
                hr = GetDefaultAudioEndpoint(enumerator, 0, 1, byref(device))
                if hr == 0 and device.value:
                    dev_vtable = ctypes.cast(
                        ctypes.cast(device, POINTER(c_void_p)).contents,
                        POINTER(c_void_p),
                    )
                    Activate_proto = ctypes.WINFUNCTYPE(
                        c_int, c_void_p, POINTER(GUID), DWORD, c_void_p, POINTER(c_void_p)
                    )
                    Activate = Activate_proto(dev_vtable[3])

                    endpoint_volume = c_void_p()
                    hr = Activate(device, byref(IID_IAudioEndpointVolume), 23, None, byref(endpoint_volume))
                    if hr == 0 and endpoint_volume.value:
                        self._win_endpoint_volume = endpoint_volume
                        vol_vtable = ctypes.cast(
                            ctypes.cast(endpoint_volume, POINTER(c_void_p)).contents,
                            POINTER(c_void_p),
                        )
                        SetMute_proto = ctypes.WINFUNCTYPE(c_int, c_void_p, BOOL, c_void_p)
                        GetMute_proto = ctypes.WINFUNCTYPE(c_int, c_void_p, POINTER(BOOL))
                        self._win_set_mute = SetMute_proto(vol_vtable[14])
                        self._win_get_mute = GetMute_proto(vol_vtable[15])
        except Exception as e:
            print(f"[AudioDucker] Windows WASAPI init ({e}), using virtual key fallback", file=sys.stderr)

    def is_system_muted(self) -> bool:
        """Check if the system output volume is currently muted."""
        if sys.platform == "darwin":
            if self._script_get:
                try:
                    res, err = self._script_get.executeAndReturnError_(None)
                    if res:
                        return bool(res.booleanValue())
                except Exception:
                    pass
            try:
                out = subprocess.check_output(
                    ["osascript", "-e", "output muted of (get volume settings)"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=1.0,
                ).strip()
                return out.lower() == "true"
            except Exception:
                return False
        elif sys.platform == "win32":
            if hasattr(self, "_win_get_mute") and self._win_get_mute and self._win_endpoint_volume:
                try:
                    from ctypes.wintypes import BOOL
                    from ctypes import byref
                    b = BOOL()
                    hr = self._win_get_mute(self._win_endpoint_volume, byref(b))
                    if hr == 0:
                        return bool(b.value)
                except Exception:
                    pass
            return False
        elif sys.platform == "linux":
            try:
                out = subprocess.check_output(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], text=True, timeout=1.0)
                return "yes" in out.lower()
            except Exception:
                return False
        return False

    def mute(self) -> None:
        """Mute system audio output if not already muted."""
        if self._is_ducked:
            return

        self._was_already_muted = self.is_system_muted()
        if self._was_already_muted:
            # User intentionally has audio muted already; do nothing
            return

        if sys.platform == "darwin":
            if self._script_mute:
                try:
                    self._script_mute.executeAndReturnError_(None)
                    self._is_ducked = True
                    return
                except Exception:
                    pass
            try:
                subprocess.run(
                    ["osascript", "-e", "set volume output muted true"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                )
                self._is_ducked = True
            except Exception as e:
                print(f"[AudioDucker] macOS mute error: {e}", file=sys.stderr)

        elif sys.platform == "win32":
            # 1. Primary: Direct Windows CoreAudio WASAPI
            if hasattr(self, "_win_set_mute") and self._win_set_mute and self._win_endpoint_volume:
                try:
                    hr = self._win_set_mute(self._win_endpoint_volume, 1, None)
                    if hr == 0:
                        self._is_ducked = True
                        return
                except Exception:
                    pass

            # 2. Universal fallback: Windows VK_VOLUME_MUTE keyboard event
            try:
                import ctypes

                VK_VOLUME_MUTE = 0xAD
                ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 2, 0)
                self._is_ducked = True
            except Exception as e:
                print(f"[AudioDucker] Windows mute error: {e}", file=sys.stderr)

        elif sys.platform == "linux":
            try:
                subprocess.run(
                    ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                )
                self._is_ducked = True
            except Exception:
                try:
                    subprocess.run(
                        ["amixer", "-D", "pulse", "set", "Master", "mute"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1.0,
                    )
                    self._is_ducked = True
                except Exception:
                    pass

    def unmute(self) -> None:
        """Unmute system audio output if we muted it."""
        if not self._is_ducked:
            return

        self._is_ducked = False
        if self._was_already_muted:
            # If the user originally had it muted, keep it muted
            return

        if sys.platform == "darwin":
            if self._script_unmute:
                try:
                    self._script_unmute.executeAndReturnError_(None)
                    return
                except Exception:
                    pass
            try:
                subprocess.run(
                    ["osascript", "-e", "set volume output muted false"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                )
            except Exception as e:
                print(f"[AudioDucker] macOS unmute error: {e}", file=sys.stderr)

        elif sys.platform == "win32":
            # 1. Primary: Direct Windows CoreAudio WASAPI
            if hasattr(self, "_win_set_mute") and self._win_set_mute and self._win_endpoint_volume:
                try:
                    hr = self._win_set_mute(self._win_endpoint_volume, 0, None)
                    if hr == 0:
                        return
                except Exception:
                    pass

            # 2. Universal fallback: Windows VK_VOLUME_MUTE keyboard event
            try:
                import ctypes

                VK_VOLUME_MUTE = 0xAD
                ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 2, 0)
            except Exception as e:
                print(f"[AudioDucker] Windows unmute error: {e}", file=sys.stderr)

        elif sys.platform == "linux":
            try:
                subprocess.run(
                    ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                )
            except Exception:
                try:
                    subprocess.run(
                        ["amixer", "-D", "pulse", "set", "Master", "unmute"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1.0,
                    )
                except Exception:
                    pass
