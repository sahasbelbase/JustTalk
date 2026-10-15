"""First-run setup: permissions, languages, your work, a voice profile, and a first try.

The voice step is the heart of it. The user reads short sentences; words light up as the speech
engine hears them, every engine on the computer is scored on their voice in the background, and
the result says which engine to use, what it mishears, and how close they are to the 98% goal.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import uuid
from typing import Callable, Dict, List, Optional

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..audio.recorder import AudioRecorder
from ..config import ADDITIONAL_LANGUAGES, AppConfig
from ..language_setup import normalize_language_settings
from ..profile.engines import ProfileEngines, apply_choice, can_apply, engine_label
from ..profile.scoring import score_take
from ..profile.scripts import EN, MIXED, NE, ROLES, Prompt
from ..profile.session import OFF_SCRIPT_ACCURACY, TARGET_ACCURACY, ProfileSession, is_learnable_mixup, languages_to_profile
from ..profile.store import VoiceProfile, save_clip
from ..stt.model_manager import ModelManager
from ..system.autostart import AutostartManager
from ..system.permissions import PermissionsManager
from . import icons
from .onboarding_widgets import (
    AccuracyBar,
    ChoiceCard,
    FlowLayout,
    LevelMeter,
    ReadingView,
    SegmentedChoice,
    StepBar,
    WordsInput,
    chip,
)
from .theme import ThemeManager

PAGES = ("welcome", "languages", "about", "voice", "result", "ready")
LANGUAGE_NAMES = {EN: "English", NE: "नेपाली", MIXED: "Nepglish"}
OTHER_LANGUAGES = [("de", "Deutsch"), ("fr", "Français"), ("es", "Español"), ("zh", "中文")]

END_SILENCE_SEC = 1.2       # pause after speech that ends a sentence
END_SILENCE_DONE_SEC = 0.5  # shorter pause once every word has lit up
NO_SPEECH_SEC = 7.0
MAX_TAKE_SEC = 15.0
MIN_SPEECH_SEC = 0.3
MIN_SPEECH_LEVEL = 0.0003   # same floor as the dictation VAD
SPEECH_OVER_NOISE = 4.0     # speech is this many times louder than the gaps between words
LEVEL_WINDOW = 90           # ~3 s of meter ticks for the noise floor
LIVE_INTERVAL_SEC = 0.3
ADVANCE_DELAY_MS = 900
FINISH_EARLY_AFTER = 5      # takes before "Finish" is offered mid-session
MAX_COMPARE_TAKES = 4       # sentences per language to compare engines the user doesn't use (Whisper Turbo is slow)


def _label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def _take_problem(audio: np.ndarray) -> Optional[str]:
    """Only problems a transcript can't reveal; endpointing already confirmed there was speech."""
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < 1e-4:
        return "No sound from the microphone. Check that the right microphone is selected."
    if peak >= 0.999:
        return "Too loud. Move back from the microphone a little."
    return None


def _icon_button(text: str, icon_name: str, name: str = "linkBtn") -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(name)
    b.setIcon(icons.icon(icon_name, icons.ICON_MUTED, icons.ICON_MUTED, 16))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class OnboardingWindow(QDialog):
    onboarding_completed = Signal()
    _partial_ready = Signal(int, str)          # take token, text
    _engine_result = Signal(str, str, str)     # clip id, engine id ("" = job skipped), text
    _live_warm = Signal(bool)
    _kriti_progress = Signal(float, str)

    def __init__(
        self,
        config: AppConfig,
        gemini=None,
        model_manager: Optional[ModelManager] = None,
        on_complete: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
        kriti=None,
        on_engines_changed: Optional[Callable[[], None]] = None,
        learner=None,
    ):
        super().__init__(parent)
        self.config = config
        self.gemini = gemini
        self.model_manager = model_manager or ModelManager()
        self.kriti = kriti
        self.on_complete_callback = on_complete
        self.on_engines_changed = on_engines_changed
        self.learner = learner
        self.engines = ProfileEngines(config, self.model_manager, kriti)

        self.session: Optional[ProfileSession] = None
        self.recorder = AudioRecorder(device_index=getattr(config, "audio_device_index", None))
        self._state = "intro"
        self._prompt: Optional[Prompt] = None
        self._clip_id = ""
        self._token = 0
        self._display_engine: Dict[str, str] = {}
        self._clip_pending: Dict[str, int] = {}
        self._compared: Dict[tuple, int] = {}
        self._live = None
        self._live_id = ""
        self._warmed: set = set()
        self._slow_live: set = set()
        self._clip_files: Dict[str, str] = {}
        self._pending_jobs = 0
        self._engine_failures: Dict[str, int] = {}
        self._jobs: "queue.Queue" = queue.Queue()
        self._eval_thread: Optional[threading.Thread] = None
        self._kriti_downloading = False
        self._finished = False

        self.setWindowTitle("Set up Just Talk")
        self.resize(900, 680)
        self.setMinimumSize(820, 620)
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

        self._partial_ready.connect(self._on_partial)
        self._engine_result.connect(self._on_engine_result)
        self._live_warm.connect(self._on_live_warm)
        self._kriti_progress.connect(self._on_kriti_progress)

        self._listen_timer = QTimer(self)
        self._listen_timer.setInterval(33)
        self._listen_timer.timeout.connect(self._listen_tick)
        self._advance_timer = QTimer(self)
        self._advance_timer.setSingleShot(True)
        self._advance_timer.timeout.connect(self._next_sentence)

        self._build()
        for key, handler in ((Qt.Key.Key_Space, self._toggle_pause), (Qt.Key.Key_R, self._read_again)):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda h=handler: self._voice_shortcut(h))
        self._refresh_permissions()
        self._perm_timer = QTimer(self)
        self._perm_timer.setInterval(1500)
        self._perm_timer.timeout.connect(self._refresh_permissions)
        self._perm_timer.start()
        self._go(0)

    # ── Frame ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(44, 26, 44, 26)
        outer.setSpacing(0)

        self.step_bar = StepBar(len(PAGES))
        outer.addWidget(self.step_bar)
        outer.addSpacing(30)

        self.stack = QStackedWidget()
        builders = {
            "welcome": self._page_welcome,
            "languages": self._page_languages,
            "about": self._page_about,
            "voice": self._page_voice,
            "result": self._page_result,
            "ready": self._page_ready,
        }
        for name in PAGES:
            self.stack.addWidget(builders[name]())
        outer.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        nav.setContentsMargins(0, 18, 0, 0)
        self.back_btn = QPushButton("Back")
        self.back_btn.setObjectName("linkBtn")
        self.back_btn.clicked.connect(self._on_back)
        nav.addWidget(self.back_btn)
        nav.addStretch()
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setObjectName("linkBtn")
        self.skip_btn.clicked.connect(self._on_skip)
        nav.addWidget(self.skip_btn)
        nav.addSpacing(14)
        self.next_btn = QPushButton("Continue")
        self.next_btn.setObjectName("primaryBtn")
        self.next_btn.setProperty("size", "large")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self._on_next)
        nav.addWidget(self.next_btn)
        outer.addLayout(nav)

    def _page(self, title: str, lead: str = "", scroll: bool = False, fill: bool = False):
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        column = QWidget()
        column.setMaximumWidth(700)
        body = QVBoxLayout(column)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        title_lbl = _label(title, "h1")
        body.addWidget(title_lbl)
        lead_lbl = None
        if lead:
            body.addSpacing(10)
            lead_lbl = _label(lead, "lead")
            body.addWidget(lead_lbl)
        body.addSpacing(28)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setWidget(column)
            row.addWidget(area)
        else:
            row.addStretch()
            row.addWidget(column, 100)
            row.addStretch()
        content = QVBoxLayout()
        content.setSpacing(0)
        if fill:
            body.addLayout(content, 1)  # the page lays out its own vertical space
        else:
            body.addLayout(content)
            body.addStretch()
        page.title_lbl, page.lead_lbl = title_lbl, lead_lbl
        return page, content

    def _go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        name = PAGES[index]
        self.step_bar.set_current(index)
        self.back_btn.setVisible(index > 0 and name != "result" and not (name == "voice" and self.session))
        self.skip_btn.setVisible(name in ("about", "voice", "result"))
        self.skip_btn.setText("Skip")
        self.next_btn.setEnabled(True)
        self.next_btn.setText({"ready": "Start using Just Talk", "voice": "Start"}.get(name, "Continue"))
        if name == "voice":
            self._enter_voice()
        elif name == "result":
            self._render_result()
        elif name == "ready":
            QTimer.singleShot(0, self.try_box.setFocus)

    def _current(self) -> str:
        return PAGES[self.stack.currentIndex()]

    def _on_back(self) -> None:
        idx = self.stack.currentIndex()
        if idx > 0:
            self._go(idx - 1)

    def _on_next(self) -> None:
        name = self._current()
        if name == "languages":
            normalize_language_settings(self.config)
            self.config.save()
        if name == "about":
            self._save_about()
        if name == "voice":
            if self._state == "unsupported":
                self._go(PAGES.index("ready"))
            elif self.session is None:
                self._start_session()
            else:
                self._finish_reading()
            return
        if name == "result":
            self._save_profile()
        if name == "ready":
            self._finish_onboarding()
            return
        self._go(self.stack.currentIndex() + 1)

    def _on_skip(self) -> None:
        name = self._current()
        if name == "about":
            self._go(PAGES.index("voice"))
        elif name == "voice":
            self._stop_listening(discard=True)
            if self.session and self.session.done_count:
                self._finish_reading()
            else:
                self._go(PAGES.index("ready"))
        elif name == "result":
            self._go(PAGES.index("ready"))

    def _finish_onboarding(self) -> None:
        self._finished = True
        self.config.has_completed_onboarding = True
        self.config.save()
        self._shutdown()
        self.accept()
        if self.on_complete_callback:
            self.on_complete_callback()
        self.onboarding_completed.emit()

    def reject(self) -> None:  # window closed or Esc
        self._shutdown()
        super().reject()

    def _shutdown(self) -> None:
        self._perm_timer.stop()
        self._listen_timer.stop()
        self._advance_timer.stop()
        self._token += 1
        if self.recorder.is_recording:
            self.recorder.stop()
        self._jobs.put(None)
        threading.Thread(target=self.engines.release, daemon=True).start()

    def _voice_shortcut(self, handler: Callable[[], None]) -> None:
        if self._current() == "voice" and self.session is not None and self._state != "done":
            handler()

    # ── Page 1: welcome & permissions ────────────────────────────────────────

    def _perm_row(self, title: str, caption: str):
        row = QFrame()
        row.setObjectName("hairRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 14, 0, 14)
        lay.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(_label(title, "rowTitle"))
        text.addWidget(_label(caption, "caption"))
        lay.addLayout(text, 1)
        status = _label("", "statusOk", wrap=False)
        lay.addWidget(status)
        button = QPushButton()
        button.setObjectName("secondaryBtn")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(button)
        return row, status, button

    def _page_welcome(self) -> QWidget:
        page, body = self._page("Talk, and it types.", "Just Talk turns your voice into text in any app. First, a few permissions.")
        row, self.mic_status, self.mic_btn = self._perm_row("Microphone", "To hear you while you dictate.")
        self.mic_btn.setText("Allow")
        self.mic_btn.clicked.connect(self._request_mic)
        body.addWidget(row)

        acc_title = "Keyboard shortcut and typing" if sys.platform == "darwin" else "Keyboard shortcut"
        row, self.acc_status, self.acc_btn = self._perm_row(acc_title, "To start on your shortcut and type into other apps.")
        self.acc_btn.setText("Open Settings")
        self.acc_btn.clicked.connect(self._open_accessibility)
        self.restart_btn = QPushButton("Restart Just Talk")
        self.restart_btn.setObjectName("primaryBtn")
        self.restart_btn.clicked.connect(self._restart)
        self.restart_btn.hide()
        row.layout().addWidget(self.restart_btn)
        body.addWidget(row)

        self.fn_status = self.fn_btn = None
        if sys.platform == "darwin":
            row, self.fn_status, self.fn_btn = self._perm_row("fn key", "Stop fn from opening the emoji picker.")
            self.fn_btn.setText("Fix")
            self.fn_btn.clicked.connect(self._fix_fn)
            body.addWidget(row)

        startup = QFrame()
        startup.setObjectName("hairRow")
        sl = QHBoxLayout(startup)
        sl.setContentsMargins(0, 14, 0, 14)
        self.startup_chk = QCheckBox("Open Just Talk when I log in")
        self.startup_chk.setChecked(bool(self.config.launch_at_startup) or not self.config.has_completed_onboarding)
        self.startup_chk.toggled.connect(self._on_startup_toggled)
        sl.addWidget(self.startup_chk)
        body.addWidget(startup)
        return page

    def _set_status(self, label: QLabel, ok: bool, text: str) -> None:
        label.setText(text)
        label.setObjectName("statusOk" if ok else "statusWarn")
        label.style().unpolish(label)
        label.style().polish(label)

    def _refresh_permissions(self) -> None:
        has_mic, _ = PermissionsManager.check_microphone()
        self._set_status(self.mic_status, has_mic, "Allowed" if has_mic else "Needed")
        self.mic_btn.setVisible(not has_mic)

        if sys.platform == "win32":
            self._set_status(self.acc_status, True, "Ready")
            self.acc_btn.hide()
        else:
            has_acc = PermissionsManager.check_accessibility(prompt_if_needed=False)
            has_input = PermissionsManager.check_input_monitoring()
            ok = has_acc and has_input
            missing = [n for n, have in (("Accessibility", has_acc), ("Input Monitoring", has_input)) if not have]
            self._set_status(self.acc_status, ok, "Allowed" if ok else f"{' and '.join(missing)} needed")
            self.acc_btn.setVisible(not ok)

        if self.fn_status is not None:
            fixed = PermissionsManager.is_fn_emoji_disabled()
            self._set_status(self.fn_status, fixed, "Done" if fixed else "Opens emoji")
            self.fn_btn.setVisible(not fixed)

    def _request_mic(self) -> None:
        PermissionsManager.request_microphone()
        QTimer.singleShot(1500, self._refresh_permissions)

    def _open_accessibility(self) -> None:
        if not PermissionsManager.check_accessibility(prompt_if_needed=False):
            PermissionsManager.open_accessibility_settings()
        else:
            PermissionsManager.open_input_monitoring_settings()
        self.restart_btn.show()
        QTimer.singleShot(2000, self._refresh_permissions)

    def _restart(self) -> None:
        python = sys.executable
        os.execl(python, python, *sys.argv)

    def _fix_fn(self) -> None:
        PermissionsManager.disable_fn_emoji_popup()
        self._refresh_permissions()

    def _on_startup_toggled(self, checked: bool) -> None:
        self.config.launch_at_startup = checked
        self.config.save()
        AutostartManager.set_autostart(checked)

    # ── Page 2: languages ────────────────────────────────────────────────────

    def _page_languages(self) -> QWidget:
        page, body = self._page("What do you speak?", "Pick every language you dictate in.")
        spoken = set(self.config.spoken_languages or ["en"])

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.en_card = ChoiceCard("English", "Including English with an accent")
        self.ne_card = ChoiceCard("नेपाली", "Nepali, and Nepali mixed with English")
        self.en_card.setChecked("en" in spoken)
        self.ne_card.setChecked("ne" in spoken)
        for card in (self.en_card, self.ne_card):
            card.toggled.connect(self._on_languages_changed)
            cards.addWidget(card)
        body.addLayout(cards)

        body.addSpacing(22)
        body.addWidget(_label("Also", "eyebrow"))
        body.addSpacing(10)
        others = QHBoxLayout()
        others.setSpacing(8)
        self.other_chips: Dict[str, QPushButton] = {}
        for code, name in OTHER_LANGUAGES:
            b = chip(name)
            b.setChecked(code in spoken)
            b.toggled.connect(self._on_languages_changed)
            self.other_chips[code] = b
            others.addWidget(b)
        self.more_combo = QComboBox()
        self.more_combo.addItem("More languages", "")
        for name, code in ADDITIONAL_LANGUAGES:
            self.more_combo.addItem(name, code)
        self.more_combo.currentIndexChanged.connect(self._on_more_language)
        others.addWidget(self.more_combo)
        others.addStretch()
        body.addLayout(others)

        self.nepali_box = QWidget()
        nb = QVBoxLayout(self.nepali_box)
        nb.setContentsMargins(0, 26, 0, 0)
        nb.setSpacing(10)
        nb.addWidget(_label("Write Nepali in", "eyebrow"))
        self.script_choice = SegmentedChoice(
            [("devanagari", "देवनागरी"), ("romanized", "Roman · k cha"), ("auto", "Depends on the app")],
            getattr(self.config, "nepali_output_mode", "auto") if getattr(self.config, "nepali_output_mode", "auto") != "english" else "auto",
        )
        self.script_choice.changed.connect(self._on_script_changed)
        nb.addWidget(self.script_choice)

        self.kriti_row = QFrame()
        self.kriti_row.setObjectName("hairRow")
        kr = QHBoxLayout(self.kriti_row)
        kr.setContentsMargins(0, 16, 0, 14)
        kt = QVBoxLayout()
        kt.setSpacing(2)
        kt.addWidget(_label("Offline Nepali model", "rowTitle"))
        self.kriti_caption = _label("Kriti by Naamche Labs. Best for Nepali and Nepglish. 475 MB.", "caption")
        kt.addWidget(self.kriti_caption)
        self.kriti_progress = QProgressBar()
        self.kriti_progress.setRange(0, 100)
        self.kriti_progress.setFixedHeight(4)
        self.kriti_progress.setTextVisible(False)
        self.kriti_progress.hide()
        kt.addSpacing(6)
        kt.addWidget(self.kriti_progress)
        kr.addLayout(kt, 1)
        self.kriti_btn = QPushButton("Download")
        self.kriti_btn.setObjectName("secondaryBtn")
        self.kriti_btn.clicked.connect(self._download_kriti)
        kr.addWidget(self.kriti_btn)
        nb.addSpacing(8)
        nb.addWidget(self.kriti_row)
        body.addWidget(self.nepali_box)
        self._sync_language_ui()
        return page

    def _spoken_from_ui(self) -> List[str]:
        langs = []
        if self.en_card.isChecked():
            langs.append("en")
        if self.ne_card.isChecked():
            langs.append("ne")
        langs += [c for c, b in self.other_chips.items() if b.isChecked()]
        langs += [c for c in (self.config.spoken_languages or []) if c not in langs and c not in ("en", "ne") and c not in self.other_chips]
        return langs

    def _on_languages_changed(self, *_args) -> None:
        langs = self._spoken_from_ui()
        if not langs:
            self.en_card.setChecked(True)
            return
        self.config.spoken_languages = langs
        if self.config.language not in langs and not (self.config.language == "ne_en" and "ne" in langs and "en" in langs):
            self.config.language = "en" if "en" in langs else langs[0]
        self.config.save()
        self._sync_language_ui()

    def _on_more_language(self, index: int) -> None:
        code = self.more_combo.currentData()
        if code and code not in self.config.spoken_languages:
            self.config.spoken_languages = list(self.config.spoken_languages) + [code]
            self.config.save()
            self.more_combo.setItemText(index, f"{self.more_combo.itemText(index)}  ✓")
        self.more_combo.blockSignals(True)
        self.more_combo.setCurrentIndex(0)
        self.more_combo.blockSignals(False)

    def _on_script_changed(self, value: str) -> None:
        self.config.nepali_output_mode = value
        self.config.save()

    def _sync_language_ui(self) -> None:
        self.nepali_box.setVisible(self.ne_card.isChecked())
        have = self.engines.kriti_available()
        if have:
            self.kriti_caption.setText("Kriti by Naamche Labs is on this computer. Nepali stays offline.")
        self.kriti_btn.setVisible(not have and not self._kriti_downloading)

    def _download_kriti(self) -> None:
        from ..stt.kriti_engine import download_kriti

        self._kriti_downloading = True
        self.kriti_btn.hide()
        self.kriti_progress.show()
        self.kriti_caption.setText("Downloading…")

        def worker() -> None:
            ok, msg = download_kriti(self.model_manager.models_dir, lambda f: self._kriti_progress.emit(min(f, 0.99), ""))
            self._kriti_progress.emit(2.0 if ok else -1.0, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_kriti_progress(self, frac: float, msg: str) -> None:
        if frac < 0:
            self._kriti_downloading = False
            self.kriti_progress.hide()
            self.kriti_caption.setText(msg or "Download failed. Check your connection and try again.")
            self.kriti_btn.setText("Try again")
            self.kriti_btn.show()
            return
        self.kriti_progress.setValue(int(min(frac, 1.0) * 100))
        if frac > 1.0:
            self._kriti_downloading = False
            self.kriti_progress.hide()
            if getattr(self.config, "nepali_asr_engine", "kriti") != "kriti":
                self.config.nepali_asr_engine = "kriti"
                self.config.save()
            self._sync_language_ui()
        elif frac < 1.0:
            self.kriti_caption.setText(f"Downloading… {frac * 100:.0f}%")

    # ── Page 3: about you ────────────────────────────────────────────────────

    def _page_about(self) -> QWidget:
        page, body = self._page(
            "What do you do?",
            "Your field's words go into your voice profile, so “push to git” doesn't come out as “push to gate”.",
        )
        host = QWidget()
        flow = FlowLayout(host, spacing=8)
        self.role_chips: Dict[str, QPushButton] = {}
        current = getattr(self.config, "user_role", "")
        for rid, label in [(r.id, r.label) for r in ROLES] + [("other", "Something else")]:
            b = chip(label)
            b.setChecked(rid == current)
            b.clicked.connect(lambda _=False, r=rid: self._select_role(r))
            self.role_chips[rid] = b
            flow.addWidget(b)
        body.addWidget(host)

        body.addSpacing(30)
        body.addWidget(_label("Names and words you use", "eyebrow"))
        body.addSpacing(10)
        existing = [w.strip() for w in (self.config.custom_vocabulary or "").split(",") if w.strip()]
        self.words_input = WordsInput(existing, "Type a name, product or place, then press Return")
        body.addWidget(self.words_input)
        body.addSpacing(6)
        body.addWidget(_label("You'll say the first three during voice setup.", "caption"))

        body.addSpacing(30)
        body.addWidget(_label("How should it write?", "eyebrow"))
        body.addSpacing(10)
        style = getattr(self.config, "prompt_style", "subtle")
        self.style_choice = SegmentedChoice(
            [("subtle", "As I say it"), ("formal", "Polished"), ("concise", "Short")],
            style if style in ("subtle", "formal", "concise") else "subtle",
        )
        body.addWidget(self.style_choice)
        return page

    def _select_role(self, role_id: str) -> None:
        for rid, b in self.role_chips.items():
            b.setChecked(rid == role_id)

    def _selected_role(self) -> str:
        rid = next((r for r, b in self.role_chips.items() if b.isChecked()), "")
        return "" if rid == "other" else rid

    def _save_about(self) -> None:
        self.config.user_role = self._selected_role()
        words = self.words_input.words()
        existing = [w.strip() for w in (self.config.custom_vocabulary or "").split(",") if w.strip()]
        merged = list(dict.fromkeys(existing + words))
        self.config.custom_vocabulary = ", ".join(merged)
        self.config.prompt_style = self.style_choice.value() or "subtle"
        self.config.save()

    # ── Page 4: voice profile ────────────────────────────────────────────────

    def _page_voice(self) -> QWidget:
        page, body = self._page("Read a few sentences", " ", fill=True)
        self.voice_page = page
        self.voice_intro = page.lead_lbl
        body.addStretch(2)

        self.voice_stage = QWidget()
        stage = QVBoxLayout(self.voice_stage)
        stage.setContentsMargins(0, 0, 0, 0)
        stage.setSpacing(0)
        top = QHBoxLayout()
        self.voice_counter = _label("", "eyebrow", wrap=False)
        top.addWidget(self.voice_counter)
        top.addStretch()
        self.meter = LevelMeter()
        top.addWidget(self.meter)
        stage.addLayout(top)
        stage.addSpacing(18)

        self.reading = ReadingView(size=34)
        stage.addWidget(self.reading)
        stage.addSpacing(18)
        self.voice_note = _label("", "caption")
        self.voice_note.setMinimumHeight(20)
        stage.addWidget(self.voice_note)
        stage.addSpacing(30)

        controls = QHBoxLayout()
        controls.setSpacing(18)
        self.pause_btn = _icon_button("Pause", "pause")
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.again_btn = _icon_button("Read again", "refresh")
        self.again_btn.clicked.connect(self._read_again)
        self.skip_sentence_btn = _icon_button("Next sentence", "skip")
        self.skip_sentence_btn.clicked.connect(self._skip_sentence)
        for b in (self.pause_btn, self.again_btn, self.skip_sentence_btn):
            controls.addWidget(b)
        controls.addStretch()
        self.keys_hint = _label("Space pauses · R reads again", "caption", wrap=False)
        controls.addWidget(self.keys_hint)
        self.voice_controls = QWidget()
        self.voice_controls.setLayout(controls)
        stage.addWidget(self.voice_controls)
        body.addWidget(self.voice_stage)
        body.addStretch(3)
        return page

    def _voice_title(self, title: str) -> None:
        self.voice_page.title_lbl.setText(title)

    def _show_intro(self, title: str, text: str) -> None:
        self._voice_title(title)
        self.voice_intro.setText(text)
        self.voice_intro.show()
        self.voice_stage.hide()

    def _enter_voice(self) -> None:
        if self.session is not None:
            self._update_voice_buttons()
            return
        langs = languages_to_profile(self.config.spoken_languages or ["en"])
        has_engine = any(self.engines.candidates(l) for l in langs)
        self.voice_controls.setVisible(False)
        self.meter.set_active(False)
        self.voice_counter.setText("")
        if not langs:
            self._show_intro("Voice setup is for English and Nepali", "Just Talk already works for your languages. You can skip this step.")
            self.next_btn.setText("Continue")
            self._state = "unsupported"
            return
        if not has_engine:
            self._show_intro(
                "Voice setup needs a speech model",
                "Download a speech model in Settings › Voice & Speech, then run setup again from Settings.",
            )
            self.next_btn.setText("Continue")
            self._state = "unsupported"
            return
        self._state = "intro"
        minutes = 2 if len(langs) == 1 else 3
        self._show_intro(
            "Read a few sentences",
            f"About {minutes} minutes, in your normal voice. Words light up as Just Talk hears them, "
            "and it learns which engine understands you best. Recordings stay on this computer.",
        )
        self.next_btn.setText("Start")

    def _start_session(self) -> None:
        if self._state == "unsupported":
            self._go(PAGES.index("ready"))
            return
        langs = languages_to_profile(self.config.spoken_languages or ["en"])
        self.session = ProfileSession(
            langs,
            personal_words=self.words_input.words(),
            role=getattr(self.config, "user_role", ""),
            current_engine={l: self.engines.current(l) for l in langs},
            live_engine={l: self.engines.live_id(l) or "" for l in langs},
        )
        self.voice_intro.hide()
        self.voice_stage.show()
        self.voice_controls.setVisible(True)
        self.back_btn.hide()
        self.skip_btn.setText("Skip voice setup")
        self._state = "between"
        self._next_sentence()

    def _update_voice_buttons(self) -> None:
        done = self.session.done_count if self.session else 0
        self.next_btn.setText("Finish")
        self.next_btn.setEnabled(done >= FINISH_EARLY_AFTER)
        self.pause_btn.setText("Resume" if self._state == "paused" else "Pause")
        self.pause_btn.setIcon(icons.icon("play" if self._state == "paused" else "pause", icons.ICON_MUTED, icons.ICON_MUTED, 16))
        if self.session:
            total = max(self.session.total, done)
            current = min(done + (0 if self._state in ("between", "done") else 1), total)
            self.voice_counter.setText(f"Sentence {max(current, 1)} of {total}")
            self.step_bar.set_current(PAGES.index("voice"), done / max(total, 1))

    def _next_sentence(self) -> None:
        if not self.session or self._state == "paused":
            return
        prompt = self.session.next_prompt()
        if prompt is None:
            self._finish_reading()
            return
        self._prompt = prompt
        self._listen()

    def _listen(self) -> None:
        """Show the current prompt and start recording it."""
        assert self._prompt is not None
        self._advance_timer.stop()
        self.reading.set_sentence(self._prompt.text)
        self.voice_note.setText("")
        title = {
            "role": "Some words from your work",
            "word": "Your own words",
            "followup": "A few more for tricky sounds",
            "extra": "A little more practice",
        }.get(self._prompt.kind, {EN: "Read this in English", NE: "यो नेपालीमा पढ्नुहोस्", MIXED: "Read this the way you'd say it"}[self._prompt.language])
        self._voice_title(title)
        live_id = self.engines.live_id(self._prompt.language)
        if live_id in self._slow_live:
            live_id = None
        self._live = self.engines.get(live_id) if live_id else None
        self._live_id = live_id or ""
        if self._live is not None and self._live_id not in self._warmed:
            self._state = "warming"
            self.voice_note.setText("Getting ready…")
            self._update_voice_buttons()
            live, lid, language = self._live, self._live_id, self._prompt.language

            def warm() -> None:
                try:
                    live.transcribe(np.zeros(8000, dtype=np.float32), language)
                except Exception:
                    pass
                self._warmed.add(lid)
                self._live_warm.emit(True)

            threading.Thread(target=warm, daemon=True).start()
            return
        self._begin_recording()

    def _on_live_warm(self, _ok: bool) -> None:
        if self._state == "warming":
            self._begin_recording()

    def _begin_recording(self) -> None:
        if not self.recorder.start():
            self._state = "problem"
            self.voice_note.setText("Couldn't open the microphone. Check the input device in Settings › Voice & Speech.")
            self.meter.set_active(False)
            self._update_voice_buttons()
            return
        self._token += 1
        self._state = "listening"
        self._take_started = time.monotonic()
        self._speech_sec = 0.0
        self._last_voice = 0.0
        self._levels: List[float] = []
        self._frontier = -1
        self.voice_note.setText("")
        self.meter.set_active(True)
        self._listen_timer.start()
        self._update_voice_buttons()
        if self._live is not None:
            threading.Thread(target=self._live_loop, args=(self._token, self._prompt.language, self._live), daemon=True).start()

    def _live_loop(self, token: int, language: str, engine) -> None:
        last = 0
        while token == self._token and self.recorder.is_recording:
            time.sleep(LIVE_INTERVAL_SEC)
            audio = self.recorder.get_current_audio()
            if audio is None or len(audio) - last < 4000:
                continue
            last = len(audio)
            started = time.monotonic()
            try:
                text = engine.transcribe(audio, language)
            except Exception:
                continue
            if time.monotonic() - started > 3.0:
                self._slow_live.add(engine.id)  # too slow to follow along; later sentences light up after each take
                return
            if token == self._token:
                self._partial_ready.emit(token, text or "")

    def _on_partial(self, token: int, text: str) -> None:
        if token != self._token or self._state != "listening" or not self._prompt:
            return
        score = score_take(self._prompt.text, text, self._prompt.language)
        if score.frontier > self._frontier:
            self._frontier = score.frontier
            self._last_voice = max(self._last_voice, time.monotonic())  # the engine heard new words
        self.reading.set_frontier(self._frontier)

    def _listen_tick(self) -> None:
        if self._state != "listening":
            self._listen_timer.stop()
            return
        now = time.monotonic()
        level = self.recorder.get_audio_level()
        # Raw microphone levels vary a hundredfold between devices and input-volume settings, so
        # speech is judged against this room's noise floor (the quiet gaps between words).
        self._levels = (self._levels + [level])[-LEVEL_WINDOW:]
        noise = float(np.percentile(self._levels, 10))
        self.meter.set_level(min(1.0, level / max(noise * SPEECH_OVER_NOISE * 2.5, MIN_SPEECH_LEVEL * 4)))
        elapsed = now - self._take_started
        if level > max(MIN_SPEECH_LEVEL, noise * SPEECH_OVER_NOISE):
            self._speech_sec += self._listen_timer.interval() / 1000.0
            self._last_voice = now
        spoke = self._speech_sec >= MIN_SPEECH_SEC or self._frontier >= 1
        silence = now - self._last_voice if self._last_voice else elapsed
        all_lit = self._frontier >= len(self._prompt.text.split()) - 1
        if spoke and (silence >= END_SILENCE_SEC or (all_lit and silence >= END_SILENCE_DONE_SEC)):
            self._end_take()
        elif not spoke and elapsed >= NO_SPEECH_SEC:
            self._stop_listening(discard=True)
            self._state = "problem"
            self.voice_note.setText("Didn't hear anything. Check your microphone, then press Read again.")
            self._update_voice_buttons()
        elif elapsed >= MAX_TAKE_SEC:
            self._end_take()

    def _stop_listening(self, discard: bool) -> Optional[np.ndarray]:
        self._listen_timer.stop()
        self.meter.set_active(False)
        self._token += 1
        audio = self.recorder.stop() if self.recorder.is_recording else None
        return None if discard else audio

    def _end_take(self) -> None:
        audio = self._stop_listening(discard=False)
        prompt = self._prompt
        if audio is None or prompt is None:
            return
        problem = _take_problem(audio)
        if problem:
            self._state = "problem"
            self.reading.reset_marks()
            self.voice_note.setText(f"{problem} Then press Read again.")
            self._update_voice_buttons()
            return

        clip_id = uuid.uuid4().hex[:12]
        self._clip_id = clip_id
        self.session.start_take(prompt, clip_id)
        try:
            self._clip_files[clip_id] = save_clip(audio, clip_id)
        except Exception as e:
            print(f"[Onboarding] Couldn't save clip: {e}", file=sys.stderr)
        self._state = "checking"
        self._update_voice_buttons()

        language = prompt.language
        candidates = [c for c in self.engines.candidates(language) if self._engine_failures.get(c.id, 0) < 2]
        keep = {self.engines.current(language), self._live_id}
        for c in [c for c in candidates if c.id not in keep]:
            used = self._compared.setdefault((language, c.id), 0)
            if used >= MAX_COMPARE_TAKES:
                candidates.remove(c)
            else:
                self._compared[(language, c.id)] = used + 1
        live = self._live if self._live_id else None
        jobs = len(candidates) + (0 if live is None or any(c.id == self._live_id for c in candidates) else 1)
        self._pending_jobs += jobs
        self._clip_pending[clip_id] = jobs
        if live is not None:
            self._display_engine[clip_id] = self._live_id
            threading.Thread(target=self._run_job, args=(clip_id, live, audio, language), daemon=True).start()
            candidates = [c for c in candidates if c.id != self._live_id]
        for c in candidates:
            self._jobs.put((clip_id, c, audio, language))
        self._ensure_evaluator()
        if live is None and not candidates:
            self._state = "between"
            self._advance_timer.start(ADVANCE_DELAY_MS)

    def _run_job(self, clip_id: str, engine, audio: np.ndarray, language: str) -> None:
        started = time.monotonic()
        try:
            text = engine.transcribe(audio, language) or ""
        except Exception as e:
            print(f"[Onboarding] {engine.id} failed: {e}", file=sys.stderr)
            text = ""
        if time.monotonic() - started > 12:
            self._engine_failures[engine.id] = 2  # too slow to be anyone's dictation engine; stop asking it
        self._engine_result.emit(clip_id, engine.id, text)

    def _ensure_evaluator(self) -> None:
        if self._eval_thread and self._eval_thread.is_alive():
            return

        def loop() -> None:
            while True:
                job = self._jobs.get()
                if job is None:
                    return
                clip_id, engine, audio, language = job
                if self._engine_failures.get(engine.id, 0) >= 2:
                    self._engine_result.emit(clip_id, "", "")
                    continue
                self._run_job(clip_id, engine, audio, language)

        self._eval_thread = threading.Thread(target=loop, daemon=True)
        self._eval_thread.start()

    def _on_engine_result(self, clip_id: str, engine_id: str, text: str) -> None:
        self._pending_jobs = max(0, self._pending_jobs - 1)
        self._clip_pending[clip_id] = max(0, self._clip_pending.get(clip_id, 1) - 1)
        if self._finished or not self.session:
            return
        if not engine_id:
            self._after_result()
            return
        take = self.session.takes.get(clip_id)
        if take is None:
            self._after_result()
            return  # the take was read again or skipped
        others_heard = any(t.strip() for e, t in take.heard.items() if e != engine_id)
        if not text.strip() and others_heard:
            self._engine_failures[engine_id] = self._engine_failures.get(engine_id, 0) + 1
        elif text.strip():
            self._engine_failures[engine_id] = 0
        score = self.session.add_result(clip_id, engine_id, text)
        display = self._display_engine.get(clip_id) or engine_id
        if display == engine_id and not text.strip() and self._clip_pending.get(clip_id):
            self._display_engine[clip_id] = ""  # nothing heard; show the next engine's result instead
            self._after_result()
            return
        self._display_engine[clip_id] = display
        if clip_id == self._clip_id and engine_id == display and self._state == "checking" and score:
            self.reading.set_marks([w.status for w in score.words])
            if score.accuracy < OFF_SCRIPT_ACCURACY:
                self._state = "problem"
                self.voice_note.setText("That didn't sound like the sentence. Press R to read it again, or go to the next one.")
                self._update_voice_buttons()
                self._after_result()
                return
            slips = [(h, m) for h, m in score.mishearings if is_learnable_mixup(m)][:2]
            if slips:
                self.voice_note.setText("   ".join(f"Heard “{h}” for “{m}”" for h, m in slips))
            elif score.accuracy >= 0.999:
                self.voice_note.setText("Every word heard.")
            self._state = "between"
            self._update_voice_buttons()
            self._advance_timer.start(ADVANCE_DELAY_MS + (700 if slips else 0))
        self._after_result()

    def _after_result(self) -> None:
        if self._current() == "result":
            self._render_result()

    def _toggle_pause(self) -> None:
        if self._state == "paused":
            self._state = "between"
            if self._prompt is not None:
                self._listen()
            else:
                self._next_sentence()
            return
        if self._state in ("listening", "warming", "between", "checking", "problem"):
            self._advance_timer.stop()
            if self._state == "listening":
                self._stop_listening(discard=True)
                self.reading.reset_marks()
            elif self._state in ("between", "checking"):
                self._prompt = None  # resume moves on to the next sentence
            self._state = "paused"
            self.voice_note.setText("Paused. Press Space or Resume when you're ready.")
            self._update_voice_buttons()

    def _read_again(self) -> None:
        if not self.session:
            return
        self._advance_timer.stop()
        if self._state == "listening":
            self._stop_listening(discard=True)
        elif self._state in ("between", "checking", "problem") and self._clip_id and self._prompt:
            if self._clip_id in self.session.takes and self.session.takes[self._clip_id].prompt == self._prompt:
                self.session.discard_take(self._clip_id)
        if self._prompt is None:
            return
        self._state = "between"
        self._listen()

    def _skip_sentence(self) -> None:
        if not self.session:
            return
        self._advance_timer.stop()
        if self._state == "listening":
            self._stop_listening(discard=True)
        self._state = "between"
        self._prompt = None
        self._next_sentence()

    def _finish_reading(self) -> None:
        self._advance_timer.stop()
        if self._state == "listening":
            self._stop_listening(discard=True)
        self._state = "done"
        self._go(PAGES.index("result"))

    # ── Page 5: result ───────────────────────────────────────────────────────

    def _page_result(self) -> QWidget:
        page, body = self._page("Your voice profile", " ")
        self.result_page = page
        self.result_rows = QVBoxLayout()
        self.result_rows.setSpacing(0)
        body.addLayout(self.result_rows)
        return page

    def _clear_results(self) -> None:
        while self.result_rows.count():
            item = self.result_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _render_result(self) -> None:
        self._clear_results()
        lead = self.result_page.lead_lbl
        summaries = self.session.summary() if self.session else []
        if not summaries:
            lead.setText("Nothing to show yet. Read a few sentences to build your profile.")
            self.next_btn.setText("Continue")
            return

        overall = self.session.overall_accuracy() or 0.0
        pending = self._pending_jobs
        if pending:
            lead.setText(f"Comparing speech engines on your voice… {pending} left")
        elif overall >= TARGET_ACCURACY:
            lead.setText(f"Just Talk heard {overall:.0%} of your words right. That's past the {TARGET_ACCURACY:.0%} goal.")
        else:
            lead.setText(f"Just Talk heard {overall:.0%} of your words right. The goal is {TARGET_ACCURACY:.0%}.")
        self.next_btn.setEnabled(pending == 0)
        self.next_btn.setText("Save profile")

        for s in summaries:
            row = QFrame()
            row.setObjectName("hairRow")
            rl = QVBoxLayout(row)
            rl.setContentsMargins(0, 14, 0, 16)
            rl.setSpacing(8)
            head = QHBoxLayout()
            head.addWidget(_label(LANGUAGE_NAMES.get(s.language, s.language), "rowTitle", wrap=False))
            head.addStretch()
            untested = s.current and s.current not in s.accuracy
            head.addWidget(_label(f"with {engine_label(s.in_use)}", "caption", wrap=False))
            head.addSpacing(12)
            head.addWidget(_label(f"{s.in_use_accuracy:.0%}", "rowTitle", wrap=False))
            rl.addLayout(head)
            rl.addWidget(AccuracyBar(s.in_use_accuracy, TARGET_ACCURACY))
            if (s.suggest_switch or untested) and can_apply(self.config, s.language, s.best) and not pending:
                tip = QHBoxLayout()
                tip.addWidget(_label(
                    f"{engine_label(s.current)} didn't respond during setup, so this is {engine_label(s.best)}'s score."
                    if untested else f"{engine_label(s.best)} heard you better: {s.best_accuracy:.0%}.",
                    "caption",
                ), 1)
                use = QPushButton(f"Use {engine_label(s.best)}")
                use.setObjectName("secondaryBtn")
                use.clicked.connect(lambda _=False, lang=s.language, eid=s.best, b=use: self._use_engine(lang, eid, b))
                tip.addWidget(use)
                rl.addLayout(tip)
            self.result_rows.addWidget(row)

        slips = []
        for s in summaries:
            slips += [(h, m) for h, m in s.mishearings if (h, m) not in slips]
        if slips:
            self.result_rows.addSpacing(26)
            self.result_rows.addWidget(_label("Mix-ups found", "eyebrow"))
            self.result_rows.addSpacing(10)
            host = QWidget()
            flow = FlowLayout(host, spacing=8)
            for h, m in slips[:10]:
                c = chip(f"{h}  →  {m}", checkable=False)
                c.setEnabled(False)
                flow.addWidget(c)
            self.result_rows.addWidget(host)
            self.result_rows.addSpacing(8)
            ai_on = bool(getattr(self.config, "gemini_enabled", True)) and not getattr(self.config, "offline_mode", False)
            self.result_rows.addWidget(_label(
                "Just Talk keeps learning from your dictations; mix-ups it sees again are fixed by AI cleanup."
                if ai_on else "Turn on AI cleanup so these can be fixed automatically.",
                "caption",
            ))

        if overall < TARGET_ACCURACY and not pending:
            self.result_rows.addSpacing(26)
            more = QPushButton("Read a few more sentences")
            more.setObjectName("secondaryBtn")
            more.setProperty("size", "large")
            more.clicked.connect(self._keep_training)
            line = QHBoxLayout()
            line.addWidget(more)
            line.addStretch()
            self.result_rows.addLayout(line)

    def _use_engine(self, language: str, engine_id: str, button: QPushButton) -> None:
        changed_main = apply_choice(self.config, language, engine_id)
        self.config.save()
        if changed_main and self.on_engines_changed:
            self.on_engines_changed()
        if self.session:
            self.session.current_engine[language] = engine_id
        button.setText("In use")
        button.setEnabled(False)
        QTimer.singleShot(400, self._render_result)

    def _keep_training(self) -> None:
        if not self.session or not self.session.keep_training():
            self.result_page.lead_lbl.setText("That's every practice sentence for now. Your profile keeps what you've read.")
            return
        self._state = "between"
        self._prompt = None
        self.stack.setCurrentIndex(PAGES.index("voice"))
        self.step_bar.set_current(PAGES.index("voice"))
        self.back_btn.hide()
        self.skip_btn.setVisible(True)
        self.skip_btn.setText("Skip voice setup")
        self.voice_controls.setVisible(True)
        self.voice_intro.hide()
        self.voice_stage.show()
        self._next_sentence()

    def _save_profile(self) -> None:
        if not self.session or not self.session.summary():
            return
        previous = VoiceProfile.load()
        labels = {e: engine_label(e) for s in self.session.summary() for e in s.accuracy}
        profile = self.session.to_profile(labels, self._clip_files, previous)
        try:
            profile.save()
        except Exception as e:
            print(f"[Onboarding] Couldn't save voice profile: {e}", file=sys.stderr)
        if self.learner is not None:
            self.learner.learn_from_setup(profile.mishearings, self.words_input.words())

    # ── Page 6: ready ────────────────────────────────────────────────────────

    def _page_ready(self) -> QWidget:
        key = "fn" if sys.platform == "darwin" else "Right Alt"
        page, body = self._page("You're set.", f"Tap {key} to start talking and tap it again to finish. Your words appear wherever you're typing.")
        row = QHBoxLayout()
        cap = QLabel(key)
        cap.setObjectName("keycap")
        cap.setFont(ThemeManager.font(16, QFont.Weight.DemiBold))
        row.addWidget(cap)
        row.addSpacing(12)
        row.addWidget(_label("Try it in the box below.", "caption"), 1)
        body.addLayout(row)
        body.addSpacing(16)
        self.try_box = QTextEdit()
        self.try_box.setPlaceholderText("Click here, tap your key, and say something.")
        self.try_box.setFixedHeight(120)
        body.addWidget(self.try_box)
        return page
