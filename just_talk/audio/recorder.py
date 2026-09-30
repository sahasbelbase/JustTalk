"""Low-latency streaming microphone audio capture with sounddevice."""

from __future__ import annotations

import math
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
        """
        Enumerate all currently active, online, and connected audio input devices.
        Filters out:
          - Disconnected or phantom devices (verified via check_input_settings)
          - Loopback / non-mic mixers ('stereo mix', 'wave out', 'what u hear')
          - Duplicate device entries across Windows Host APIs (MME, DirectSound, WASAPI)
        """
        devices: List[AudioDeviceInfo] = []
        try:
            device_list = sd.query_devices()
            default_input_idx = sd.default.device[0]

            seen_names = set()
            phantom_keywords = (
                "stereo mix",
                "wave out",
                "what u hear",
                "mapper",
                "primary sound capture",
            )

            for idx, dev in enumerate(device_list):
                if dev.get("max_input_channels", 0) <= 0:
                    continue

                raw_name = str(dev.get("name", "")).strip()
                lower_name = raw_name.lower()

                # Filter out known loopback and non-microphone virtual mixers
                if any(pk in lower_name for pk in phantom_keywords):
                    continue

                # Verify device is physically connected and can actually be opened right now!
                try:
                    sd.check_input_settings(device=idx)
                except Exception:
                    # Device is offline, unplugged, or disabled in OS
                    continue

                # Normalize name to eliminate duplicate entries for the same physical mic across host APIs
                norm_key = (
                    lower_name.replace("windows wasapi", "")
                    .replace("windows directsound", "")
                    .replace("mme", "")
                    .replace("@", "")
                    .strip()
                )
                if norm_key in seen_names and (idx != default_input_idx):
                    continue
                seen_names.add(norm_key)

                devices.append(
                    AudioDeviceInfo(
                        index=idx,
                        name=raw_name,
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
        """
        Start capturing microphone audio.
        Automatically verifies device availability, supports native hardware sample rates
        (such as 48kHz or 44.1kHz on Windows), and falls back gracefully to system default.
        """
        with self._lock:
            if self._is_recording:
                return True
            self._frames.clear()
            self._current_rms = 0.0
            self._is_recording = True

        target_dev = self.device_index
        # Verify selected device is online
        if target_dev is not None:
            try:
                sd.check_input_settings(device=target_dev)
            except Exception:
                print(
                    f"[AudioRecorder] Device {target_dev} is unavailable or unplugged. Falling back to default.",
                    file=sys.stderr,
                )
                target_dev = None

        # Build list of sample rates to try:
        # First 16000 Hz, then native hardware rate (e.g. 48000 Hz or 44100 Hz common on Windows)
        rates_to_try = [self.SAMPLE_RATE]
        try:
            lookup_dev = target_dev if target_dev is not None else sd.default.device[0]
            dev_info = sd.query_devices(lookup_dev)
            hw_rate = int(dev_info.get("default_samplerate", 48000))
            if hw_rate not in rates_to_try:
                rates_to_try.append(hw_rate)
        except Exception:
            rates_to_try.extend([48000, 44100])

        stream = None
        chosen_rate = self.SAMPLE_RATE

        for rate in rates_to_try:
            try:
                stream = sd.InputStream(
                    samplerate=rate,
                    channels=self.CHANNELS,
                    dtype="float32",
                    blocksize=int(self.BLOCK_SIZE * (rate / 16000.0)),
                    device=target_dev,
                    callback=self._audio_callback,
                )
                stream.start()
                chosen_rate = rate
                print(f"[AudioRecorder] Opened microphone stream: device={target_dev}, rate={rate}Hz", file=sys.stderr)
                break
            except Exception as stream_err:
                print(f"[AudioRecorder] Could not open at {rate}Hz: {stream_err}", file=sys.stderr)
                stream = None

        # If selected device failed on all sample rates, fall back to system default device
        if stream is None and target_dev is not None:
            print("[AudioRecorder] Retrying with system default input device...", file=sys.stderr)
            for rate in [self.SAMPLE_RATE, 48000, 44100]:
                try:
                    stream = sd.InputStream(
                        samplerate=rate,
                        channels=self.CHANNELS,
                        dtype="float32",
                        blocksize=int(self.BLOCK_SIZE * (rate / 16000.0)),
                        device=None,
                        callback=self._audio_callback,
                    )
                    stream.start()
                    chosen_rate = rate
                    print(f"[AudioRecorder] Default device fallback opened at {rate}Hz", file=sys.stderr)
                    break
                except Exception:
                    stream = None

        if stream is None:
            with self._lock:
                self._is_recording = False
                self._stream = None
            print("[AudioRecorder] Failed to open any microphone stream!", file=sys.stderr)
            return False

        self._actual_sample_rate = chosen_rate
        self._stream = stream
        return True

    def stop(self) -> Optional[np.ndarray]:
        """
        Stop recording and return the accumulated audio as a 1D NumPy float32 array at 16000 Hz.
        Resamples native hardware rates (e.g. 48kHz) to 16kHz and applies AGC for soft speech.
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

        if captured_audio is not None and len(captured_audio) > 0:
            # Resample to 16000 Hz if recorded at hardware native rate (e.g. 48000 or 44100 Hz)
            actual_rate = getattr(self, "_actual_sample_rate", self.SAMPLE_RATE)
            if actual_rate != self.SAMPLE_RATE:
                try:
                    from scipy import signal

                    gcd = math.gcd(int(actual_rate), self.SAMPLE_RATE)
                    up = self.SAMPLE_RATE // gcd
                    down = int(actual_rate) // gcd
                    captured_audio = signal.resample_poly(captured_audio, up, down).astype(np.float32)
                except Exception as resample_err:
                    print(f"[AudioRecorder] Resample warning: {resample_err}, using linear interpolation", file=sys.stderr)
                    target_len = int(len(captured_audio) * self.SAMPLE_RATE / actual_rate)
                    captured_audio = np.interp(
                        np.linspace(0, len(captured_audio), target_len, endpoint=False),
                        np.arange(len(captured_audio)),
                        captured_audio,
                    ).astype(np.float32)

            # Soft speech automatic gain control (AGC):
            # If the user spoke softly or Windows microphone volume slider is low,
            # scale the audio gently up to a healthy level for Whisper.
            peak = float(np.max(np.abs(captured_audio)))
            if 0.0005 < peak < 0.20:
                boost = min(4.5, 0.75 / max(peak, 0.001))
                captured_audio = np.clip(captured_audio * boost, -1.0, 1.0)
                print(f"[AudioRecorder] Applied AGC boost {boost:.1f}x (peak was {peak:.4f})", file=sys.stderr)

        return captured_audio
