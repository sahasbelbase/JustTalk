"""Frees speech models from RAM after a period of inactivity.

The models stay resident while you are dictating and are loaded again, in the
background, the moment the next recording starts. Nothing is ever unloaded while
a recording, transcription or download is in flight.
"""

from __future__ import annotations

import gc
import sys
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterable, List, Tuple

# (name, is_loaded, unload)
Unloadable = Tuple[str, Callable[[], bool], Callable[[], None]]


class ModelLifecycle:
    def __init__(
        self,
        targets: Callable[[], Iterable[Unloadable]],
        idle_minutes: Callable[[], float],
        clock: Callable[[], float] = time.monotonic,
    ):
        self._targets = targets
        self._idle_minutes = idle_minutes
        self._clock = clock
        self._lock = threading.Lock()
        self._busy = 0
        self._last_used = clock()

    def touch(self) -> None:
        with self._lock:
            self._last_used = self._clock()

    @contextmanager
    def busy(self):
        """Hold the models in memory for the duration of a job; idle time restarts when it ends."""
        with self._lock:
            self._busy += 1
        try:
            yield
        finally:
            with self._lock:
                self._busy -= 1
                self._last_used = self._clock()

    def begin(self) -> None:
        with self._lock:
            self._busy += 1

    def end(self) -> None:
        with self._lock:
            self._busy = max(0, self._busy - 1)
            self._last_used = self._clock()

    def unload_if_idle(self) -> List[str]:
        """Unload every loaded model if the idle limit has passed. Returns the names unloaded."""
        minutes = float(self._idle_minutes() or 0)
        if minutes <= 0:  # 0 = keep models loaded
            return []
        with self._lock:
            if self._busy or self._clock() - self._last_used < minutes * 60:
                return []
            # Hold the lock while unloading so a job can't start halfway through
            freed = []
            for name, is_loaded, unload in self._targets():
                try:
                    if is_loaded():
                        unload()
                        freed.append(name)
                except Exception as e:
                    print(f"[Lifecycle] Could not unload {name}: {e}", file=sys.stderr)
            self._last_used = self._clock()
        if freed:
            gc.collect()
            print(f"[Lifecycle] Idle for {minutes:g} min, unloaded: {', '.join(freed)}", file=sys.stderr)
        return freed
