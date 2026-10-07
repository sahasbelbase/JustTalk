"""Guided voice enrollment and "test my voice" dialog.

Records through the same AudioRecorder path as dictation (resampling + gain), so enrollment
and dictation embeddings are comparable. Never blocks the UI thread: recording runs on the
recorder's audio thread, and the dialog polls the level meter with a QTimer.
"""

from __future__ import annotations

import threading
from typing import List, Optional

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..audio.recorder import AudioRecorder
from ..audio.speaker_recognizer import SpeakerRecognizer
from ..audio.voice_match import (
    check_take_quality,
    combine_enrollment,
    decide,
    profiles_from_records,
    speech_only,
)
from .theme import ThemeManager
from .ui_thread import run_on_ui_thread

ENROLL_PHRASES = [
    "The quick brown fox jumps over the lazy dog, and I am testing my microphone.",
    "Ma Just Talk ma bolera type gardai chu. Yo ekdam sajilo cha.",
    "Tomorrow's meeting is at ten, so please send me the report before then.",
]
TAKE_SECONDS = 5
TEST_SECONDS = 4
MIN_CONSISTENCY = 0.50


class VoiceEnrollDialog(QDialog):
    """mode="enroll" records three phrases into a profile; mode="test" scores one phrase."""

    def __init__(self, db, config, mode: str = "enroll", parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self.mode = mode
        self.recognizer = SpeakerRecognizer()
        self.recorder = AudioRecorder(device_index=getattr(config, "audio_device_index", None))
        self.takes: List[np.ndarray] = []
        self._remaining = 0.0
        self._recording = False

        self.setWindowTitle("Enroll your voice" if mode == "enroll" else "Test my voice")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 22, 24, 20)

        self.title = QLabel()
        self.title.setFont(ThemeManager.get_ui_font(15, weight=QFont.Weight.DemiBold))
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        self.name_row = QHBoxLayout()
        name_lbl = QLabel("Profile name:")
        self.name_input = QLineEdit("Me")
        self.name_row.addWidget(name_lbl)
        self.name_row.addWidget(self.name_input, 1)
        layout.addLayout(self.name_row)

        self.phrase = QLabel()
        self.phrase.setWordWrap(True)
        self.phrase.setFont(ThemeManager.get_ui_font(16))
        self.phrase.setStyleSheet("padding: 14px; border-radius: 8px; background: rgba(127,127,127,0.12);")
        layout.addWidget(self.phrase)

        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setFixedHeight(10)
        layout.addWidget(self.meter)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("mutedLabel")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("secondaryBtn")
        self.cancel_btn.clicked.connect(self.reject)
        self.action_btn = QPushButton()
        self.action_btn.setObjectName("primaryBtn")
        self.action_btn.clicked.connect(self._on_action)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.action_btn)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

        if not self.recognizer.is_available():
            self._show_download_step()
        else:
            self._show_next_step()

    # ── Steps ────────────────────────────────────────────────────────────────

    def _show_download_step(self) -> None:
        self.title.setText("Download the voice model first")
        self.phrase.setText(
            f"Voice recognition uses a small on-device model ({SpeakerRecognizer.MODEL_SIZE_MB} MB, "
            "Wespeaker CAM++). It runs entirely on your computer."
        )
        self._set_name_visible(False)
        self.status.setText("")
        self.action_btn.setText("Download")
        self._step = "download"

    def _show_next_step(self) -> None:
        if self.mode == "test":
            self._set_name_visible(False)
            self.title.setText("Read this aloud after you press Record")
            self.phrase.setText(ENROLL_PHRASES[0])
            self.action_btn.setText("Record")
            self._step = "record"
            return

        self._set_name_visible(True)
        n = len(self.takes)
        if n < len(ENROLL_PHRASES):
            self.title.setText(f"Phrase {n + 1} of {len(ENROLL_PHRASES)} — press Record, then read it aloud")
            self.phrase.setText(ENROLL_PHRASES[n])
            self.action_btn.setText("Record")
            self._step = "record"
        else:
            self._finish_enrollment()

    def _set_name_visible(self, visible: bool) -> None:
        for i in range(self.name_row.count()):
            w = self.name_row.itemAt(i).widget()
            if w:
                w.setVisible(visible)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _on_action(self) -> None:
        step = getattr(self, "_step", "")
        if step == "download":
            self._start_download()
        elif step == "record":
            self._start_recording()
        elif step == "save":
            self._save_profile()
        elif step == "retry":
            self.takes.clear()
            self._show_next_step()
        elif step == "done":
            self.accept()

    def _start_download(self) -> None:
        self.action_btn.setEnabled(False)
        self.status.setText("Downloading…")

        def progress(frac: float) -> None:
            run_on_ui_thread(lambda: self.meter.setValue(int(frac * 100)))

        def worker() -> None:
            ok, msg = self.recognizer.download(progress)

            def done() -> None:
                self.action_btn.setEnabled(True)
                self.meter.setValue(0)
                self.status.setText(msg)
                if ok:
                    self._show_next_step()

            run_on_ui_thread(done)

        threading.Thread(target=worker, daemon=True).start()

    def _start_recording(self) -> None:
        if not self.recorder.start():
            self.status.setText("Couldn't open the microphone. Check the input device in Settings › Audio.")
            return
        self._recording = True
        self._remaining = float(TEST_SECONDS if self.mode == "test" else TAKE_SECONDS)
        self.action_btn.setEnabled(False)
        self.name_input.setEnabled(False)
        self._timer.start()

    def _tick(self) -> None:
        level = self.recorder.get_audio_level()
        self.meter.setValue(int(min(1.0, level * 12) * 100))
        self._remaining -= self._timer.interval() / 1000.0
        if self._remaining > 0:
            self.status.setText(f"Listening… {self._remaining:.0f} s")
            return
        self._timer.stop()
        self._recording = False
        audio = self.recorder.stop()
        self.meter.setValue(0)
        self.action_btn.setEnabled(True)
        self._on_take_finished(audio if audio is not None else np.zeros(0, dtype=np.float32))

    def _on_take_finished(self, audio: np.ndarray) -> None:
        problem = check_take_quality(audio)
        if problem:
            self.status.setText(f"{problem} Press Record to try again.")
            return
        emb = self.recognizer.extract_embedding(speech_only(audio))
        if emb is None:
            self.status.setText("Couldn't read that recording. Press Record to try again.")
            return

        if self.mode == "test":
            self._show_test_result(emb)
            return

        self.takes.append(emb)
        self.status.setText("Got it.")
        self._show_next_step()

    def _finish_enrollment(self) -> None:
        profile, accept, consistency = combine_enrollment(self.takes)
        self._profile = (profile, accept)
        if consistency < MIN_CONSISTENCY:
            self.title.setText("Those recordings didn't sound alike")
            self.phrase.setText(
                "Background noise or a changing distance from the microphone can do this. "
                "Try again somewhere quieter, keeping the same distance."
            )
            self.status.setText(f"Consistency {consistency:.2f} (needs {MIN_CONSISTENCY:.2f}).")
            self.action_btn.setText("Start over")
            self._step = "retry"
            return
        self.title.setText("All set — save your voice profile")
        self.phrase.setText(
            "Just Talk will recognise this voice. With “Ignore unrecognized voices” on, dictations that "
            "clearly come from someone else are skipped; if it was you, press Paste Last Dictation right "
            "after and Just Talk keeps it and learns."
        )
        self.status.setText(f"Consistency {consistency:.2f} · match threshold {accept:.2f}")
        self.action_btn.setText("Save")
        self._step = "save"

    def _save_profile(self) -> None:
        name = self.name_input.text().strip() or "Me"
        profile, accept = self._profile
        self.db.save_voice_profile(name, profile, threshold=accept, sample_count=len(self.takes))
        self.accept()

    def _show_test_result(self, emb: np.ndarray) -> None:
        profiles = profiles_from_records(self.db.get_voice_profile_records())
        if not profiles:
            self.status.setText("No voice profiles yet. Enroll a voice first.")
            return
        d = decide(emb, profiles)
        best = max(profiles, key=lambda p: float(np.dot(emb, p.embedding)))
        accept, reject = best.thresholds
        if d.action == "match":
            verdict = f"Recognised as “{d.speaker}”."
        elif d.action == "other":
            verdict = "Not recognised — this would be ignored as another voice. Consider re-enrolling."
        else:
            verdict = "Unsure — this would be kept, but not tagged."
        self.title.setText(verdict)
        self.status.setText(
            f"Match score {d.score:.2f} for “{best.name}” (recognised at {accept:.2f}, ignored below {reject:.2f})."
        )
        self.action_btn.setText("Test again")
        self._step = "record"

    def reject(self) -> None:  # Cancel / Esc / close
        self._timer.stop()
        if self.recorder.is_recording:
            self.recorder.stop()
        super().reject()
