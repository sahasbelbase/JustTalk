"""Escape cancels dictation on macOS, registered as a global hot key only while recording.

Listening to key presses in other apps needs the Input Monitoring permission, which macOS drops
whenever a new (ad-hoc signed) build is installed, so Escape never reached Just Talk. A Carbon hot
key needs no permission. While it's registered, Escape goes to Just Talk instead of the app in
front, which is what you want while dictating; it's released as soon as recording ends.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Callable, Optional

_KEYCODE_ESCAPE = 53
_SIGNATURE = int.from_bytes(b"JTlk", "big")


def _fourcc(code: str) -> int:
    return int.from_bytes(code.encode(), "big")


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


class EscapeHotKey:
    """arm() while recording, disarm() after. Call both on the main thread."""

    def __init__(self, on_escape: Callable[[], None]) -> None:
        self._on_escape = on_escape
        self._carbon = None
        self._handler_ref = ctypes.c_void_p()
        self._hotkey_ref: Optional[ctypes.c_void_p] = None
        self._callback = _HANDLER(self._fired)  # kept alive for as long as the handler is installed
        if sys.platform == "darwin":
            try:
                self._setup()
            except Exception as e:
                print(f"[EscapeHotKey] unavailable: {e}", file=sys.stderr)
                self._carbon = None

    def _setup(self) -> None:
        carbon = ctypes.CDLL(ctypes.util.find_library("Carbon"))
        carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
        carbon.InstallEventHandler.argtypes = [ctypes.c_void_p, _HANDLER, ctypes.c_uint32,
                                               ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
                                               ctypes.POINTER(ctypes.c_void_p)]
        carbon.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID, ctypes.c_void_p,
                                               ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        spec = _EventTypeSpec(_fourcc("keyb"), 5)  # kEventClassKeyboard, kEventHotKeyPressed
        status = carbon.InstallEventHandler(carbon.GetApplicationEventTarget(), self._callback, 1,
                                            ctypes.byref(spec), None, ctypes.byref(self._handler_ref))
        if status != 0:
            raise OSError(f"InstallEventHandler failed ({status})")
        self._carbon = carbon

    @property
    def available(self) -> bool:
        return self._carbon is not None

    def arm(self) -> None:
        if self._carbon is None or self._hotkey_ref is not None:
            return
        ref = ctypes.c_void_p()
        status = self._carbon.RegisterEventHotKey(_KEYCODE_ESCAPE, 0, _EventHotKeyID(_SIGNATURE, 1),
                                                  self._carbon.GetApplicationEventTarget(), 0, ctypes.byref(ref))
        if status == 0:
            self._hotkey_ref = ref
        else:
            print(f"[EscapeHotKey] couldn't register Escape ({status})", file=sys.stderr)

    def disarm(self) -> None:
        if self._carbon is not None and self._hotkey_ref is not None:
            self._carbon.UnregisterEventHotKey(self._hotkey_ref)
        self._hotkey_ref = None

    def _fired(self, _call_ref, _event, _user_data) -> int:
        if self._hotkey_ref is not None:
            print("[EscapeHotKey] Escape pressed -> CANCEL recording", file=sys.stderr)
            self.disarm()
            try:
                self._on_escape()
            except Exception as e:
                print(f"[EscapeHotKey] cancel error: {e}", file=sys.stderr)
        return 0
