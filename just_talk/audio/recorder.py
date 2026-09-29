"""Low-latency streaming microphone audio capture with sounddevice."""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np
import sounddevice as sd

from .vad import VoiceActivityDetector


@dataclass
class AudioDeviceInfo:
    """Information about a system audio input device."""

    index: int
    name: str
    max_input_channels: int
    default_samplerate: float
    is_default: bool = False


class AudioRecorder:
    """Manages thread-safe streaming audio recording from the microphone."""

    SAMPLE_RATE = 16000  # Standard Whisper input rate
    CHANNELS = 1         # Mono
    BLOCK_SIZE = 1024    # ~64ms frames

    def __init__(
        self,
        device_index: Optional[int] = None,
        level_callback: Optional[Callable[[float], None]] = None,
    ):
        self.device_index = device_index
        self.level_callback = level_callback
        self._stream: Optional[sd.InputStream] = None
        self._frames: List[np.ndarray] = []
        self._lock = threading.Lock()
        self._is_recording = False
        self._current_rms: float = 0.0

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._is_recording

    def get_audio_level(self) -> float:
        """Thread-safe query for current audio RMS energy level (0.0 to 1.0)."""
        return self._current_rms

    @staticmethod
    def get_input_devices() -> List[AudioDeviceInfo]:
        """Enumerate all available physical and virtual audio input devices."""
        devices: List[AudioDeviceInfo] = []
        try:
            device_list = sd.query_devices()
            default_input_idx = sd.default.device[0]

            for idx, dev in enumerate(device_list):
                if dev.get("max_input_channels", 0) > 0:
                    devices.append(
                        AudioDeviceInfo(
                            index=idx,
                            name=dev.get("name", f"Microphone {idx}"),
                            max_input_channels=dev.get("max_input_channels", 1),
                            default_samplerate=dev.get("default_samplerate", 16000.0),
                            is_default=(idx == default_input_idx),
                        )
                    )
        except Exception as e:
            print(f"[AudioRecorder] Device query error: {e}", file=sys.stderr)
        return devices

    def set_device(self, device_index: Optional[int]) -> None:
        """Update selected input device (takes effect on next recording)."""
        self.device_index = device_index

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: dict,
        status: sd.CallbackFlags,
    ) -> None:
        """PortAudio stream callback running in a real-time audio thread."""
        if not self._is_recording:
            return

        frame = indata[:, 0].copy()

        with self._lock:
            if self._is_recording:
                self._frames.append(frame)

        # Thread-safe atomic float update (safe in CPython GIL, no cross-thread lock)
        self._current_rms = VoiceActivityDetector.calculate_rms(frame)

        # Optional legacy callback hook
        if self.level_callback is not None:
            try:
                self.level_callback(self._current_rms)
            except Exception:
                pass

    def start(self) -> bool:
        """Start capturing microphone audio."""
        with self._lock:
            if self._is_recording:
                return True
            self._frames.clear()
            self._current_rms = 0.0
            self._is_recording = True

        try:
            self._stream = sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype="float32",
                blocksize=self.BLOCK_SIZE,
                device=self.device_index,
                callback=self._audio_callback,
            )
            self._stream.start()
            return True
        except Exception as e:
            with self._lock:
                self._is_recording = False
                self._stream = None
            print(f"[AudioRecorder] Failed to open microphone stream: {e}", file=sys.stderr)
            return False

    def stop(self) -> Optional[np.ndarray]:
        """
        Stop recording and return the accumulated audio as a 1D NumPy float32 array.
        Returns None if no audio or microphone stream error.
        Flushes and stops the PortAudio stream first so all audio is captured without loss.
        """
        with self._lock:
            if not self._is_recording:
                return None
            stream_to_close = self._stream

        # Stop stream first to allow PortAudio to flush any in-flight buffer
        if stream_to_close is not None:
            try:
                stream_to_close.stop()
                stream_to_close.close()
            except Exception:
                pass

        with self._lock:
            self._is_recording = False
            self._current_rms = 0.0
            self._stream = None

            if not self._frames:
                captured_audio = None
            else:
                captured_audio = np.concatenate(self._frames, axis=0)
            self._frames.clear()

        return captured_audio
