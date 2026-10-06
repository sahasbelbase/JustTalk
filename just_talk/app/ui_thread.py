"""Run callables on the Qt main (GUI) thread from any thread."""

from __future__ import annotations

import sys
import threading
import traceback
from typing import Callable, Optional

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal


class _Dispatcher(QObject):
    """Lives on the GUI thread; queued signal delivery runs each callable there."""

    call = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.call.connect(self._run, Qt.ConnectionType.QueuedConnection)

    @staticmethod
    def _run(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            print("[UIThread] Callback error:\n" + traceback.format_exc(), file=sys.stderr)


_dispatcher: Optional[_Dispatcher] = None
_lock = threading.Lock()


def run_on_ui_thread(fn: Callable[[], None]) -> None:
    """
    Schedule ``fn`` on the GUI thread.

    Use this instead of ``QTimer.singleShot(0, fn)`` from worker threads: a QTimer
    created in a plain ``threading.Thread`` has no event loop and never fires.
    """
    global _dispatcher
    with _lock:
        if _dispatcher is None:
            _dispatcher = _Dispatcher()
            app = QCoreApplication.instance()
            if app is not None and _dispatcher.thread() is not app.thread():
                _dispatcher.moveToThread(app.thread())
    _dispatcher.call.emit(fn)
