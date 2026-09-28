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

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._is_recording

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
        if status:
            pass  # Buffer overflow/underflow warnings ignored for latency

        # Copy incoming 1D float32 audio frame
        frame = indata[:, 0].copy()

        with self._lock:
            if self._is_recording:
                self._frames.append(frame)

        # Notify visual level indicator
        if self.level_callback is not None:
            rms = VoiceActivityDetector.calculate_rms(frame)
            try:
                self.level_callback(rms)
            except Exception:
                pass

    def start(self) -> bool:
        """Start capturing microphone audio."""
        with self._lock:
            if self._is_recording:
                return True
            self._frames.clear()
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
            print(f"[AudioRecorder] Failed to open microphone stream: {e}", file=sys.stderr)
            return False

    def stop(self) -> Optional[np.ndarray]:
        """
        Stop recording and return the accumulated audio as a 1D NumPy float32 array.
        Returns None if no audio or microphone stream error.
        """
        with self._lock:
            if not self._is_recording:
                return None
            self._is_recording = False

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        with self._lock:
            if not self._frames:
                return None
            audio = np.concatenate(self._frames, axis=0)
            self._frames.clear()

        return audio
