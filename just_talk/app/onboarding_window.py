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
    QComboBox,
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
from ..stt.model_manager import TIERS, ModelManager
from ..system.autostart import AutostartManager
from ..system.permissions import PermissionsManager
from .theme import ThemeManager


class OnboardingWindow(QDialog):
    """
    5-step interactive onboarding wizard:
    1. Setup checklist & permissions (with restart detection)
    2. Multilingual speech model & language setup
    3. "Fix as you speak" self-correction walkthrough
    4. Floating pill legend
    5. Menu bar & tray overview
    """

    onboarding_completed = Signal()
    model_progress_signal = Signal(float, str)

    def __init__(
        self,
        config: AppConfig,
        gemini: GeminiFormatter,
        model_manager: Optional[ModelManager] = None,
        on_complete: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config = config
        self.gemini = gemini
        self.model_manager = model_manager or ModelManager()
        self.on_complete_callback = on_complete
        self._is_downloading_model = False
        self.model_progress_signal.connect(self._on_model_progress_update)

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

        self._check_permissions_status()
        self._perm_poll_timer = QTimer(self)
        self._perm_poll_timer.setInterval(1500)
        self._perm_poll_timer.timeout.connect(self._check_permissions_status)
        self._perm_poll_timer.start()

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
            kb_sub = QLabel("Stop macOS from opening the Emoji & Symbols picker when pressing Fn.")
            kb_sub.setObjectName("mutedLabel")
            kb_sub.setFont(ThemeManager.get_ui_font(12))
            kb_info.addWidget(kb_title)
            kb_info.addWidget(kb_sub)
            kc_layout.addLayout(kb_info, 1)

            self.fn_status_lbl = QLabel("Checking...")
            self.fn_status_lbl.setFont(ThemeManager.get_ui_font(12))
            kc_layout.addWidget(self.fn_status_lbl)

            self.fix_fn_btn = QPushButton("1-Click Fix")
            self.fix_fn_btn.setObjectName("secondaryBtn")
            self.fix_fn_btn.setStyleSheet("background-color: #6C8EEF; color: white; border: none; font-weight: bold; padding: 4px 10px;")
            self.fix_fn_btn.clicked.connect(self._fix_fn_emoji)
            kc_layout.addWidget(self.fix_fn_btn)

            open_kb_btn = QPushButton("Settings...")
            open_kb_btn.setObjectName("secondaryBtn")
            open_kb_btn.clicked.connect(PermissionsManager.open_keyboard_settings)
            kc_layout.addWidget(open_kb_btn)
            layout.addWidget(kb_card)

        # 4. Launch at Startup Card
        startup_card = QFrame()
        startup_card.setObjectName("surfaceCard")
        st_layout = QHBoxLayout(startup_card)
        st_layout.setContentsMargins(14, 10, 14, 10)
        self.startup_chk = QCheckBox("Start Just Talk automatically when you log into your computer")
        self.startup_chk.setFont(ThemeManager.get_ui_font(13))
        self.startup_chk.setChecked(self.config.launch_at_startup or True)
        self.startup_chk.toggled.connect(self._on_startup_toggled)
        st_layout.addWidget(self.startup_chk)
        layout.addWidget(startup_card)

        # 5. AI Formatting Status Card (Ready out of the box, no asking for key)
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
            if sys.platform == "win32":
                self.mic_status_lbl.setText("✓ Ready (Auto-granted)")
            else:
                self.mic_status_lbl.setText("✓ Granted")
            self.mic_status_lbl.setStyleSheet("color: #30D158;")
            self.req_mic_btn.hide()
        else:
            self.mic_status_lbl.setText("Action required")
            self.mic_status_lbl.setStyleSheet("color: #FF9F0A;")
            self.req_mic_btn.show()

        # Check Accessibility / Input Monitoring
        if sys.platform == "win32":
            self.acc_status_lbl.setText("✓ Ready (Global Low-Level Hook)")
            self.acc_status_lbl.setStyleSheet("color: #30D158;")
            self.open_settings_btn.hide()
            self.restart_app_btn.hide()
        else:
            has_acc = PermissionsManager.check_accessibility(prompt_if_needed=False)
            has_input = PermissionsManager.check_input_monitoring()
            if has_acc and has_input:
                self.acc_status_lbl.setText("✓ Granted")
                self.acc_status_lbl.setStyleSheet("color: #30D158;")
                self.open_settings_btn.hide()
                self.restart_app_btn.hide()
            elif not has_acc and not has_input:
                self.acc_status_lbl.setText("Accessibility & Input Monitoring required")
                self.acc_status_lbl.setStyleSheet("color: #FF9F0A;")
                self.open_settings_btn.setText("Grant Permissions")
                self.open_settings_btn.show()
                self.restart_app_btn.hide()
            elif not has_acc:
                self.acc_status_lbl.setText("Accessibility required")
                self.acc_status_lbl.setStyleSheet("color: #FF9F0A;")
                self.open_settings_btn.setText("Grant Accessibility")
                self.open_settings_btn.show()
                self.restart_app_btn.hide()
            else:
                self.acc_status_lbl.setText("Input Monitoring required")
                self.acc_status_lbl.setStyleSheet("color: #FF9F0A;")
                self.open_settings_btn.setText("Grant Input Monitoring")
                self.open_settings_btn.show()
                self.restart_app_btn.hide()

        # Check macOS Globe/Fn emoji status
        if sys.platform == "darwin" and hasattr(self, "fn_status_lbl"):
            if PermissionsManager.is_fn_emoji_disabled():
                self.fn_status_lbl.setText("✓ Configured")
                self.fn_status_lbl.setStyleSheet("color: #30D158;")
                self.fix_fn_btn.hide()
            else:
                self.fn_status_lbl.setText("Opens emoji picker")
                self.fn_status_lbl.setStyleSheet("color: #FF9F0A;")
                self.fix_fn_btn.show()

    def _fix_fn_emoji(self) -> None:
        PermissionsManager.disable_fn_emoji_popup()
        self._check_permissions_status()

    def _on_startup_toggled(self, checked: bool) -> None:
        self.config.launch_at_startup = checked
        self.config.save()
        AutostartManager.set_autostart(checked)

    def _verify_event_monitor(self) -> bool:
        """On macOS, test whether Quartz event tap permissions are functional."""
        if sys.platform != "darwin":
            return True
        return PermissionsManager.check_accessibility(prompt_if_needed=False) and PermissionsManager.check_input_monitoring()

    def _request_microphone(self) -> None:
        PermissionsManager.request_microphone()
        QTimer.singleShot(1500, self._check_permissions_status)

    def _open_accessibility_settings(self) -> None:
        has_acc = PermissionsManager.check_accessibility(prompt_if_needed=False)
        has_input = PermissionsManager.check_input_monitoring()
        if not has_acc:
            PermissionsManager.open_accessibility_settings()
        elif not has_input:
            PermissionsManager.open_input_monitoring_settings()
        else:
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
    # Step 2: Multilingual Speech Model & Language Setup
    # -------------------------------------------------------------------------

    def _create_step2_say_hello(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(14)

        title = QLabel("Speech Model & Language")
        title.setFont(ThemeManager.get_display_font(26, weight=QFont.Weight.Bold))
        layout.addWidget(title)

        desc = QLabel("Just Talk transcribes speech 100% locally on your computer with zero latency. No audio is ever sent to cloud servers.")
        desc.setObjectName("mutedLabel")
        desc.setFont(ThemeManager.get_ui_font(13))
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 1. Model Status & Download Progress Card
        model_card = QFrame()
        model_card.setObjectName("card")
        m_layout = QVBoxLayout(model_card)
        m_layout.setContentsMargins(16, 14, 16, 14)
        m_layout.setSpacing(10)

        m_head = QHBoxLayout()
        m_title = QLabel("Multilingual Speech Model (Balanced · 466 MB)")
        m_title.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        m_head.addWidget(m_title)
        m_head.addStretch()

        self.model_status_badge = QLabel("Checking...")
        self.model_status_badge.setFont(ThemeManager.get_ui_font(12, weight=QFont.Weight.Medium))
        m_head.addWidget(self.model_status_badge)
        m_layout.addLayout(m_head)

        m_sub = QLabel("Supports Nepali, English, German, French, Italian, Mandarin, and 90+ languages with high punctuation accuracy.")
        m_sub.setObjectName("mutedLabel")
        m_sub.setFont(ThemeManager.get_ui_font(12))
        m_sub.setWordWrap(True)
        m_layout.addWidget(m_sub)

        # Progress bar
        self.model_progress_bar = QProgressBar()
        self.model_progress_bar.setRange(0, 100)
        self.model_progress_bar.setFixedHeight(8)
        self.model_progress_bar.setTextVisible(False)
        self.model_progress_bar.setStyleSheet("""
            QProgressBar {
                background: rgba(255, 255, 255, 0.08);
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6C8EEF, stop:1 #30D158);
                border-radius: 4px;
            }
        """)
        m_layout.addWidget(self.model_progress_bar)

        btn_row = QHBoxLayout()
        self.model_detail_lbl = QLabel("")
        self.model_detail_lbl.setFont(ThemeManager.get_ui_font(11))
        self.model_detail_lbl.setObjectName("mutedLabel")
        btn_row.addWidget(self.model_detail_lbl, 1)

        self.download_model_btn = QPushButton("Download Model")
        self.download_model_btn.setObjectName("secondaryBtn")
        self.download_model_btn.clicked.connect(self._start_model_download)
        btn_row.addWidget(self.download_model_btn)
        m_layout.addLayout(btn_row)

        layout.addWidget(model_card)

        # 2. Language & Output Mode Card
        lang_card = QFrame()
        lang_card.setObjectName("card")
        l_layout = QVBoxLayout(lang_card)
        l_layout.setContentsMargins(16, 14, 16, 14)
        l_layout.setSpacing(12)

        # Mode Selector (Transcribe vs Translate)
        mode_header = QLabel("Output Mode:")
        mode_header.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        l_layout.addWidget(mode_header)

        mode_row = QHBoxLayout()
        self.mode_transcribe_btn = QPushButton("✍️ Write in My Language")
        self.mode_transcribe_btn.setCheckable(True)
        self.mode_transcribe_btn.setChecked(self.config.speech_mode != "translate")
        self.mode_transcribe_btn.clicked.connect(lambda: self._set_speech_mode("transcribe"))

        self.mode_translate_btn = QPushButton("🌐 Translate to English")
        self.mode_translate_btn.setCheckable(True)
        self.mode_translate_btn.setChecked(self.config.speech_mode == "translate")
        self.mode_translate_btn.clicked.connect(lambda: self._set_speech_mode("translate"))

        self._style_mode_buttons()
        mode_row.addWidget(self.mode_transcribe_btn)
        mode_row.addWidget(self.mode_translate_btn)
        l_layout.addLayout(mode_row)

        # Spoken Language Dropdown
        lang_row = QHBoxLayout()
        lang_lbl = QLabel("Spoken Language:")
        lang_lbl.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        lang_row.addWidget(lang_lbl)

        self.onboarding_lang_combo = QComboBox()
        self.onboarding_lang_combo.addItem("Auto-Detect Language (Recommended)", "auto")
        self.onboarding_lang_combo.addItem("Nepali (नेपाली)", "ne")
        self.onboarding_lang_combo.addItem("English", "en")
        self.onboarding_lang_combo.addItem("German (Deutsch)", "de")
        self.onboarding_lang_combo.addItem("French (Français)", "fr")
        self.onboarding_lang_combo.addItem("Italian (Italiano)", "it")
        self.onboarding_lang_combo.addItem("Mandarin Chinese (中文)", "zh")

        # Select matching item
        cur_lang = getattr(self.config, "language", "auto")
        idx = self.onboarding_lang_combo.findData(cur_lang)
        if idx >= 0:
            self.onboarding_lang_combo.setCurrentIndex(idx)
        self.onboarding_lang_combo.currentIndexChanged.connect(self._on_lang_combo_changed)
        lang_row.addWidget(self.onboarding_lang_combo, 1)
        l_layout.addLayout(lang_row)

        self.mode_explanation_lbl = QLabel("")
        self.mode_explanation_lbl.setObjectName("mutedLabel")
        self.mode_explanation_lbl.setFont(ThemeManager.get_ui_font(12))
        self.mode_explanation_lbl.setWordWrap(True)
        l_layout.addWidget(self.mode_explanation_lbl)

        layout.addWidget(lang_card)

        # 3. Practice & Voice Shortcut Card
        sc_card = QFrame()
        sc_card.setObjectName("surfaceCard")
        sc_layout = QVBoxLayout(sc_card)
        sc_layout.setContentsMargins(16, 14, 16, 14)
        sc_layout.setSpacing(10)

        sc_row = QHBoxLayout()
        shortcut_name = "fn" if sys.platform == "darwin" else "Right Alt"
        keycap = QLabel(shortcut_name)
        keycap.setObjectName("keycap")
        keycap.setFont(ThemeManager.get_ui_font(16, weight=QFont.Weight.Bold))
        sc_row.addWidget(keycap)

        inst_layout = QVBoxLayout()
        inst_title = QLabel("Hold this key and say:")
        inst_title.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.Medium))
        self.sample_phrase = QLabel('"Hello Just Talk, this is my first voice test."')
        self.sample_phrase.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.Bold))
        self.sample_phrase.setStyleSheet("color: #6C8EEF;")
        inst_layout.addWidget(inst_title)
        inst_layout.addWidget(self.sample_phrase)
        sc_row.addLayout(inst_layout)
        sc_row.addStretch()
        sc_layout.addLayout(sc_row)

        self.demo_text_input = QTextEdit()
        self.demo_text_input.setPlaceholderText("Click here, hold your shortcut key, and speak...")
        self.demo_text_input.setFixedHeight(65)
        sc_layout.addWidget(self.demo_text_input)

        layout.addWidget(sc_card)
        layout.addStretch()

        self._update_model_status_display()
        self._update_mode_explanation()
        scroll.setWidget(container)
        return scroll

    def _style_mode_buttons(self) -> None:
        transcribe_active = getattr(self.config, "speech_mode", "transcribe") != "translate"
        if transcribe_active:
            self.mode_transcribe_btn.setStyleSheet("background-color: #6C8EEF; color: white; border: none; font-weight: bold; border-radius: 8px; padding: 10px 14px;")
            self.mode_translate_btn.setStyleSheet("background-color: rgba(255, 255, 255, 0.08); color: #8E8E93; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 10px 14px;")
        else:
            self.mode_transcribe_btn.setStyleSheet("background-color: rgba(255, 255, 255, 0.08); color: #8E8E93; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 10px 14px;")
            self.mode_translate_btn.setStyleSheet("background-color: #6C8EEF; color: white; border: none; font-weight: bold; border-radius: 8px; padding: 10px 14px;")

    def _set_speech_mode(self, mode: str) -> None:
        self.config.speech_mode = mode
        self.config.save()
        self._style_mode_buttons()
        self._update_mode_explanation()

    def _on_lang_combo_changed(self, idx: int) -> None:
        val = self.onboarding_lang_combo.itemData(idx)
        self.config.language = val
        self.config.save()
        self._update_mode_explanation()

    def _update_mode_explanation(self) -> None:
        lang_code = self.onboarding_lang_combo.currentData()
        mode = getattr(self.config, "speech_mode", "transcribe")

        if mode == "translate":
            self.mode_explanation_lbl.setText(
                "Speech will automatically be translated into clear English text, regardless of whether you speak in Nepali, German, French, Italian, or Mandarin."
            )
            if lang_code == "ne":
                self.sample_phrase.setText('"नमस्ते, मलाई अंग्रेजी सिक्न मन छ।" → (types in English)')
            else:
                self.sample_phrase.setText('"Hello Just Talk, translate this into English."')
        else:
            self.mode_explanation_lbl.setText(
                "Speech will be transcribed directly in the spoken language (e.g. Nepali is typed in Devanagari script: नेपाली)."
            )
            if lang_code == "ne":
                self.sample_phrase.setText('"नमस्ते Just Talk, यो मेरो पहिलो आवाज परीक्षण हो।"')
            elif lang_code == "de":
                self.sample_phrase.setText('"Hallo Just Talk, das ist mein erster Sprachtest."')
            elif lang_code == "fr":
                self.sample_phrase.setText('"Bonjour Just Talk, c\'est mon premier test vocal."')
            elif lang_code == "zh":
                self.sample_phrase.setText('"你好 Just Talk，这是我的语音输入测试。"')
            else:
                self.sample_phrase.setText('"Hello Just Talk, this is my first voice test."')

    def _update_model_status_display(self) -> None:
        tier_id = getattr(self.config, "model_tier", "quality")
        is_dl = self.model_manager.is_model_downloaded(tier_id)
        info = self.model_manager.get_tier_info(tier_id)
        if is_dl:
            self.model_status_badge.setText("✓ Ready Locally")
            self.model_status_badge.setStyleSheet("color: #30D158;")
            self.model_progress_bar.setValue(100)
            self.model_detail_lbl.setText("Speech model is downloaded and verified on disk.")
            self.download_model_btn.hide()
        elif self._is_downloading_model:
            self.model_status_badge.setText("Downloading...")
            self.model_status_badge.setStyleSheet("color: #6C8EEF;")
            self.download_model_btn.setEnabled(False)
            self.download_model_btn.setText("Downloading...")
        else:
            self.model_status_badge.setText("Not Downloaded")
            self.model_status_badge.setStyleSheet("color: #FF9F0A;")
            self.model_progress_bar.setValue(0)
            self.model_detail_lbl.setText(f"Click below to download {info.display_name} (~{info.disk_size_mb} MB) for offline speech recognition.")
            self.download_model_btn.show()
            self.download_model_btn.setEnabled(True)
            self.download_model_btn.setText("Download Speech Model")

    def _start_model_download(self) -> None:
        if self._is_downloading_model:
            return
        self._is_downloading_model = True
        self.download_model_btn.setEnabled(False)
        self.download_model_btn.setText("Downloading...")
        self.model_status_badge.setText("Downloading...")
        self.model_status_badge.setStyleSheet("color: #6C8EEF;")

        def worker():
            def progress(pct: float, msg: str):
                self.model_progress_signal.emit(pct, msg)

            tier_id = getattr(self.config, "model_tier", "quality")
            success = self.model_manager.download_model(tier_id, progress_callback=progress)
            if success:
                self.model_progress_signal.emit(100.0, "✓ Model ready!")
            else:
                self.model_progress_signal.emit(-1.0, "Download failed. Please check internet connection.")

        import threading

        threading.Thread(target=worker, daemon=True).start()

    def _on_model_progress_update(self, pct: float, msg: str) -> None:
        if pct < 0:
            self._is_downloading_model = False
            self.model_status_badge.setText("✗ Download Failed")
            self.model_status_badge.setStyleSheet("color: #FF453A;")
            self.model_detail_lbl.setText(msg)
            self.download_model_btn.setEnabled(True)
            self.download_model_btn.setText("Retry Download")
            self.download_model_btn.show()
        elif pct >= 100.0:
            self._is_downloading_model = False
            self.model_progress_bar.setValue(100)
            self.model_status_badge.setText("✓ Ready Locally")
            self.model_status_badge.setStyleSheet("color: #30D158;")
            self.model_detail_lbl.setText("Speech model is downloaded and verified on disk.")
            self.download_model_btn.hide()
        else:
            self.model_progress_bar.setValue(int(pct))
            self.model_status_badge.setText(f"Downloading {pct:.0f}%")
            self.model_status_badge.setStyleSheet("color: #6C8EEF;")
            self.model_detail_lbl.setText(msg)

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
