"""First-run interactive onboarding wizard and tutorial dialog."""

from __future__ import annotations

import os
import sys
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..ai.gemini import GeminiFormatter
from ..audio.recorder import AudioRecorder
from ..config import AppConfig
from ..security import CredentialManager
from ..system.permissions import PermissionsManager
from .theme import ThemeManager


class OnboardingWindow(QDialog):
    """
    5-step interactive onboarding wizard:
    1. Setup checklist & permissions (with restart detection)
    2. "Say Hello" live push-to-talk demo
    3. "Fix as you speak" self-correction walkthrough
    4. Floating pill legend
    5. Menu bar & tray overview
    """

    onboarding_completed = Signal()

    def __init__(
        self,
        config: AppConfig,
        gemini: GeminiFormatter,
        on_complete: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config = config
        self.gemini = gemini
        self.on_complete_callback = on_complete

        self.setWindowTitle("Welcome to Just Talk")
        self.resize(680, 540)
        self.setMinimumSize(600, 480)

        # Center on screen
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.center().y() - self.height() // 2,
            )

        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(16)

        # Top Step Indicator Dots
        self.step_dots_layout = QHBoxLayout()
        self.step_dots_layout.setSpacing(8)
        self.step_dots_layout.addStretch()
        self._dots = []
        for i in range(5):
            dot = QLabel("●")
            dot.setFont(ThemeManager.get_ui_font(10))
            dot.setStyleSheet("color: #30D158;" if i == 0 else "color: #333;")
            self._dots.append(dot)
            self.step_dots_layout.addWidget(dot)
        self.step_dots_layout.addStretch()
        main_layout.addLayout(self.step_dots_layout)

        # Wizard Stack
        self.stack = QStackedWidget()
        self.step1 = self._create_step1_checklist()
        self.step2 = self._create_step2_say_hello()
        self.step3 = self._create_step3_correction()
        self.step4 = self._create_step4_pill_legend()
        self.step5 = self._create_step5_tray_guide()

        self.stack.addWidget(self.step1)
        self.stack.addWidget(self.step2)
        self.stack.addWidget(self.step3)
        self.stack.addWidget(self.step4)
        self.stack.addWidget(self.step5)
        main_layout.addWidget(self.stack, 1)

        # Bottom Navigation Controls
        nav_box = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.setObjectName("secondaryBtn")
        self.back_btn.setEnabled(False)
        self.back_btn.clicked.connect(self._on_back)
        nav_box.addWidget(self.back_btn)

        nav_box.addStretch()

        self.skip_btn = QPushButton("Skip Tutorial")
        self.skip_btn.setObjectName("flatBtn")
        self.skip_btn.clicked.connect(self._finish_onboarding)
        nav_box.addWidget(self.skip_btn)

        self.next_btn = QPushButton("Next →")
        self.next_btn.setObjectName("primaryBtn")
        self.next_btn.clicked.connect(self._on_next)
        nav_box.addWidget(self.next_btn)

        main_layout.addLayout(nav_box)

    def _update_dots(self, current_step: int) -> None:
        for i, dot in enumerate(self._dots):
            if i == current_step:
                dot.setStyleSheet("color: #6C8EEF;")  # active accent
            elif i < current_step:
                dot.setStyleSheet("color: #30D158;")  # completed green
            else:
                dot.setStyleSheet("color: rgba(255, 255, 255, 0.12);")

        self.back_btn.setEnabled(current_step > 0)
        if current_step == 4:
            self.next_btn.setText("Get Started")
            self.skip_btn.hide()
        else:
            self.next_btn.setText("Next →")
            self.skip_btn.show()

    def _on_next(self) -> None:
        idx = self.stack.currentIndex()
        if idx < 4:
            self.stack.setCurrentIndex(idx + 1)
            self._update_dots(idx + 1)
        else:
            self._finish_onboarding()

    def _on_back(self) -> None:
        idx = self.stack.currentIndex()
        if idx > 0:
            self.stack.setCurrentIndex(idx - 1)
            self._update_dots(idx - 1)

    def _finish_onboarding(self) -> None:
        self.config.has_completed_onboarding = True
        self.config.save()
        self.accept()
        if self.on_complete_callback:
            self.on_complete_callback()
        self.onboarding_completed.emit()

    # -------------------------------------------------------------------------
    # Step 1: Permissions & Setup Checklist
    # -------------------------------------------------------------------------

    def _create_step1_checklist(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(14)

        title = QLabel("Setup Checklist")
        title.setFont(ThemeManager.get_display_font(26, weight=QFont.Weight.Bold))
        layout.addWidget(title)

        desc = QLabel("Just Talk requires a few system permissions to capture your speech and insert text into your active applications.")
        desc.setObjectName("mutedLabel")
        desc.setFont(ThemeManager.get_ui_font(13))
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 1. Microphone Card
        mic_card = QFrame()
        mic_card.setObjectName("card")
        mc_layout = QHBoxLayout(mic_card)
        mc_layout.setContentsMargins(14, 12, 14, 12)

        mic_info = QVBoxLayout()
        mic_info.setSpacing(2)
        mic_title = QLabel("Microphone Access")
        mic_title.setFont(ThemeManager.get_ui_font(14, weight=QFont.Weight.DemiBold))
        mic_sub = QLabel("Required to capture push-to-talk audio locally.")
        mic_sub.setObjectName("mutedLabel")
        mic_sub.setFont(ThemeManager.get_ui_font(12))
        mic_info.addWidget(mic_title)
        mic_info.addWidget(mic_sub)
        mc_layout.addLayout(mic_info, 1)

        self.mic_status_lbl = QLabel("Checking...")
        self.mic_status_lbl.setFont(ThemeManager.get_ui_font(12))
        mc_layout.addWidget(self.mic_status_lbl)

        self.req_mic_btn = QPushButton("Request Access")
        self.req_mic_btn.setObjectName("secondaryBtn")
        self.req_mic_btn.clicked.connect(self._request_microphone)
        mc_layout.addWidget(self.req_mic_btn)
        layout.addWidget(mic_card)

        # 2. Accessibility / Input Monitoring Card
        acc_card = QFrame()
        acc_card.setObjectName("card")
        ac_layout = QHBoxLayout(acc_card)
        ac_layout.setContentsMargins(14, 12, 14, 12)

        acc_info = QVBoxLayout()
        acc_info.setSpacing(2)
        acc_title = QLabel("Accessibility & Input Monitoring")
        acc_title.setFont(ThemeManager.get_ui_font(14, weight=QFont.Weight.DemiBold))
        acc_sub = QLabel("Required to detect the Fn/Alt shortcut and paste text into apps.")
        acc_sub.setObjectName("mutedLabel")
        acc_sub.setFont(ThemeManager.get_ui_font(12))
        acc_info.addWidget(acc_title)
        acc_info.addWidget(acc_sub)
        ac_layout.addLayout(acc_info, 1)

        self.acc_status_lbl = QLabel("Checking...")
        self.acc_status_lbl.setFont(ThemeManager.get_ui_font(12))
        ac_layout.addWidget(self.acc_status_lbl)

        self.open_settings_btn = QPushButton("Grant Permission")
        self.open_settings_btn.setObjectName("secondaryBtn")
        self.open_settings_btn.clicked.connect(self._open_accessibility_settings)
        ac_layout.addWidget(self.open_settings_btn)

        # Restart Just Talk button (shown if granted but monitor needs restart)
        self.restart_app_btn = QPushButton("Restart Just Talk")
        self.restart_app_btn.setObjectName("secondaryBtn")
        self.restart_app_btn.setStyleSheet("background-color: #6C8EEF; color: white; border: none;")
        self.restart_app_btn.clicked.connect(self._restart_application)
        self.restart_app_btn.hide()
        ac_layout.addWidget(self.restart_app_btn)

        layout.addWidget(acc_card)

        # 3. macOS Keyboard Setup Card (Mac only)
        if sys.platform == "darwin":
            kb_card = QFrame()
            kb_card.setObjectName("card")
            kc_layout = QHBoxLayout(kb_card)
            kc_layout.setContentsMargins(14, 12, 14, 12)

            kb_info = QVBoxLayout()
            kb_info.setSpacing(2)
            kb_title = QLabel("macOS Globe / Fn Key Setup")
            kb_title.setFont(ThemeManager.get_ui_font(14, weight=QFont.Weight.DemiBold))
            kb_sub = QLabel("Set 'Press Globe key to' to 'Do Nothing' in Keyboard settings so macOS doesn't open emoji picker.")
            kb_sub.setObjectName("mutedLabel")
            kb_sub.setFont(ThemeManager.get_ui_font(12))
            kb_info.addWidget(kb_title)
            kb_info.addWidget(kb_sub)
            kc_layout.addLayout(kb_info, 1)

            open_kb_btn = QPushButton("Keyboard Settings")
            open_kb_btn.setObjectName("secondaryBtn")
            open_kb_btn.clicked.connect(PermissionsManager.open_keyboard_settings)
            kc_layout.addWidget(open_kb_btn)
            layout.addWidget(kb_card)

        # 4. AI Formatting Status Card (Ready out of the box, no asking for key)
        gem_card = QFrame()
        gem_card.setObjectName("surfaceCard")
        gc_layout = QVBoxLayout(gem_card)
        gc_layout.setContentsMargins(14, 12, 14, 12)
        gc_layout.setSpacing(6)

        g_head = QHBoxLayout()
        g_title = QLabel("AI Formatting Engine")
        g_title.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        g_head.addWidget(g_title)

        g_head.addStretch()

        self.ai_badge = QLabel("✓ Connected & Ready")
        self.ai_badge.setFont(ThemeManager.get_ui_font(12, weight=QFont.Weight.Medium))
        self.ai_badge.setStyleSheet("color: #30D158;")
        g_head.addWidget(self.ai_badge)
        gc_layout.addLayout(g_head)

        g_sub = QLabel("Gemini AI formatting is pre-configured and ready. Text will automatically be polished with correct grammar and zero loss.")
        g_sub.setObjectName("mutedLabel")
        g_sub.setFont(ThemeManager.get_ui_font(12))
        gc_layout.addWidget(g_sub)

        # Hidden expandable field if user ever wishes to change key
        self.key_edit_container = QWidget()
        kec_layout = QHBoxLayout(self.key_edit_container)
        kec_layout.setContentsMargins(0, 4, 0, 0)
        self.step1_key_input = QLineEdit()
        self.step1_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.step1_key_input.setPlaceholderText("Paste custom Gemini API key (optional)")
        curr_key = CredentialManager.get_api_key()
        if curr_key:
            self.step1_key_input.setText(curr_key)
        self.step1_key_input.editingFinished.connect(self._save_step1_key)
        kec_layout.addWidget(self.step1_key_input, 1)

        self.step1_test_btn = QPushButton("Test")
        self.step1_test_btn.setObjectName("secondaryBtn")
        self.step1_test_btn.clicked.connect(self._test_step1_key)
        kec_layout.addWidget(self.step1_test_btn)
        gc_layout.addWidget(self.key_edit_container)
        self.key_edit_container.hide()

        toggle_key_btn = QPushButton("Custom API Key (Advanced) ▾")
        toggle_key_btn.setFlat(True)
        toggle_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle_key_btn.setStyleSheet("color: #8E8E93; font-size: 11px; text-align: left; padding: 0;")
        toggle_key_btn.clicked.connect(lambda: self.key_edit_container.setVisible(not self.key_edit_container.isVisible()))
        gc_layout.addWidget(toggle_key_btn)

        layout.addWidget(gem_card)
        layout.addStretch()

        self._check_permissions_status()
        return container

    def _check_permissions_status(self) -> None:
        # Check Microphone
        has_mic, _ = PermissionsManager.check_microphone()
        if has_mic:
            self.mic_status_lbl.setText("✓ Granted")
            self.mic_status_lbl.setStyleSheet("color: #30D158;")
            self.req_mic_btn.hide()
        else:
            self.mic_status_lbl.setText("Action required")
            self.mic_status_lbl.setStyleSheet("color: #FF9F0A;")
            self.req_mic_btn.show()

        # Check Accessibility / Input Monitoring
        has_acc = PermissionsManager.check_accessibility(prompt_if_needed=False)
        if has_acc:
            monitor_working = self._verify_event_monitor()
            if monitor_working:
                self.acc_status_lbl.setText("✓ Granted")
                self.acc_status_lbl.setStyleSheet("color: #30D158;")
                self.open_settings_btn.hide()
                self.restart_app_btn.hide()
            else:
                self.acc_status_lbl.setText("Granted (Restart needed)")
                self.acc_status_lbl.setStyleSheet("color: #FF9F0A;")
                self.open_settings_btn.hide()
                self.restart_app_btn.show()
        else:
            self.acc_status_lbl.setText("Action required")
            self.acc_status_lbl.setStyleSheet("color: #FF9F0A;")
            self.open_settings_btn.show()
            self.restart_app_btn.hide()

    def _verify_event_monitor(self) -> bool:
        """On macOS, test whether Quartz / AppKit event tap is functional."""
        if sys.platform != "darwin":
            return True
        try:
            from Quartz import CGEventSourceCreate, kCGEventSourceStateCombinedSessionState

            source = CGEventSourceCreate(kCGEventSourceStateCombinedSessionState)
            return source is not None
        except Exception:
            return False

    def _request_microphone(self) -> None:
        PermissionsManager.request_microphone()
        QTimer.singleShot(1500, self._check_permissions_status)

    def _open_accessibility_settings(self) -> None:
        PermissionsManager.open_accessibility_settings()
        QTimer.singleShot(2000, self._check_permissions_status)

    def _restart_application(self) -> None:
        """Relaunch Just Talk cleanly after permissions update."""
        python = sys.executable
        os.execl(python, python, *sys.argv)

    def _save_step1_key(self) -> None:
        key = self.step1_key_input.text().strip()
        if key:
            CredentialManager.set_api_key(key)
            self.gemini.set_api_key(key)

    def _test_step1_key(self) -> None:
        key = self.step1_key_input.text().strip()
        if not key:
            return

        self._save_step1_key()
        self.step1_test_btn.setText("Testing...")
        self.step1_test_btn.setEnabled(False)

        def worker():
            res = self.gemini.test_connection(api_key=key, model=self.config.gemini_model)
            QTimer.singleShot(0, lambda: self._on_step1_test_result(res))

        import threading

        threading.Thread(target=worker, daemon=True).start()

    def _on_step1_test_result(self, res) -> None:
        self.step1_test_btn.setText("Test")
        self.step1_test_btn.setEnabled(True)
        if res.success:
            self.ai_badge.setText(f"✓ Connected ({res.latency_ms}ms)")
            self.ai_badge.setStyleSheet("color: #30D158;")
        else:
            self.ai_badge.setText("✗ Connection Error")
            self.ai_badge.setStyleSheet("color: #FF453A;")

    # -------------------------------------------------------------------------
    # Step 2: "Say Hello" Live Demo
    # -------------------------------------------------------------------------

    def _create_step2_say_hello(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(14)

        title = QLabel("Try It: Say Hello")
        title.setFont(ThemeManager.get_display_font(26, weight=QFont.Weight.Bold))
        layout.addWidget(title)

        desc = QLabel("Just Talk is built on push-to-talk: you hold your voice trigger shortcut while speaking, and release it the instant you are done.")
        desc.setObjectName("mutedLabel")
        desc.setFont(ThemeManager.get_ui_font(13))
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Shortcut Display Card
        sc_card = QFrame()
        sc_card.setObjectName("card")
        sc_layout = QVBoxLayout(sc_card)
        sc_layout.setContentsMargins(20, 20, 20, 20)
        sc_layout.setSpacing(12)

        sc_row = QHBoxLayout()
        shortcut_name = "fn" if sys.platform == "darwin" else "Right Alt"
        keycap = QLabel(shortcut_name)
        keycap.setObjectName("keycap")
        keycap.setFont(ThemeManager.get_ui_font(18, weight=QFont.Weight.Bold))
        sc_row.addWidget(keycap)

        inst_layout = QVBoxLayout()
        inst_title = QLabel("Hold this key and say:")
        inst_title.setFont(ThemeManager.get_ui_font(14, weight=QFont.Weight.Medium))
        sample_phrase = QLabel('"Hello Just Talk, this is my first voice test."')
        sample_phrase.setFont(ThemeManager.get_ui_font(14, weight=QFont.Weight.Bold))
        sample_phrase.setStyleSheet("color: #6C8EEF;")
        inst_layout.addWidget(inst_title)
        inst_layout.addWidget(sample_phrase)
        sc_row.addLayout(inst_layout)
        sc_row.addStretch()
        sc_layout.addLayout(sc_row)

        layout.addWidget(sc_card)

        # Interactive Test Sandbox Box
        test_box = QFrame()
        test_box.setObjectName("surfaceCard")
        tb_layout = QVBoxLayout(test_box)
        tb_layout.setContentsMargins(16, 14, 16, 14)
        tb_layout.setSpacing(8)

        tb_lbl = QLabel("Live Transcription Practice Box:")
        tb_lbl.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        tb_layout.addWidget(tb_lbl)

        self.demo_text_input = QTextEdit()
        self.demo_text_input.setPlaceholderText("Click here, hold your shortcut key, and speak...")
        self.demo_text_input.setFixedHeight(75)
        tb_layout.addWidget(self.demo_text_input)

        layout.addWidget(test_box)
        layout.addStretch()
        return container

    # -------------------------------------------------------------------------
    # Step 3: Self-Correction Walkthrough
    # -------------------------------------------------------------------------

    def _create_step3_correction(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(14)

        title = QLabel("Self-Correction & Polish")
        title.setFont(ThemeManager.get_display_font(26, weight=QFont.Weight.Bold))
        layout.addWidget(title)

        desc = QLabel("You don't need to speak in perfect sentences. When you pause or change your mind, Just Talk detects corrections and outputs clean text.")
        desc.setObjectName("mutedLabel")
        desc.setFont(ThemeManager.get_ui_font(13))
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Example Comparison Card
        comp_card = QFrame()
        comp_card.setObjectName("card")
        cc_layout = QVBoxLayout(comp_card)
        cc_layout.setContentsMargins(18, 16, 18, 16)
        cc_layout.setSpacing(12)

        # What you say
        say_lbl = QLabel("WHAT YOU SAY:")
        say_lbl.setObjectName("mutedLabel")
        say_lbl.setFont(ThemeManager.get_mono_font(10))
        cc_layout.addWidget(say_lbl)

        raw_box = QLabel('"Um let\'s schedule the sync for Tuesday, wait, no, Thursday at 3pm."')
        raw_box.setObjectName("surfaceRaised")
        raw_box.setFont(ThemeManager.get_mono_font(12))
        raw_box.setStyleSheet("padding: 10px; border-radius: 6px; color: #ECEDEF;")
        cc_layout.addWidget(raw_box)

        # What gets inserted
        arrow_lbl = QLabel("↓  AUTOMATICALLY CLEANED")
        arrow_lbl.setObjectName("mutedLabel")
        arrow_lbl.setFont(ThemeManager.get_mono_font(10))
        cc_layout.addWidget(arrow_lbl)

        clean_box = QLabel('"Let\'s schedule the sync for Thursday at 3:00 PM."')
        clean_box.setObjectName("surfaceRaised")
        clean_box.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.Medium))
        clean_box.setStyleSheet("padding: 10px; border-radius: 6px; color: #30D158; background-color: rgba(48, 209, 88, 0.08);")
        cc_layout.addWidget(clean_box)

        layout.addWidget(comp_card)

        # Tip Card
        tip_card = QFrame()
        tip_card.setObjectName("surfaceCard")
        tc_layout = QVBoxLayout(tip_card)
        tc_layout.setContentsMargins(14, 12, 14, 12)
        tc_layout.setSpacing(4)

        tip_title = QLabel("Pro Tip: Offline Zero-Loss Safety")
        tip_title.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        tip_desc = QLabel("If you lose internet connection or Gemini is slow, Just Talk automatically inserts your local Whisper speech with clean punctuation. Your dictation is never lost.")
        tip_desc.setObjectName("mutedLabel")
        tip_desc.setFont(ThemeManager.get_ui_font(12))
        tip_desc.setWordWrap(True)
        tc_layout.addWidget(tip_title)
        tc_layout.addWidget(tip_desc)
        layout.addWidget(tip_card)

        layout.addStretch()
        return container

    # -------------------------------------------------------------------------
    # Step 4: Floating Pill Legend
    # -------------------------------------------------------------------------

    def _create_step4_pill_legend(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Floating Pill Indicator")
        title.setFont(ThemeManager.get_display_font(26, weight=QFont.Weight.Bold))
        layout.addWidget(title)

        desc = QLabel("The minimal floating pill appears at the bottom-center of your screen while holding your shortcut key.")
        desc.setObjectName("mutedLabel")
        desc.setFont(ThemeManager.get_ui_font(13))
        layout.addWidget(desc)

        # Legend rows
        legend_card = QFrame()
        legend_card.setObjectName("card")
        lc_layout = QVBoxLayout(legend_card)
        lc_layout.setContentsMargins(16, 14, 16, 14)
        lc_layout.setSpacing(10)

        states = [
            ("🔴  Listening", "#FF453A", "Microphone is recording audio. Live waveform reflects your voice volume."),
            ("🔵  Processing", "#64D2FF", "Whisper transcribes speech and Gemini applies formatting polish."),
            ("🟢  Inserted", "#30D158", "Formatted text successfully pasted directly into your active window."),
            ("🟡  Inserted (offline)", "#FF9F0A", "Speech transcribed on-device and inserted when offline or API paused."),
            ("🔷  Copied to Clipboard", "#6C8EEF", "Placed on clipboard if no active text field was focused."),
        ]

        for name, color, explanation in states:
            row = QHBoxLayout()
            row.setSpacing(12)

            badge = QLabel(name)
            badge.setFont(ThemeManager.get_ui_font(12, weight=QFont.Weight.DemiBold))
            badge.setStyleSheet(f"color: {color}; min-width: 140px;")
            row.addWidget(badge)

            exp = QLabel(explanation)
            exp.setObjectName("mutedLabel")
            exp.setFont(ThemeManager.get_ui_font(12))
            exp.setWordWrap(True)
            row.addWidget(exp, 1)

            lc_layout.addLayout(row)

        layout.addWidget(legend_card)
        layout.addStretch()
        return container

    # -------------------------------------------------------------------------
    # Step 5: Menu Bar & Tray Overview
    # -------------------------------------------------------------------------

    def _create_step5_tray_guide(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(14)

        title = QLabel("You're Ready to Talk")
        title.setFont(ThemeManager.get_display_font(26, weight=QFont.Weight.Bold))
        layout.addWidget(title)

        desc = QLabel("Just Talk stays quietly in your menu bar or system tray, always ready to transcribe whenever you hold your shortcut.")
        desc.setObjectName("mutedLabel")
        desc.setFont(ThemeManager.get_ui_font(13))
        desc.setWordWrap(True)
        layout.addWidget(desc)

        guide_card = QFrame()
        guide_card.setObjectName("card")
        gc_layout = QVBoxLayout(guide_card)
        gc_layout.setContentsMargins(18, 16, 18, 16)
        gc_layout.setSpacing(12)

        items = [
            ("Runs in Menu Bar", "Closing the main window keeps Just Talk listening in the background."),
            ("Global Push-to-Talk", "Press your shortcut anywhere: in Slack, Terminal, Docs, or email."),
            ("History & Sandbox", "Click the menu bar icon anytime to review past dictations or adjust settings."),
        ]

        for header, sub in items:
            row = QVBoxLayout()
            row.setSpacing(2)
            h = QLabel(f"•  {header}")
            h.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
            s = QLabel(f"    {sub}")
            s.setObjectName("mutedLabel")
            s.setFont(ThemeManager.get_ui_font(12))
            row.addWidget(h)
            row.addWidget(s)
            gc_layout.addLayout(row)

        layout.addWidget(guide_card)

        # Final Keycap Reminder
        rem_card = QFrame()
        rem_card.setObjectName("surfaceCard")
        rc_layout = QHBoxLayout(rem_card)
        rc_layout.setContentsMargins(16, 14, 16, 14)
        rc_layout.setSpacing(14)

        shortcut_name = "fn" if sys.platform == "darwin" else "Right Alt"
        keycap = QLabel(shortcut_name)
        keycap.setObjectName("keycap")
        keycap.setFont(ThemeManager.get_ui_font(16, weight=QFont.Weight.Bold))
        rc_layout.addWidget(keycap)

        rem_desc = QLabel("Your voice shortcut is active right now. Hold it anytime to speak!")
        rem_desc.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.Medium))
        rc_layout.addWidget(rem_desc, 1)
        layout.addWidget(rem_card)

        layout.addStretch()
        return container
