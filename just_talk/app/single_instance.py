"""Single instance lock using OS file locking and QLocalServer."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from ..config import get_app_data_dir

SOCKET_NAME = "justtalk_single_instance_lock"


class SingleInstanceManager(QObject):
    """
    Guarantees that Just Talk runs as a strictly single-instance application.
    If a secondary instance is launched, it notifies the running instance and exits.
    """

    instance_activated = Signal()

    def __init__(
        self,
        on_activate: Optional[Callable[[], None]] = None,
        lock_name: str = SOCKET_NAME,
    ):
        super().__init__()
        self.on_activate = on_activate
        self.lock_name = lock_name
        self._server: Optional[QLocalServer] = None
        self._lock_file = None
        self._lock_path = get_app_data_dir() / f"{lock_name}.lock"

    def try_lock(self) -> bool:
        """
        Attempt to acquire the single-instance lock.
        Returns True if this is the ONLY running instance.
        Returns False if another instance is already running.
        """
        # Step 1: Check if an existing QLocalServer is listening
        socket = QLocalSocket()
        socket.connectToServer(self.lock_name)
        if socket.waitForConnected(300):
            # Another instance is already active! Tell it to activate
            socket.write(b"ACTIVATE\n")
            socket.waitForBytesWritten(300)
            socket.disconnectFromServer()
            return False

        # Step 2: Acquire OS-level kernel file lock
        try:
            self._lock_file = open(self._lock_path, "w")
            if sys.platform != "win32":
                import fcntl

                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt

                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except (IOError, OSError):
            # File is locked by an existing process
            return False

        # Step 3: Start QLocalServer to listen for future launch attempts
        QLocalServer.removeServer(self.lock_name)  # Clean any stale socket file
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._handle_new_connection)
        self._server.listen(self.lock_name)

        return True

    def _handle_new_connection(self) -> None:
        """Called when a secondary launch attempt connects."""
        if not self._server:
            return
        client = self._server.nextPendingConnection()
        if client:
            client.waitForReadyRead(200)
            msg = client.readAll().data().decode("utf-8", errors="ignore")
            client.disconnectFromServer()

            if "ACTIVATE" in msg:
                self.instance_activated.emit()
                if self.on_activate:
                    self.on_activate()

    def cleanup(self) -> None:
        """Release server and file locks upon exit."""
        if self._server:
            self._server.close()
            QLocalServer.removeServer(self.lock_name)
            self._server = None

        if self._lock_file:
            try:
                if sys.platform != "win32":
                    import fcntl

                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception:
                pass
            self._lock_file = None
