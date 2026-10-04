"""Full desktop application window with sidebar navigation, Home, History, and Settings."""

from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..ai.gemini import GeminiFormatter
from ..audio.recorder import AudioRecorder
from ..config import AppConfig
from ..database.history import HistoryDatabase, HistoryItem
from ..security import CredentialManager
from ..stt.model_manager import TIERS, ModelManager
from ..system.autostart import AutostartManager
from ..system.clipboard import ClipboardManager
from ..system.permissions import PermissionsManager
from .ai_formatting_view import AIFormattingView
from .language_selector import SearchableLanguageComboBox
from .theme import ThemeManager


class MainWindow(QMainWindow):
    """
    Main desktop window for Just Talk.
    Provides dual-mode behavior: lives in menu bar / system tray, but can open as a
    full native application window with Home, History, and Settings views.
    """

    config_changed = Signal(AppConfig)
    replay_tutorial_requested = Signal()

    def __init__(
        self,
        config: AppConfig,
        db: HistoryDatabase,
        model_manager: ModelManager,
        gemini: GeminiFormatter,
        on_config_changed: Optional[Callable[[AppConfig], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config = config
        self.db = db
        self.model_manager = model_manager
        self.gemini = gemini
        self.on_config_changed_callback = on_config_changed

        self.setWindowTitle("Just Talk")
        self.resize(1160, 760)
        self.setMinimumSize(920, 580)

        # Center on screen
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.center().y() - self.height() // 2,
            )

        self._setup_ui()
        self._refresh_home_status()

        # Timer to keep status and circuit breaker badges fresh
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_home_status)
        self._status_timer.start(5000)

    # -------------------------------------------------------------------------
    # Window Lifecycle & macOS Activation Policy
    # -------------------------------------------------------------------------

    def show_and_activate(self, screen_name: Optional[str] = None) -> None:
        """Show the window, elevate to regular app policy, and focus."""
        if screen_name:
            self.switch_screen(screen_name)
        self.update_activation_policy(is_visible=True)
        self.show()
        self.raise_()
        self.activateWindow()
        if sys.platform == "darwin":
            try:
                from AppKit import NSApp

                NSApp.activateIgnoringOtherApps_(True)
            except Exception:
                pass

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Intercept close: keep background push-to-talk listener and tray alive.
        Switches macOS dock policy back to accessory.
        """
        if getattr(self, "_is_testing_mic", False):
            self._stop_mic_test()
        event.ignore()
        self.hide()
        self.update_activation_policy(is_visible=False)

    def update_activation_policy(self, is_visible: bool) -> None:
        """Dynamically toggle macOS Dock icon presence."""
        if sys.platform == "darwin":
            try:
                from AppKit import (
                    NSApp,
                    NSApplicationActivationPolicyAccessory,
                    NSApplicationActivationPolicyRegular,
                )

                policy = (
                    NSApplicationActivationPolicyRegular
                    if is_visible
                    else NSApplicationActivationPolicyAccessory
                )
                NSApp.setActivationPolicy_(policy)
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # UI Construction
    # -------------------------------------------------------------------------

    def _setup_ui(self) -> None:
        central_widget = QWidget(self)
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Left Sidebar
        sidebar = self._create_sidebar()
        root_layout.addWidget(sidebar)

        # Hairline divider
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setObjectName("hairline")
        divider.setFixedWidth(1)
        root_layout.addWidget(divider)

        # 2. Main Stack Area
        self.stack = QStackedWidget()
        self.home_view = self._create_home_view()
        self.history_view = self._create_history_view()
        self.settings_view = self._create_settings_view()

        self.stack.addWidget(self.home_view)
        self.stack.addWidget(self.history_view)
        self.stack.addWidget(self.settings_view)

        root_layout.addWidget(self.stack, 1)

    def _create_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(130)
        sidebar.setObjectName("sidebar")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 18, 10, 12)
        layout.setSpacing(2)

        # App Brand
        brand_layout = QHBoxLayout()
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(8)

        icon_label = QLabel()
        asset_icon = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
        if asset_icon.exists():
            pix = QPixmap(str(asset_icon)).scaled(
                26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            icon_label.setPixmap(pix)
            brand_layout.addWidget(icon_label)

        title_vbox = QVBoxLayout()
        title_vbox.setContentsMargins(0, 0, 0, 0)
        title_vbox.setSpacing(0)
        title = QLabel("Just Talk")
        title.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.Bold))
        subtitle = QLabel("v1.0")
        subtitle.setObjectName("mutedLabel")
        subtitle.setFont(ThemeManager.get_ui_font(10))
        title_vbox.addWidget(title)
        title_vbox.addWidget(subtitle)
        brand_layout.addLayout(title_vbox)
        brand_layout.addStretch()

        layout.addLayout(brand_layout)
        layout.addSpacing(18)

        # Navigation Buttons
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.nav_home = QPushButton("⌂  Home")
        self.nav_home.setObjectName("navBtn")
        self.nav_home.setCheckable(True)
        self.nav_home.setChecked(True)
        self.nav_home.clicked.connect(lambda: self.switch_screen("home"))
        self.nav_group.addButton(self.nav_home, 0)
        layout.addWidget(self.nav_home)

        self.nav_history = QPushButton("⏱  History")
        self.nav_history.setObjectName("navBtn")
        self.nav_history.setCheckable(True)
        self.nav_history.clicked.connect(lambda: self.switch_screen("history"))
        self.nav_group.addButton(self.nav_history, 1)
        layout.addWidget(self.nav_history)

        self.nav_settings = QPushButton("⚙  Settings")
        self.nav_settings.setObjectName("navBtn")
        self.nav_settings.setCheckable(True)
        self.nav_settings.clicked.connect(lambda: self.switch_screen("settings"))
        self.nav_group.addButton(self.nav_settings, 2)
        layout.addWidget(self.nav_settings)

        layout.addStretch()

        # Bottom Status
        status_row = QHBoxLayout()
        status_row.setSpacing(5)
        status_row.setContentsMargins(2, 0, 2, 0)

        self.sidebar_dot = QLabel("●")
        self.sidebar_dot.setFont(ThemeManager.get_ui_font(7))
        self.sidebar_dot.setStyleSheet("color: #30D158;")
        status_row.addWidget(self.sidebar_dot)

        self.sidebar_status_text = QLabel("Ready")
        self.sidebar_status_text.setFont(ThemeManager.get_ui_font(11))
        status_row.addWidget(self.sidebar_status_text)
        status_row.addStretch()
        layout.addLayout(status_row)

        self.sidebar_key_label = QLabel(self._get_shortcut_display())
        self.sidebar_key_label.setObjectName("mutedLabel")
        self.sidebar_key_label.setFont(ThemeManager.get_mono_font(10))
        self.sidebar_key_label.setContentsMargins(2, 2, 0, 4)
        layout.addWidget(self.sidebar_key_label)

        return sidebar

    def switch_screen(self, screen_name: str) -> None:
        """Switch active screen in stacked widget."""
        name = screen_name.lower()
        if name == "home":
            self.stack.setCurrentIndex(0)
            self.nav_home.setChecked(True)
            self._refresh_home_status()
        elif name == "history":
            self.stack.setCurrentIndex(1)
            self.nav_history.setChecked(True)
            self._load_history_data()
        elif name == "settings":
            self.stack.setCurrentIndex(2)
            self.nav_settings.setChecked(True)

    # -------------------------------------------------------------------------
    # Screen 1: Home View
    # -------------------------------------------------------------------------

    def _create_home_view(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setSpacing(16)

        # Large greeting heading — Typeless style
        greeting_text = self._get_time_greeting()
        self.greeting_label = QLabel(greeting_text)
        self.greeting_label.setFont(ThemeManager.get_display_font(32, weight=QFont.Weight.Bold))
        layout.addWidget(self.greeting_label)

        subtitle = QLabel("Just Talk is warm in RAM and ready to transcribe.")
        subtitle.setObjectName("mutedLabel")
        subtitle.setFont(ThemeManager.get_ui_font(13))
        layout.addWidget(subtitle)
        layout.addSpacing(6)

        # Push-to-Talk Hero Keycap Card
        hero_card = QFrame()
        hero_card.setObjectName("card")
        hero_layout = QVBoxLayout(hero_card)
        hero_layout.setContentsMargins(18, 16, 18, 16)
        hero_layout.setSpacing(10)

        hero_header = QHBoxLayout()
        hero_title = QLabel("Push-to-Talk Shortcut")
        hero_title.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        hero_header.addWidget(hero_title)
        hero_header.addStretch()
        hero_layout.addLayout(hero_header)

        keycap_row = QHBoxLayout()
        keycap_row.setSpacing(12)

        self.hero_keycap = QLabel(self._get_shortcut_display())
        self.hero_keycap.setObjectName("keycap")
        self.hero_keycap.setFont(ThemeManager.get_mono_font(14, weight=QFont.Weight.Bold))
        keycap_row.addWidget(self.hero_keycap)

        hero_desc_layout = QVBoxLayout()
        hero_desc_layout.setSpacing(2)
        hero_desc = QLabel("Hold to talk · Release to insert")
        hero_desc.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.Medium))
        hero_desc_sub = QLabel("Speaks into Slack, VS Code, Chrome, or any focused application.")
        hero_desc_sub.setObjectName("mutedLabel")
        hero_desc_sub.setFont(ThemeManager.get_ui_font(12))
        hero_desc_layout.addWidget(hero_desc)
        hero_desc_layout.addWidget(hero_desc_sub)

        keycap_row.addLayout(hero_desc_layout)
        keycap_row.addStretch()
        hero_layout.addLayout(keycap_row)

        layout.addWidget(hero_card)

        # macOS Fn Key Emoji Assistant Alert Banner
        if sys.platform == "darwin":
            self.home_fn_alert_card = QFrame()
            self.home_fn_alert_card.setObjectName("surfaceCard")
            hfa_layout = QHBoxLayout(self.home_fn_alert_card)
            hfa_layout.setContentsMargins(14, 10, 14, 10)

            self.home_fn_msg = QLabel("")
            self.home_fn_msg.setFont(ThemeManager.get_ui_font(12))
            hfa_layout.addWidget(self.home_fn_msg, 1)

            self.home_fn_fix_btn = QPushButton("1-Click Fix")
            self.home_fn_fix_btn.setObjectName("secondaryBtn")
            self.home_fn_fix_btn.setStyleSheet("background-color: #6C8EEF; color: white; border: none; font-weight: bold; padding: 4px 10px;")
            self.home_fn_fix_btn.clicked.connect(self._on_home_fix_fn_clicked)
            hfa_layout.addWidget(self.home_fn_fix_btn)
            layout.addWidget(self.home_fn_alert_card)

        # Multilingual Language & Speech Mode Card
        mode_card = QFrame()
        mode_card.setObjectName("card")
        mc_layout = QVBoxLayout(mode_card)
        mc_layout.setContentsMargins(18, 16, 18, 16)
        mc_layout.setSpacing(12)

        mc_head = QHBoxLayout()
        mc_title = QLabel("SPEECH LANGUAGE & DUAL OUTPUT MODE")
        mc_title.setFont(ThemeManager.get_mono_font(11, weight=QFont.Weight.Bold))
        mc_title.setObjectName("mutedLabel")
        mc_head.addWidget(mc_title)
        mc_head.addStretch()
        mc_layout.addLayout(mc_head)

        mode_btn_row = QHBoxLayout()
        mode_btn_row.setSpacing(10)
        self.home_mode_transcribe_btn = QPushButton("✍️ Write in My Language")
        self.home_mode_transcribe_btn.setCheckable(True)
        self.home_mode_transcribe_btn.setChecked(getattr(self.config, "speech_mode", "transcribe") != "translate")
        self.home_mode_transcribe_btn.clicked.connect(lambda: self._set_home_speech_mode("transcribe"))

        self.home_mode_translate_btn = QPushButton("🌐 Translate to English")
        self.home_mode_translate_btn.setCheckable(True)
        self.home_mode_translate_btn.setChecked(getattr(self.config, "speech_mode", "transcribe") == "translate")
        self.home_mode_translate_btn.clicked.connect(lambda: self._set_home_speech_mode("translate"))

        self._style_home_mode_buttons()
        mode_btn_row.addWidget(self.home_mode_transcribe_btn)
        mode_btn_row.addWidget(self.home_mode_translate_btn)
        mc_layout.addLayout(mode_btn_row)

        # Spoken Language Dropdown
        lang_row = QHBoxLayout()
        lang_lbl = QLabel("Spoken Language:")
        lang_lbl.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.Medium))
        lang_row.addWidget(lang_lbl)

        self.home_lang_combo = SearchableLanguageComboBox()
        cur_lang = getattr(self.config, "language", "en")
        self.home_lang_combo.set_current_language(cur_lang)
        self.home_lang_combo.language_changed.connect(self._on_home_lang_changed)
        lang_row.addWidget(self.home_lang_combo, 1)
        mc_layout.addLayout(lang_row)

        self.home_mode_desc = QLabel("")
        self.home_mode_desc.setObjectName("mutedLabel")
        self.home_mode_desc.setFont(ThemeManager.get_ui_font(12))
        self.home_mode_desc.setWordWrap(True)
        mc_layout.addWidget(self.home_mode_desc)

        layout.addWidget(mode_card)

        # Status Cards Row (Speech Engine, AI Formatter, Audio Input)
        status_row = QHBoxLayout()
        status_row.setSpacing(10)

        self.model_card = self._create_mini_status_card("SPEECH ENGINE", "Whisper", "Ready")
        self.gemini_card = self._create_mini_status_card("AI FORMATTING", "Gemini", "Active")
        self.audio_card = self._create_mini_status_card("INPUT DEVICE", "Microphone", "Default")

        status_row.addWidget(self.model_card)
        status_row.addWidget(self.gemini_card)
        status_row.addWidget(self.audio_card)
        layout.addLayout(status_row)

        # "Try It Here" Live Dictation Sandbox
        practice_card = QFrame()
        practice_card.setObjectName("card")
        practice_layout = QVBoxLayout(practice_card)
        practice_layout.setContentsMargins(16, 14, 16, 14)
        practice_layout.setSpacing(8)

        practice_header = QHBoxLayout()
        p_title = QLabel("Try It Here")
        p_title.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        practice_header.addWidget(p_title)

        practice_header.addStretch()
        clear_test_btn = QPushButton("Clear")
        clear_test_btn.setObjectName("secondaryBtn")
        clear_test_btn.clicked.connect(lambda: self.practice_text.clear())
        practice_header.addWidget(clear_test_btn)
        practice_layout.addLayout(practice_header)

        practice_sub = QLabel("Focus the box below, hold your voice shortcut, and speak. Watch text format and appear instantly.")
        practice_sub.setObjectName("mutedLabel")
        practice_sub.setFont(ThemeManager.get_ui_font(12))
        practice_sub.setWordWrap(True)
        practice_layout.addWidget(practice_sub)

        self.practice_text = QTextEdit()
        self.practice_text.setPlaceholderText("Click here and hold your voice key to practice...")
        self.practice_text.setFixedHeight(80)
        practice_layout.addWidget(self.practice_text)

        layout.addWidget(practice_card)

        # Recent Dictations Card
        recent_card = QFrame()
        recent_card.setObjectName("card")
        recent_layout = QVBoxLayout(recent_card)
        recent_layout.setContentsMargins(16, 14, 16, 14)
        recent_layout.setSpacing(10)

        recent_header = QHBoxLayout()
        recent_title = QLabel("Recent Dictations")
        recent_title.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        recent_header.addWidget(recent_title)

        recent_header.addStretch()
        view_all_btn = QPushButton("View all in History →")
        view_all_btn.setObjectName("flatBtn")
        view_all_btn.clicked.connect(lambda: self.switch_screen("history"))
        recent_header.addWidget(view_all_btn)
        recent_layout.addLayout(recent_header)

        self.recent_items_layout = QVBoxLayout()
        self.recent_items_layout.setSpacing(6)
        recent_layout.addLayout(self.recent_items_layout)

        layout.addWidget(recent_card)
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _create_mini_status_card(self, tag: str, title: str, status: str) -> QFrame:
        card = QFrame()
        card.setObjectName("surfaceCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)

        tag_lbl = QLabel(tag)
        tag_lbl.setObjectName("mutedLabel")
        tag_lbl.setFont(ThemeManager.get_ui_font(10, weight=QFont.Weight.Medium))
        layout.addWidget(tag_lbl)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("cardTitle")
        title_lbl.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        title_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)

        status_lbl = QLabel(status)
        status_lbl.setObjectName("cardStatus")
        status_lbl.setFont(ThemeManager.get_ui_font(11))
        status_lbl.setWordWrap(True)
        layout.addWidget(status_lbl)

        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        card.status_label = status_lbl
        card.title_label = title_lbl
        return card

    def _refresh_home_status(self) -> None:
        """Update live status labels and recent history on Home screen."""
        # 1. Speech engine
        tier_info = TIERS.get(self.config.model_tier)
        short_name = tier_info.model_name.upper() if tier_info else "QUALITY"
        is_dl = self.model_manager.is_model_downloaded(self.config.model_tier)
        self.model_card.title_label.setText(f"Whisper {short_name}")
        self.model_card.status_label.setText("Ready Locally" if is_dl else "Not Downloaded")

        # Update macOS Fn Key and global permissions status if banner is present
        if sys.platform == "darwin" and hasattr(self, "home_fn_alert_card"):
            acc_ok = PermissionsManager.check_accessibility(prompt_if_needed=False)
            input_ok = PermissionsManager.check_input_monitoring()
            fn_ok = PermissionsManager.is_fn_emoji_disabled()

            if not acc_ok or not input_ok:
                missing = []
                if not acc_ok:
                    missing.append("Accessibility")
                if not input_ok:
                    missing.append("Input Monitoring")
                self.home_fn_msg.setText(f"⚠️ Permissions required: {', '.join(missing)} needed for global hold-to-talk.")
                self.home_fn_msg.setStyleSheet("color: #FF9F0A;")
                self.home_fn_fix_btn.setText("Grant Permission")
                self.home_fn_fix_btn.show()
            elif not fn_ok:
                self.home_fn_msg.setText("⚠️ Pressing Fn opens macOS Emoji window.")
                self.home_fn_msg.setStyleSheet("color: #FF9F0A;")
                self.home_fn_fix_btn.setText("1-Click Fix")
                self.home_fn_fix_btn.show()
            else:
                self.home_fn_msg.setText("✓ Global shortcuts active across all applications.")
                self.home_fn_msg.setStyleSheet("color: #30D158;")
                self.home_fn_fix_btn.hide()

        if hasattr(self, "home_mode_desc"):
            self._update_home_mode_desc()

        # 2. AI Formatting & Circuit Breaker
        if self.config.offline_mode:
            self.gemini_card.title_label.setText("Pure Offline")
            self.gemini_card.status_label.setText("Speech never sent out")
            self.sidebar_dot.setStyleSheet("color: #8E8E93;")
            self.sidebar_status_text.setText("Offline")
        elif not self.config.gemini_enabled:
            self.gemini_card.title_label.setText("Raw STT Only")
            self.gemini_card.status_label.setText("AI formatting disabled")
            self.sidebar_dot.setStyleSheet("color: #8E8E93;")
            self.sidebar_status_text.setText("Ready (Raw)")
        elif self.gemini.circuit_breaker.is_paused:
            rem = self.gemini.circuit_breaker.remaining_cooldown_sec
            self.gemini_card.title_label.setText("Circuit Breaker")
            self.gemini_card.status_label.setText(f"Paused ({rem}s remaining)")
            self.sidebar_dot.setStyleSheet("color: #FF9F0A;")  # macOS amber
            self.sidebar_status_text.setText("AI Paused")
        else:
            pid = getattr(self.config, "ai_provider", "gemini") or "gemini"
            from ..ai.providers import get_provider
            p = get_provider(pid)
            p_name = p.display_name if p else "AI"
            active_model = getattr(self.config, "ai_model", "") or self.config.gemini_model
            self.gemini_card.title_label.setText(f"{p_name} Active")
            self.gemini_card.status_label.setText(active_model)
            self.sidebar_dot.setStyleSheet("color: #30D158;")  # macOS green
            self.sidebar_status_text.setText("Ready")

        # 3. Audio input
        self.audio_card.title_label.setText("Microphone")
        dev_idx = self.config.audio_device_index
        if dev_idx is None:
            self.audio_card.status_label.setText("Default System Device")
        else:
            self.audio_card.status_label.setText(f"Device #{dev_idx}")

        # 4. Update shortcut display
        sc_text = self._get_shortcut_display()
        self.hero_keycap.setText(sc_text)
        self.sidebar_key_label.setText(sc_text)

        # 5. Populate recent history snippets
        self._populate_recent_home_items()

    def _populate_recent_home_items(self) -> None:
        # Clear existing
        while self.recent_items_layout.count():
            item = self.recent_items_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        recent = self.db.get_recent(limit=3)
        if not recent:
            empty_lbl = QLabel("No dictations yet. Hold your shortcut to speak!")
            empty_lbl.setObjectName("mutedLabel")
            empty_lbl.setFont(ThemeManager.get_ui_font(12))
            self.recent_items_layout.addWidget(empty_lbl)
            return

        for item in recent:
            row = QFrame()
            row.setObjectName("surfaceRaised")
            r_layout = QHBoxLayout(row)
            r_layout.setContentsMargins(12, 10, 12, 10)
            r_layout.setSpacing(10)

            # Meta badge
            app_lbl = QLabel(item.application or "App")
            app_lbl.setObjectName("badge")
            app_lbl.setFont(ThemeManager.get_mono_font(10))
            r_layout.addWidget(app_lbl)

            # Truncated text
            txt = item.processed_text.replace("\n", " ").strip()
            if len(txt) > 65:
                txt = txt[:65] + "…"
            text_lbl = QLabel(txt)
            text_lbl.setFont(ThemeManager.get_ui_font(13))
            r_layout.addWidget(text_lbl, 1)

            # Quick copy
            copy_btn = QPushButton("Copy")
            copy_btn.setObjectName("secondaryBtn")
            copy_btn.setFixedHeight(26)
            copy_btn.clicked.connect(lambda _, t=item.processed_text: self._copy_text(t))
            r_layout.addWidget(copy_btn)

            self.recent_items_layout.addWidget(row)

    # -------------------------------------------------------------------------
    # Screen 2: History View
    # -------------------------------------------------------------------------

    def _create_history_view(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(36, 30, 36, 28)
        layout.setSpacing(14)

        # Header Bar
        header = QHBoxLayout()
        title = QLabel("History")
        title.setFont(ThemeManager.get_display_font(28, weight=QFont.Weight.Bold))
        header.addWidget(title)
        header.addStretch()

        clear_btn = QPushButton("Clear History…")
        clear_btn.setObjectName("secondaryBtn")
        clear_btn.clicked.connect(self._on_clear_history)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        # Search Bar & Filter Chips
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search transcription text, app name, or dates…")
        self.history_search.textChanged.connect(self._on_search_history)
        filter_bar.addWidget(self.history_search, 1)

        self.filter_all_btn = QPushButton("All")
        self.filter_all_btn.setObjectName("chipBtn")
        self.filter_all_btn.setCheckable(True)
        self.filter_all_btn.setChecked(True)
        self.filter_all_btn.clicked.connect(lambda: self._set_history_filter("all"))
        filter_bar.addWidget(self.filter_all_btn)

        self.filter_formatted_btn = QPushButton("Formatted")
        self.filter_formatted_btn.setObjectName("chipBtn")
        self.filter_formatted_btn.setCheckable(True)
        self.filter_formatted_btn.clicked.connect(lambda: self._set_history_filter("formatted"))
        filter_bar.addWidget(self.filter_formatted_btn)

        self.filter_offline_btn = QPushButton("Offline / Raw")
        self.filter_offline_btn.setObjectName("chipBtn")
        self.filter_offline_btn.setCheckable(True)
        self.filter_offline_btn.clicked.connect(lambda: self._set_history_filter("offline"))
        filter_bar.addWidget(self.filter_offline_btn)

        self._history_filter = "all"
        layout.addLayout(filter_bar)

        # Splitter: Table on left, Detail inspector on right
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("historySplitter")
        splitter.setHandleWidth(1)

        # Table widget
        self.history_table = QTableWidget(0, 3)
        self.history_table.setHorizontalHeaderLabels(["Time", "Target App", "Dictation"])
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setShowGrid(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.itemSelectionChanged.connect(self._on_history_selection_changed)
        splitter.addWidget(self.history_table)

        # Detail Panel
        detail_card = QFrame()
        detail_card.setObjectName("card")
        d_layout = QVBoxLayout(detail_card)
        d_layout.setContentsMargins(14, 14, 14, 14)
        d_layout.setSpacing(8)

        self.detail_meta = QLabel("Select an entry to view details.")
        self.detail_meta.setObjectName("mutedLabel")
        self.detail_meta.setFont(ThemeManager.get_ui_font(11))
        self.detail_meta.setWordWrap(True)
        d_layout.addWidget(self.detail_meta)

        fmt_label = QLabel("Formatted Output")
        fmt_label.setFont(ThemeManager.get_ui_font(11, weight=QFont.Weight.DemiBold))
        fmt_label.setObjectName("mutedLabel")
        d_layout.addWidget(fmt_label)
        self.detail_formatted = QTextEdit()
        self.detail_formatted.setReadOnly(True)
        self.detail_formatted.setFont(ThemeManager.get_ui_font(13))
        d_layout.addWidget(self.detail_formatted, 2)

        raw_label = QLabel("Raw Whisper Transcription")
        raw_label.setFont(ThemeManager.get_ui_font(11, weight=QFont.Weight.DemiBold))
        raw_label.setObjectName("mutedLabel")
        d_layout.addWidget(raw_label)
        self.detail_raw = QTextEdit()
        self.detail_raw.setReadOnly(True)
        self.detail_raw.setFont(ThemeManager.get_mono_font(12))
        self.detail_raw.setFixedHeight(72)
        d_layout.addWidget(self.detail_raw, 1)

        copy_full_btn = QPushButton("Copy Formatted Text")
        copy_full_btn.setObjectName("primaryBtn")
        copy_full_btn.clicked.connect(self._copy_selected_history)
        d_layout.addWidget(copy_full_btn)

        splitter.addWidget(detail_card)
        splitter.setSizes([460, 340])
        layout.addWidget(splitter, 1)

        return container

    def _load_history_data(self) -> None:
        self._history_items = self.db.get_recent(limit=250)
        self._apply_history_filtering()

    def _set_history_filter(self, filter_name: str) -> None:
        self._history_filter = filter_name
        self.filter_all_btn.setChecked(filter_name == "all")
        self.filter_formatted_btn.setChecked(filter_name == "formatted")
        self.filter_offline_btn.setChecked(filter_name == "offline")
        self._apply_history_filtering()

    def _on_search_history(self, text: str) -> None:
        if not text.strip():
            self._load_history_data()
            return
        self._history_items = self.db.search(text.strip())
        self._apply_history_filtering()

    def _apply_history_filtering(self) -> None:
        filtered = []
        for it in getattr(self, "_history_items", []):
            if self._history_filter == "formatted":
                if it.processed_text == it.raw_transcription:
                    continue
            elif self._history_filter == "offline":
                if "offline" not in it.status.lower() and it.processed_text != it.raw_transcription:
                    continue
            filtered.append(it)

        self._filtered_history_items = filtered
        self.history_table.setRowCount(len(filtered))

        for row, item in enumerate(filtered):
            self.history_table.setItem(row, 0, QTableWidgetItem(item.formatted_time))
            self.history_table.setItem(row, 1, QTableWidgetItem(item.application or "Unknown"))
            preview = item.processed_text.replace("\n", " ").strip()
            self.history_table.setItem(row, 2, QTableWidgetItem(preview))

        if filtered:
            self.history_table.selectRow(0)
        else:
            self.detail_formatted.clear()
            self.detail_raw.clear()
            self.detail_meta.setText("No entries matching your filter.")

    def _on_history_selection_changed(self) -> None:
        rows = self.history_table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        if 0 <= row < len(getattr(self, "_filtered_history_items", [])):
            item = self._filtered_history_items[row]
            self.detail_formatted.setPlainText(item.processed_text)
            self.detail_raw.setPlainText(item.raw_transcription)
            self.detail_meta.setText(
                f"App: {item.application or 'Unknown'}  ·  Duration: {item.duration_ms}ms  ·  Status: {item.status.capitalize()}"
            )

    def _copy_selected_history(self) -> None:
        text = self.detail_formatted.toPlainText()
        if text:
            self._copy_text(text)

    def _copy_text(self, text: str) -> None:
        ClipboardManager.set_text(text)
        QMessageBox.information(self, "Copied", "Text copied to clipboard.")

    def _on_clear_history(self) -> None:
        reply = QMessageBox.question(
            self,
            "Clear History",
            "Are you sure you want to permanently clear all dictation records?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.clear()
            self._load_history_data()
            self._refresh_home_status()

    # -------------------------------------------------------------------------
    # Screen 3: Settings View
    # -------------------------------------------------------------------------

    def _create_settings_view(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setSpacing(18)

        # Header
        header = QLabel("Settings")
        header.setFont(ThemeManager.get_display_font(28, weight=QFont.Weight.Bold))
        layout.addWidget(header)

        # Section 1: General & Shortcuts
        sec1, sec1_layout = self._create_settings_section("Trigger & General")
        s1_form = QFormLayout()
        s1_form.setSpacing(12)
        s1_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        s1_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.shortcut_combo = QComboBox()
        if sys.platform == "darwin":
            self.shortcut_combo.addItem("Function / Globe Key (Fn) [Recommended]", "fn")
            self.shortcut_combo.addItem("Right Option Key", "right_alt")
            self.shortcut_combo.addItem("Control + Space", "ctrl_space")
            self.shortcut_combo.addItem("Option + Space", "alt_space")
            self.shortcut_combo.addItem("Control + Shift + Space", "ctrl_shift_space")
        else:
            self.shortcut_combo.addItem("Right Alt Key [Recommended]", "right_alt")
            self.shortcut_combo.addItem("Control + Space", "ctrl_space")
            self.shortcut_combo.addItem("Alt + Space", "alt_space")
            self.shortcut_combo.addItem("Control + Shift + Space", "ctrl_shift_space")
        s1_form.addRow("Voice Shortcut:", self.shortcut_combo)

        if sys.platform == "darwin":
            kb_row = QHBoxLayout()
            self.fn_fix_status = QLabel("")
            self.fn_fix_status.setFont(ThemeManager.get_ui_font(12))
            self.fn_fix_status.setWordWrap(True)
            self.fn_fix_btn = QPushButton("1-Click Fix (Stop Emoji Popup)")
            self.fn_fix_btn.setObjectName("secondaryBtn")
            self.fn_fix_btn.setStyleSheet("background-color: #6C8EEF; color: white; border: none; font-weight: bold; padding: 4px 10px;")
            self.fn_fix_btn.clicked.connect(self._on_fix_fn_emoji_clicked)
            kb_row.addWidget(self.fn_fix_status)
            kb_row.addWidget(self.fn_fix_btn)

            kb_btn = QPushButton("macOS Settings...")
            kb_btn.setObjectName("secondaryBtn")
            kb_btn.setStyleSheet("font-size: 11px; padding: 3px 8px;")
            kb_btn.clicked.connect(PermissionsManager.open_keyboard_settings)
            kb_row.addWidget(kb_btn)
            kb_row.addStretch()
            s1_form.addRow("Fn Key Behavior:", kb_row)

        self.ptt_check = QCheckBox("Push-to-Talk (Hold shortcut to speak, release to format and insert)")
        s1_form.addRow("Trigger Mode:", self.ptt_check)

        self.retention_combo = QComboBox()
        self.retention_combo.addItem("30 Days (Default)", 30)
        self.retention_combo.addItem("7 Days", 7)
        self.retention_combo.addItem("15 Days", 15)
        self.retention_combo.addItem("60 Days", 60)
        self.retention_combo.addItem("90 Days", 90)
        self.retention_combo.addItem("Never Delete", 0)
        s1_form.addRow("History Retention:", self.retention_combo)

        self.startup_check = QCheckBox("Launch Just Talk automatically on system login")
        s1_form.addRow("Startup:", self.startup_check)

        self.minimized_check = QCheckBox("Start minimized in menu bar / system tray")
        s1_form.addRow("Window State:", self.minimized_check)

        sec1_layout.addLayout(s1_form)
        layout.addWidget(sec1)

        # Section 2: Speech-to-Text & Microphone
        sec2, sec2_layout = self._create_settings_section("Voice & Speech Recognition")
        s2_form = QFormLayout()
        s2_form.setSpacing(12)
        s2_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        s2_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Microphone selection and live testing row
        mic_row = QHBoxLayout()
        mic_row.setSpacing(8)
        self.device_combo = QComboBox()
        self.device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._populate_audio_devices()
        mic_row.addWidget(self.device_combo, 1)

        self.mic_test_btn = QPushButton("🎤 Test Mic")
        self.mic_test_btn.setObjectName("secondaryBtn")
        self.mic_test_btn.setMinimumHeight(32)
        self.mic_test_btn.clicked.connect(self._toggle_mic_test)
        mic_row.addWidget(self.mic_test_btn)
        s2_form.addRow("Microphone:", mic_row)

        # Microphone live test meter and status
        self.mic_test_container = QWidget()
        mic_test_layout = QVBoxLayout(self.mic_test_container)
        mic_test_layout.setContentsMargins(0, 4, 0, 4)
        mic_test_layout.setSpacing(6)

        self.mic_level_bar = QProgressBar()
        self.mic_level_bar.setRange(0, 100)
        self.mic_level_bar.setValue(0)
        self.mic_level_bar.setTextVisible(False)
        self.mic_level_bar.setFixedHeight(8)
        self.mic_level_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 4px;
                background-color: rgba(255, 255, 255, 0.06);
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #30D158, stop:0.8 #FFD60A, stop:1 #FF453A);
                border-radius: 3px;
            }
        """)
        mic_test_layout.addWidget(self.mic_level_bar)

        self.mic_test_status = QLabel("")
        self.mic_test_status.setObjectName("mutedLabel")
        self.mic_test_status.setWordWrap(True)
        mic_test_layout.addWidget(self.mic_test_status)

        self.mic_test_container.hide()
        s2_form.addRow("", self.mic_test_container)

        self.tier_combo = QComboBox()
        for tier_id, info in TIERS.items():
            self.tier_combo.addItem(f"{info.display_name} — {info.speed_factor} ({info.disk_size_mb} MB)", tier_id)
        self.tier_combo.currentIndexChanged.connect(self._on_tier_selection_changed)
        s2_form.addRow("Model Quality:", self.tier_combo)

        # Responsive Model Storage & Download Card
        storage_row = QVBoxLayout()
        storage_row.setSpacing(8)

        self.download_btn = QPushButton("Download Model")
        self.download_btn.setObjectName("secondaryBtn")
        self.download_btn.setMinimumHeight(34)
        self.download_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.download_btn.clicked.connect(self._on_download_model)
        storage_row.addWidget(self.download_btn)

        self.model_progress_bar = QProgressBar()
        self.model_progress_bar.setRange(0, 100)
        self.model_progress_bar.setValue(0)
        self.model_progress_bar.setTextVisible(False)
        self.model_progress_bar.setFixedHeight(8)
        self.model_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 4px;
                background-color: rgba(255, 255, 255, 0.06);
            }
            QProgressBar::chunk {
                background-color: #6C8EEF;
                border-radius: 3px;
            }
        """)
        self.model_progress_bar.hide()
        storage_row.addWidget(self.model_progress_bar)

        self.model_status_label = QLabel("")
        self.model_status_label.setObjectName("mutedLabel")
        self.model_status_label.setWordWrap(True)
        self.model_status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        storage_row.addWidget(self.model_status_label)

        self.model_error_label = QLabel("")
        self.model_error_label.setStyleSheet("""
            background-color: rgba(255, 69, 58, 0.15);
            color: #FF453A;
            border: 1px solid rgba(255, 69, 58, 0.3);
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 12px;
            font-weight: 500;
        """)
        self.model_error_label.setWordWrap(True)
        self.model_error_label.hide()
        storage_row.addWidget(self.model_error_label)

        s2_form.addRow("Model Storage:", storage_row)

        self.speech_mode_combo = QComboBox()
        self.speech_mode_combo.addItem("✍️ Write in My Language (Transcribe)", "transcribe")
        self.speech_mode_combo.addItem("🌐 Translate Speech to English (Translate)", "translate")
        cur_mode = getattr(self.config, "speech_mode", "transcribe")
        m_idx = self.speech_mode_combo.findData(cur_mode)
        if m_idx >= 0:
            self.speech_mode_combo.setCurrentIndex(m_idx)
        self.speech_mode_combo.currentIndexChanged.connect(self._on_speech_mode_setting_changed)
        s2_form.addRow("Speech Output Mode:", self.speech_mode_combo)

        self.language_combo = SearchableLanguageComboBox()
        cur_lang = getattr(self.config, "language", "en")
        self.language_combo.set_current_language(cur_lang)
        self.language_combo.language_changed.connect(self._on_language_setting_changed)
        s2_form.addRow("Spoken Language:", self.language_combo)

        self.vocab_input = QLineEdit()
        self.vocab_input.setPlaceholderText("e.g. JustTalk, Python, Kubernetes, PyTorch, GraphQL")
        self.vocab_input.setText(getattr(self.config, "custom_vocabulary", ""))
        self.vocab_input.textChanged.connect(self._on_custom_vocabulary_changed)
        s2_form.addRow("Custom Vocabulary:", self.vocab_input)

        vocab_desc = QLabel("Personal names, brands, acronyms, or jargon (comma-separated). Primes Whisper's language decoder so these terms are never misheard.")
        vocab_desc.setObjectName("mutedLabel")
        vocab_desc.setWordWrap(True)
        s2_form.addRow("", vocab_desc)

        self.voice_isolation_check = QCheckBox("Voice & Echo Isolation (DeepFilterNet v3: eliminate background noise & laptop speakers)")
        self.voice_isolation_check.setChecked(getattr(self.config, "voice_isolation_enabled", True))
        self.voice_isolation_check.toggled.connect(self._on_voice_isolation_toggled)
        s2_form.addRow("Voice Isolation:", self.voice_isolation_check)

        self.two_phase_check = QCheckBox("Typeless Fast Emission (Insert draft words instantly in 250ms, then polish with AI)")
        self.two_phase_check.setChecked(getattr(self.config, "two_phase_emission", True))
        self.two_phase_check.toggled.connect(self._on_two_phase_toggled)
        s2_form.addRow("Typeless Emission:", self.two_phase_check)

        sec2_layout.addLayout(s2_form)
        layout.addWidget(sec2)

        # Section: Voice Profiles & Speaker Identification (WeSpeaker CAM++)
        sec_spk, sec_spk_layout = self._create_settings_section("Speaker Recognition & Voice Profiles (WeSpeaker CAM++)")
        spk_form = QFormLayout()
        spk_form.setSpacing(12)

        self.speaker_id_check = QCheckBox("Identify speaker profiles and tag history (e.g. [Speaker 1]: ...)")
        self.speaker_id_check.setChecked(getattr(self.config, "speaker_id_enabled", True))
        self.speaker_id_check.toggled.connect(self._on_speaker_id_toggled)
        spk_form.addRow("Speaker Identification:", self.speaker_id_check)

        self.target_isolation_check = QCheckBox("Filter & drop speech from unrecognized background voices")
        self.target_isolation_check.setChecked(getattr(self.config, "target_speaker_isolation", False))
        self.target_isolation_check.toggled.connect(self._on_target_isolation_toggled)
        spk_form.addRow("Voice Isolation Filter:", self.target_isolation_check)

        # Profile container
        self.profiles_container = QVBoxLayout()
        self._refresh_profiles_list()
        spk_form.addRow("Enrolled Profiles:", self.profiles_container)

        self.enroll_btn = QPushButton("➕ Enroll New Voice Profile (4s calibration)")
        self.enroll_btn.setObjectName("secondaryBtn")
        self.enroll_btn.clicked.connect(self._on_enroll_voice_clicked)
        spk_form.addRow("", self.enroll_btn)

        sec_spk_layout.addLayout(spk_form)
        layout.addWidget(sec_spk)

        # Section 3: Multi-Provider AI Formatting
        sec3, sec3_layout = self._create_settings_section("AI Formatting Layer (Gemini, Claude, OpenAI, Grok, Groq, OpenRouter, Custom)")

        # Embedded AI Formatting View
        self.ai_view = AIFormattingView(self.config, self.gemini, parent=self)
        self.ai_view.config_changed.connect(self._on_ai_config_changed)
        sec3_layout.addWidget(self.ai_view)

        layout.addWidget(sec3)

        # Section 4: Appearance & Themes
        sec4, sec4_layout = self._create_settings_section("Appearance & Theme")
        s4_form = QFormLayout()
        s4_form.setSpacing(12)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("System (Sync with OS Dark / Light)", "system")
        self.theme_combo.addItem("Soft Graphite (Dark)", "dark")
        self.theme_combo.addItem("Clean Paper (Light)", "light")
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        s4_form.addRow("Theme:", self.theme_combo)

        sec4_layout.addLayout(s4_form)
        layout.addWidget(sec4)

        # Section 5: Onboarding & Help
        sec5, sec5_layout = self._create_settings_section("Tutorial & Onboarding")

        replay_desc = QLabel("Re-run the interactive first-time walkthrough to test your microphone, permissions, and keyboard triggers.")
        replay_desc.setObjectName("mutedLabel")
        sec5_layout.addWidget(replay_desc)

        replay_btn = QPushButton("Replay Onboarding Tutorial")
        replay_btn.setObjectName("secondaryBtn")
        replay_btn.clicked.connect(lambda: self.replay_tutorial_requested.emit())
        sec5_layout.addWidget(replay_btn)

        layout.addWidget(sec5)

        # Save Button
        bottom_box = QHBoxLayout()
        bottom_box.addStretch()
        save_btn = QPushButton("Save Preferences")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._on_save_settings)
        bottom_box.addWidget(save_btn)
        layout.addLayout(bottom_box)

        layout.addStretch()
        scroll.setWidget(container)

        self._load_settings_values()
        return scroll

    def _create_settings_section(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        lbl = QLabel(title)
        lbl.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        layout.addWidget(lbl)
        return frame, layout

    def _populate_audio_devices(self) -> None:
        self.device_combo.clear()
        self.device_combo.addItem("Default System Microphone", None)
        devices = AudioRecorder.get_input_devices()
        for dev in devices:
            self.device_combo.addItem(f"{dev.name} (Ch {dev.max_input_channels})", dev.index)

    def _load_settings_values(self) -> None:
        idx = self.shortcut_combo.findData(self.config.shortcut)
        if idx >= 0:
            self.shortcut_combo.setCurrentIndex(idx)
        self.ptt_check.setChecked(self.config.push_to_talk)

        ret_idx = self.retention_combo.findData(self.config.history_retention_days)
        if ret_idx >= 0:
            self.retention_combo.setCurrentIndex(ret_idx)

        self.startup_check.setChecked(self.config.launch_at_startup)
        self.minimized_check.setChecked(self.config.start_minimized)

        dev_idx = self.device_combo.findData(self.config.audio_device_index)
        if dev_idx >= 0:
            self.device_combo.setCurrentIndex(dev_idx)

        tier_idx = self.tier_combo.findData(self.config.model_tier)
        if tier_idx >= 0:
            self.tier_combo.setCurrentIndex(tier_idx)
        self._update_model_status()

        # Theme
        t_idx = self.theme_combo.findData(self.config.appearance)
        if t_idx >= 0:
            self.theme_combo.setCurrentIndex(t_idx)

        # Custom Vocabulary
        if hasattr(self, "vocab_input"):
            self.vocab_input.setText(getattr(self.config, "custom_vocabulary", ""))

    def _on_custom_vocabulary_changed(self, text: str) -> None:
        self.config.custom_vocabulary = text
        self.config.save()
        if self.on_config_changed_callback:
            self.on_config_changed_callback(self.config)

    def _on_voice_isolation_toggled(self, checked: bool) -> None:
        self.config.voice_isolation_enabled = checked
        self.config.save()
        if self.on_config_changed_callback:
            self.on_config_changed_callback(self.config)

    def _on_two_phase_toggled(self, checked: bool) -> None:
        self.config.two_phase_emission = checked
        self.config.save()
        if self.on_config_changed_callback:
            self.on_config_changed_callback(self.config)

    def _on_speaker_id_toggled(self, checked: bool) -> None:
        self.config.speaker_id_enabled = checked
        self.config.save()
        if self.on_config_changed_callback:
            self.on_config_changed_callback(self.config)

    def _on_target_isolation_toggled(self, checked: bool) -> None:
        self.config.target_speaker_isolation = checked
        self.config.save()
        if self.on_config_changed_callback:
            self.on_config_changed_callback(self.config)

    def _refresh_profiles_list(self) -> None:
        if not hasattr(self, "profiles_container"):
            return
        while self.profiles_container.count():
            item = self.profiles_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        profiles = self.db.list_voice_profiles() if hasattr(self.db, "list_voice_profiles") else []
        if not profiles:
            empty_lbl = QLabel("No voice profiles enrolled yet. Click 'Enroll New Voice Profile' below.")
            empty_lbl.setObjectName("mutedLabel")
            self.profiles_container.addWidget(empty_lbl)
            return

        for p in profiles:
            p_row = QHBoxLayout()
            name_lbl = QLabel(f"🎙️ {p['name']}")
            name_lbl.setStyleSheet("font-weight: 600; color: #FFFFFF;")
            p_row.addWidget(name_lbl)

            date_lbl = QLabel(f"Added {p['created_at'][:10]}")
            date_lbl.setObjectName("mutedLabel")
            p_row.addWidget(date_lbl)

            p_row.addStretch()

            del_btn = QPushButton("Delete")
            del_btn.setObjectName("dangerBtn")
            del_btn.setStyleSheet("background-color: rgba(255, 69, 58, 0.15); color: #FF453A; font-size: 11px; padding: 2px 8px; border-radius: 4px;")
            name_to_del = p['name']
            del_btn.clicked.connect(lambda checked=False, n=name_to_del: self._on_delete_profile(n))
            p_row.addWidget(del_btn)

            row_widget = QWidget()
            row_widget.setLayout(p_row)
            self.profiles_container.addWidget(row_widget)

    def _on_delete_profile(self, name: str) -> None:
        if hasattr(self.db, "delete_voice_profile"):
            self.db.delete_voice_profile(name)
            self._refresh_profiles_list()

    def _on_enroll_voice_clicked(self) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        name, ok = QInputDialog.getText(self, "Enroll Voice Profile", "Enter a name for this voice profile (e.g. Speaker 1):")
        if not ok or not name.strip():
            return

        profile_name = name.strip()
        QMessageBox.information(
            self,
            "Calibrating Voice Profile",
            f"Click OK and speak clearly for 4 seconds to calibrate '{profile_name}'.",
        )

        try:
            import sounddevice as sd
            from ..audio.speaker_recognizer import SpeakerRecognizer

            sr = SpeakerRecognizer()
            if not sr.is_available():
                QMessageBox.warning(self, "Model Missing", "WeSpeaker CAM++ model is downloading or not yet loaded.")
                return

            audio = sd.rec(int(16000 * 4.0), samplerate=16000, channels=1, dtype="float32", device=self.config.audio_device_index)
            sd.wait()
            audio_flat = audio.flatten()

            emb = sr.extract_embedding(audio_flat)
            if emb is not None:
                self.db.save_voice_profile(profile_name, emb)
                self._refresh_profiles_list()
                QMessageBox.information(self, "Voice Enrolled", f"Successfully enrolled voice profile: '{profile_name}'!")
            else:
                QMessageBox.warning(self, "Calibration Failed", "Could not extract voice embedding. Ensure your microphone is working and speak clearly.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Voice enrollment failed: {e}")

    def _on_tier_selection_changed(self) -> None:
        tier_id = self.tier_combo.currentData()
        if tier_id:
            self.config.model_tier = tier_id
            self.config.save()
            self._update_model_status()
            self._refresh_home_status()
            if self.on_config_changed_callback:
                self.on_config_changed_callback(self.config)

    def _update_model_status(self) -> None:
        tier_id = self.tier_combo.currentData() or self.config.model_tier
        info = self.model_manager.get_tier_info(tier_id)
        downloaded = self.model_manager.is_model_downloaded(tier_id)
        if hasattr(self.model_manager, "is_downloading") and self.model_manager.is_downloading(tier_id):
            active_prog = self.model_manager.get_active_progress(tier_id)
            pct = active_prog[0] if active_prog else 5.0
            msg = active_prog[1] if active_prog else f"Downloading {info.display_name}..."
            self.model_status_label.setText(msg)
            self.model_status_label.setStyleSheet("color: #6C8EEF;")
            self.model_progress_bar.show()
            self.model_progress_bar.setValue(int(max(1, min(100, pct))))
            self.download_btn.setText("Downloading...")
            self.download_btn.setEnabled(False)
            self.model_error_label.hide()
        elif downloaded:
            self.model_status_label.setText(f"✓ {info.display_name} is downloaded and ready in cache (~{info.disk_size_mb} MB).")
            self.model_status_label.setStyleSheet("color: #30D158;")
            self.download_btn.setText("Re-download Model")
            self.download_btn.setStyleSheet("")
            self.download_btn.setEnabled(True)
            self.model_progress_bar.hide()
            self.model_error_label.hide()
        else:
            self.model_status_label.setText(f"Not downloaded yet (~{info.disk_size_mb} MB required). Downloads automatically on first voice input or click below.")
            self.model_status_label.setStyleSheet("color: #8E8E93;")
            self.download_btn.setText(f"Download {info.model_name.upper()} ({info.disk_size_mb} MB)")
            self.download_btn.setStyleSheet("background-color: #6C8EEF; color: white; border: none; font-weight: bold; border-radius: 6px; padding: 6px 12px;")
            self.download_btn.setEnabled(True)
            self.model_progress_bar.hide()
            self.model_error_label.hide()

    def _on_download_model(self) -> None:
        tier_id = self.tier_combo.currentData() or self.config.model_tier
        info = self.model_manager.get_tier_info(tier_id)
        is_redownload = "Re-download" in self.download_btn.text()

        self.model_error_label.hide()
        self.model_progress_bar.show()
        self.model_progress_bar.setValue(2)
        self.model_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 4px;
                background-color: rgba(255, 255, 255, 0.06);
            }
            QProgressBar::chunk {
                background-color: #6C8EEF;
                border-radius: 3px;
            }
        """)
        action_verb = "Re-downloading" if is_redownload else "Downloading"
        self.model_status_label.setText(f"Connecting to {action_verb.lower()} {info.display_name} ({info.disk_size_mb} MB)...")
        self.model_status_label.setStyleSheet("color: #6C8EEF;")
        self.download_btn.setEnabled(False)
        self.download_btn.setText(f"{action_verb}...")

        def worker():
            last_err = ""

            def progress(pct: float, msg: str):
                nonlocal last_err
                if pct < 0:
                    last_err = msg
                    QTimer.singleShot(0, lambda m=msg: self._on_download_failed(m))
                else:
                    QTimer.singleShot(0, lambda p=pct, m=msg: self._on_download_progress(p, m))

            success = self.model_manager.download_model(
                tier_id,
                progress_callback=progress,
                force_redownload=is_redownload,
            )

            def done():
                self.download_btn.setEnabled(True)
                if success:
                    self._on_download_succeeded(info)
                elif not last_err:
                    self._on_download_failed("Download interrupted. Check internet connection.")

            QTimer.singleShot(0, done)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _on_download_progress(self, pct: float, msg: str) -> None:
        self.model_progress_bar.show()
        self.model_progress_bar.setValue(int(max(0, min(100, pct))))
        self.model_status_label.setText(msg)
        self.model_status_label.setStyleSheet("color: #6C8EEF;")

    def _on_download_succeeded(self, info) -> None:
        self.model_progress_bar.setValue(100)
        self.model_progress_bar.hide()
        self.model_error_label.hide()
        self.model_status_label.setText(f"✓ {info.display_name} is fully downloaded and verified ({info.disk_size_mb} MB).")
        self.model_status_label.setStyleSheet("color: #30D158;")
        self.download_btn.setText("Re-download Model")
        self.download_btn.setStyleSheet("")
        self.download_btn.setEnabled(True)
        self._refresh_home_status()
        QMessageBox.information(self, "Download Complete", f"{info.display_name} downloaded successfully and is ready for use!")

    def _on_download_failed(self, error_msg: str) -> None:
        self.model_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid rgba(255, 69, 58, 0.3);
                border-radius: 4px;
                background-color: rgba(255, 255, 255, 0.06);
            }
            QProgressBar::chunk {
                background-color: #FF453A;
                border-radius: 3px;
            }
        """)
        clean_err = error_msg.replace("Download failed:", "").strip()
        self.model_error_label.setText(f"⚠️ Download Failed: {clean_err}\nCheck your internet connection and click Retry Download.")
        self.model_error_label.show()
        self.model_status_label.setText("Download interrupted.")
        self.model_status_label.setStyleSheet("color: #FF453A;")
        self.download_btn.setText("Retry Download")
        self.download_btn.setStyleSheet("background-color: #FF453A; color: white; border: none; font-weight: bold; border-radius: 6px; padding: 6px 12px;")
        self.download_btn.setEnabled(True)

    # -------------------------------------------------------------------------
    # Live Microphone Testing
    # -------------------------------------------------------------------------

    def _toggle_mic_test(self) -> None:
        if getattr(self, "_is_testing_mic", False):
            self._stop_mic_test()
        else:
            self._start_mic_test()

    def _start_mic_test(self) -> None:
        self._is_testing_mic = True
        self.mic_test_btn.setText("⏹️ Stop Test")
        self.mic_test_btn.setStyleSheet("background-color: rgba(255, 69, 58, 0.2); color: #FF453A; border: 1px solid #FF453A;")
        self.mic_test_container.show()
        self.mic_level_bar.setValue(0)
        self.mic_test_status.setText("Listening... Speak into your microphone to verify capture.")
        self.mic_test_status.setStyleSheet("color: #6C8EEF;")

        dev_idx = self.device_combo.currentData()
        self._mic_test_detected_voice = False

        def on_level(rms: float):
            pct = min(100, int(rms * 450))
            if pct > 4:
                self._mic_test_detected_voice = True
            QTimer.singleShot(0, lambda p=pct: self._on_mic_test_level(p))

        self._mic_test_recorder = AudioRecorder(
            device_index=dev_idx,
            level_callback=on_level,
        )
        started = self._mic_test_recorder.start()
        if not started:
            self.mic_test_status.setText("⚠️ Failed to open microphone. Check device permissions or reconnect hardware.")
            self.mic_test_status.setStyleSheet("color: #FF453A;")
            self._stop_mic_test(reset_status=False)
            return

        # Auto stop after 10 seconds of testing
        if not hasattr(self, "_mic_test_timer"):
            self._mic_test_timer = QTimer(self)
            self._mic_test_timer.setSingleShot(True)
            self._mic_test_timer.timeout.connect(self._stop_mic_test)
        self._mic_test_timer.start(10000)

    def _on_mic_test_level(self, level: int) -> None:
        if not getattr(self, "_is_testing_mic", False):
            return
        self.mic_level_bar.setValue(level)
        if getattr(self, "_mic_test_detected_voice", False):
            self.mic_test_status.setText("✓ Sound detected! Microphone is receiving audio clearly.")
            self.mic_test_status.setStyleSheet("color: #30D158;")

    def _stop_mic_test(self, reset_status: bool = True) -> None:
        self._is_testing_mic = False
        self.mic_test_btn.setText("🎤 Test Mic")
        self.mic_test_btn.setStyleSheet("")
        if hasattr(self, "_mic_test_timer"):
            self._mic_test_timer.stop()
        if hasattr(self, "_mic_test_recorder") and self._mic_test_recorder is not None:
            try:
                self._mic_test_recorder.stop()
            except Exception:
                pass
            self._mic_test_recorder = None
        self.mic_level_bar.setValue(0)
        if reset_status and not getattr(self, "_mic_test_detected_voice", False):
            self.mic_test_status.setText("⚠️ Test finished: No voice/audio detected. Ensure microphone is not muted.")
            self.mic_test_status.setStyleSheet("color: #FF9F0A;")

    def _on_theme_changed(self) -> None:
        app = QApplication.instance()
        if app:
            chosen = self.theme_combo.currentData()
            self.config.appearance = chosen
            ThemeManager.apply_theme(app, chosen)

    def _on_ai_config_changed(self) -> None:
        self.config.save()
        if self.on_config_changed_callback:
            self.on_config_changed_callback(self.config)
        self._refresh_home_status()

    def _style_home_mode_buttons(self) -> None:
        transcribe_active = getattr(self.config, "speech_mode", "transcribe") != "translate"
        if transcribe_active:
            self.home_mode_transcribe_btn.setStyleSheet("background-color: #6C8EEF; color: white; border: none; font-weight: bold; border-radius: 8px; padding: 10px 14px;")
            self.home_mode_translate_btn.setStyleSheet("background-color: rgba(255, 255, 255, 0.08); color: #8E8E93; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 10px 14px;")
        else:
            self.home_mode_transcribe_btn.setStyleSheet("background-color: rgba(255, 255, 255, 0.08); color: #8E8E93; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 10px 14px;")
            self.home_mode_translate_btn.setStyleSheet("background-color: #6C8EEF; color: white; border: none; font-weight: bold; border-radius: 8px; padding: 10px 14px;")

    def _set_home_speech_mode(self, mode: str) -> None:
        self.config.speech_mode = mode
        self.config.save()
        self._style_home_mode_buttons()
        self._update_home_mode_desc()
        if hasattr(self, "speech_mode_combo"):
            idx = self.speech_mode_combo.findData(mode)
            if idx >= 0:
                self.speech_mode_combo.blockSignals(True)
                self.speech_mode_combo.setCurrentIndex(idx)
                self.speech_mode_combo.blockSignals(False)
        self.config_changed.emit(self.config)

    def _on_home_lang_changed(self, code: str) -> None:
        self.config.language = code
        self.config.save()
        self._update_home_mode_desc()
        if hasattr(self, "language_combo") and self.language_combo is not None:
            self.language_combo.set_current_language(code)
        self.config_changed.emit(self.config)

    def _update_home_mode_desc(self) -> None:
        lang_code = getattr(self.config, "language", "en")
        mode = getattr(self.config, "speech_mode", "transcribe")
        if mode == "translate":
            if lang_code == "ne_en":
                self.home_mode_desc.setText(
                    "🌐 Translate Mode: Mixed Nepali & English speech is translated seamlessly into clean, fluent English."
                )
            else:
                self.home_mode_desc.setText(
                    "🌐 Translate Mode: Whatever you speak (Nepali, Spanish, French, etc.) is translated directly into English."
                )
        else:
            if lang_code == "ne_en":
                self.home_mode_desc.setText("✍️ Transcribe Mode: Speak in conversational mixed Nepali & English; text is typed exactly as spoken.")
            elif lang_code == "ne":
                self.home_mode_desc.setText("✍️ Transcribe Mode: Speak in Nepali, and it types directly in Nepali Devanagari (नेपाली).")
            else:
                self.home_mode_desc.setText("✍️ Transcribe Mode: Text is typed directly in the exact language you speak.")

    def _on_home_fix_fn_clicked(self) -> None:
        acc_ok = PermissionsManager.check_accessibility(prompt_if_needed=False)
        input_ok = PermissionsManager.check_input_monitoring()
        if not acc_ok:
            PermissionsManager.open_accessibility_settings()
        elif not input_ok:
            PermissionsManager.open_input_monitoring_settings()
        else:
            PermissionsManager.disable_fn_emoji_popup()
        self._refresh_home_status()

    def _on_fix_fn_emoji_clicked(self) -> None:
        PermissionsManager.disable_fn_emoji_popup()
        self._refresh_home_status()
        if hasattr(self, "fn_fix_status"):
            self.fn_fix_status.setText("✓ Fixed (Emoji popup disabled)")
            self.fn_fix_status.setStyleSheet("color: #30D158;")
            self.fn_fix_btn.hide()

    def _on_speech_mode_setting_changed(self, idx: int) -> None:
        mode = self.speech_mode_combo.itemData(idx)
        self._set_home_speech_mode(mode)

    def _on_language_setting_changed(self, code: str) -> None:
        self.config.language = code
        self.config.save()
        self._update_home_mode_desc()
        if hasattr(self, "home_lang_combo") and self.home_lang_combo is not None:
            self.home_lang_combo.set_current_language(code)
        self.config_changed.emit(self.config)

    def _on_save_settings(self) -> None:
        self.config.shortcut = self.shortcut_combo.currentData()
        self.config.push_to_talk = self.ptt_check.isChecked()
        self.config.history_retention_days = self.retention_combo.currentData()
        self.config.launch_at_startup = self.startup_check.isChecked()
        self.config.start_minimized = self.minimized_check.isChecked()
        self.config.audio_device_index = self.device_combo.currentData()
        self.config.model_tier = self.tier_combo.currentData()
        self.config.appearance = self.theme_combo.currentData()
        if hasattr(self, "speech_mode_combo"):
            self.config.speech_mode = self.speech_mode_combo.currentData()
        if hasattr(self, "language_combo"):
            self.config.language = self.language_combo.get_current_language()
        self.config.save()

        # Synchronize autostart with operating system
        AutostartManager.set_autostart(self.config.launch_at_startup)

        # Update in-memory and notify main loop
        if self.on_config_changed_callback:
            self.on_config_changed_callback(self.config)

        self._refresh_home_status()
        QMessageBox.information(self, "Settings Saved", "Preferences updated successfully.")

    # -------------------------------------------------------------------------
    # Helper Utilities
    # -------------------------------------------------------------------------

    def _get_shortcut_display(self) -> str:
        s = self.config.shortcut
        if s == "fn":
            return "fn" if sys.platform == "darwin" else "Right Alt"
        elif s == "right_alt":
            return "Right Alt" if sys.platform != "darwin" else "Right Option"
        elif s == "alt_space":
            return "⌥ + Space" if sys.platform == "darwin" else "Alt + Space"
        elif s == "ctrl_shift_space":
            return "⌃ + ⇧ + Space" if sys.platform == "darwin" else "Ctrl + Shift + Space"
        return s.upper()

    @staticmethod
    def _get_time_greeting() -> str:
        hour = datetime.datetime.now().hour
        if 5 <= hour < 12:
            return "Good morning"
        elif 12 <= hour < 17:
            return "Good afternoon"
        elif 17 <= hour < 22:
            return "Good evening"
        return "Good night"
