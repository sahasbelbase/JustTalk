"""Full desktop application window with sidebar navigation, Home, History, and Settings."""

from __future__ import annotations

import datetime
import sys
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont, QIcon
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
from ..system.clipboard import ClipboardManager
from .ai_formatting_view import AIFormattingView
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
        self.resize(960, 650)
        self.setMinimumSize(860, 560)

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

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Intercept close: keep background push-to-talk listener and tray alive.
        Switches macOS dock policy back to accessory.
        """
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
        sidebar.setFixedWidth(210)
        sidebar.setObjectName("sidebar")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 20, 14, 18)
        layout.setSpacing(12)

        # App Brand Header
        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(2)

        title = QLabel("Just Talk")
        title.setFont(ThemeManager.get_display_font(26, weight=QFont.Weight.Bold))
        brand_layout.addWidget(title)

        subtitle = QLabel("Voice Keyboard · v1.0")
        subtitle.setObjectName("mutedLabel")
        subtitle.setFont(ThemeManager.get_ui_font(11))
        brand_layout.addWidget(subtitle)

        layout.addLayout(brand_layout)
        layout.addSpacing(16)

        # Navigation Buttons
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.nav_home = QPushButton("  Home")
        self.nav_home.setObjectName("navBtn")
        self.nav_home.setCheckable(True)
        self.nav_home.setChecked(True)
        self.nav_home.clicked.connect(lambda: self.switch_screen("home"))
        self.nav_group.addButton(self.nav_home, 0)
        layout.addWidget(self.nav_home)

        self.nav_history = QPushButton("  History")
        self.nav_history.setObjectName("navBtn")
        self.nav_history.setCheckable(True)
        self.nav_history.clicked.connect(lambda: self.switch_screen("history"))
        self.nav_group.addButton(self.nav_history, 1)
        layout.addWidget(self.nav_history)

        self.nav_settings = QPushButton("  Settings")
        self.nav_settings.setObjectName("navBtn")
        self.nav_settings.setCheckable(True)
        self.nav_settings.clicked.connect(lambda: self.switch_screen("settings"))
        self.nav_group.addButton(self.nav_settings, 2)
        layout.addWidget(self.nav_settings)

        layout.addStretch()

        # Sidebar Bottom Status Indicator Card
        status_card = QFrame()
        status_card.setObjectName("surfaceCard")
        sc_layout = QVBoxLayout(status_card)
        sc_layout.setContentsMargins(10, 10, 10, 10)
        sc_layout.setSpacing(6)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.sidebar_dot = QLabel("●")
        self.sidebar_dot.setFont(ThemeManager.get_ui_font(11))
        self.sidebar_dot.setStyleSheet("color: #3DD68C;")  # green default
        status_row.addWidget(self.sidebar_dot)

        self.sidebar_status_text = QLabel("Ready")
        self.sidebar_status_text.setFont(ThemeManager.get_ui_font(12, weight=QFont.Weight.Medium))
        status_row.addWidget(self.sidebar_status_text)
        status_row.addStretch()
        sc_layout.addLayout(status_row)

        self.sidebar_key_label = QLabel(self._get_shortcut_display())
        self.sidebar_key_label.setObjectName("shortcutBadge")
        self.sidebar_key_label.setFont(ThemeManager.get_mono_font(10))
        sc_layout.addWidget(self.sidebar_key_label)

        layout.addWidget(status_card)
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
        layout.setContentsMargins(36, 32, 36, 32)
        layout.setSpacing(20)

        # Greeting in Instrument Serif
        greeting_text = self._get_time_greeting()
        self.greeting_label = QLabel(greeting_text)
        self.greeting_label.setFont(ThemeManager.get_display_font(30, weight=QFont.Weight.Normal))
        layout.addWidget(self.greeting_label)

        subtitle = QLabel("Just Talk is warm in RAM and ready to transcribe.")
        subtitle.setObjectName("mutedLabel")
        subtitle.setFont(ThemeManager.get_ui_font(14))
        layout.addWidget(subtitle)

        # Push-to-Talk Hero Keycap Card
        hero_card = QFrame()
        hero_card.setObjectName("card")
        hero_layout = QVBoxLayout(hero_card)
        hero_layout.setContentsMargins(20, 20, 20, 20)
        hero_layout.setSpacing(12)

        hero_header = QHBoxLayout()
        hero_title = QLabel("Push-to-Talk Shortcut")
        hero_title.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        hero_header.addWidget(hero_title)
        hero_header.addStretch()
        hero_layout.addLayout(hero_header)

        keycap_row = QHBoxLayout()
        keycap_row.setSpacing(14)

        self.hero_keycap = QLabel(self._get_shortcut_display())
        self.hero_keycap.setObjectName("keycap")
        self.hero_keycap.setFont(ThemeManager.get_ui_font(16, weight=QFont.Weight.Bold))
        keycap_row.addWidget(self.hero_keycap)

        hero_desc_layout = QVBoxLayout()
        hero_desc_layout.setSpacing(4)
        hero_desc = QLabel("Hold to talk · Release to insert")
        hero_desc.setFont(ThemeManager.get_ui_font(14, weight=QFont.Weight.Medium))
        hero_desc_sub = QLabel("Speaks into Slack, VS Code, Chrome, or any focused application.")
        hero_desc_sub.setObjectName("mutedLabel")
        hero_desc_sub.setFont(ThemeManager.get_ui_font(12))
        hero_desc_layout.addWidget(hero_desc)
        hero_desc_layout.addWidget(hero_desc_sub)

        keycap_row.addLayout(hero_desc_layout)
        keycap_row.addStretch()
        hero_layout.addLayout(keycap_row)

        layout.addWidget(hero_card)

        # Status Cards Row (Speech Engine, AI Formatter, Audio Input)
        status_row = QHBoxLayout()
        status_row.setSpacing(12)

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
        practice_layout.setContentsMargins(18, 18, 18, 18)
        practice_layout.setSpacing(10)

        practice_header = QHBoxLayout()
        p_title = QLabel("Try It Here")
        p_title.setFont(ThemeManager.get_ui_font(14, weight=QFont.Weight.DemiBold))
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
        practice_layout.addWidget(practice_sub)

        self.practice_text = QTextEdit()
        self.practice_text.setPlaceholderText("Click here and hold your voice key to practice...")
        self.practice_text.setFixedHeight(85)
        practice_layout.addWidget(self.practice_text)

        layout.addWidget(practice_card)

        # Recent Dictations Card
        recent_card = QFrame()
        recent_card.setObjectName("card")
        recent_layout = QVBoxLayout(recent_card)
        recent_layout.setContentsMargins(18, 18, 18, 18)
        recent_layout.setSpacing(12)

        recent_header = QHBoxLayout()
        recent_title = QLabel("Recent Dictations")
        recent_title.setFont(ThemeManager.get_ui_font(14, weight=QFont.Weight.DemiBold))
        recent_header.addWidget(recent_title)

        recent_header.addStretch()
        view_all_btn = QPushButton("View all in History →")
        view_all_btn.setObjectName("flatBtn")
        view_all_btn.clicked.connect(lambda: self.switch_screen("history"))
        recent_header.addWidget(view_all_btn)
        recent_layout.addLayout(recent_header)

        self.recent_items_layout = QVBoxLayout()
        self.recent_items_layout.setSpacing(8)
        recent_layout.addLayout(self.recent_items_layout)

        layout.addWidget(recent_card)
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _create_mini_status_card(self, tag: str, title: str, status: str) -> QFrame:
        card = QFrame()
        card.setObjectName("surfaceCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        tag_lbl = QLabel(tag)
        tag_lbl.setObjectName("mutedLabel")
        tag_lbl.setFont(ThemeManager.get_mono_font(10))
        layout.addWidget(tag_lbl)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("cardTitle")
        title_lbl.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        layout.addWidget(title_lbl)

        status_lbl = QLabel(status)
        status_lbl.setObjectName("cardStatus")
        status_lbl.setFont(ThemeManager.get_ui_font(12))
        layout.addWidget(status_lbl)

        card.status_label = status_lbl
        card.title_label = title_lbl
        return card

    def _refresh_home_status(self) -> None:
        """Update live status labels and recent history on Home screen."""
        # 1. Speech engine
        tier_info = TIERS.get(self.config.model_tier)
        tier_name = tier_info.display_name if tier_info else self.config.model_tier
        self.model_card.title_label.setText(f"Whisper {tier_name}")
        self.model_card.status_label.setText("Loaded in RAM")

        # 2. AI Formatting & Circuit Breaker
        if self.config.offline_mode:
            self.gemini_card.title_label.setText("Pure Offline")
            self.gemini_card.status_label.setText("Speech never sent out")
            self.sidebar_dot.setStyleSheet("color: #9497A1;")
            self.sidebar_status_text.setText("Offline")
        elif not self.config.gemini_enabled:
            self.gemini_card.title_label.setText("Raw STT Only")
            self.gemini_card.status_label.setText("Gemini formatting disabled")
            self.sidebar_dot.setStyleSheet("color: #9497A1;")
            self.sidebar_status_text.setText("Ready (Raw)")
        elif self.gemini.circuit_breaker.is_paused:
            rem = self.gemini.circuit_breaker.remaining_cooldown_sec
            self.gemini_card.title_label.setText("Circuit Breaker")
            self.gemini_card.status_label.setText(f"Paused ({rem}s remaining)")
            self.sidebar_dot.setStyleSheet("color: #F5B942;")  # amber
            self.sidebar_status_text.setText("AI Paused")
        else:
            self.gemini_card.title_label.setText("Gemini Active")
            self.gemini_card.status_label.setText(self.config.gemini_model)
            self.sidebar_dot.setStyleSheet("color: #3DD68C;")  # green
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
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        # Header Bar
        header = QHBoxLayout()
        title = QLabel("Dictation History")
        title.setFont(ThemeManager.get_ui_font(20, weight=QFont.Weight.Bold))
        header.addWidget(title)
        header.addStretch()

        clear_btn = QPushButton("Clear History...")
        clear_btn.setObjectName("secondaryBtn")
        clear_btn.clicked.connect(self._on_clear_history)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        # Search Bar & Filter Chips
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(10)

        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search transcription text, app name, or dates...")
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

        # Table widget
        self.history_table = QTableWidget(0, 3)
        self.history_table.setHorizontalHeaderLabels(["Time", "Target App", "Dictation"])
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.itemSelectionChanged.connect(self._on_history_selection_changed)
        splitter.addWidget(self.history_table)

        # Detail Panel
        detail_card = QFrame()
        detail_card.setObjectName("card")
        d_layout = QVBoxLayout(detail_card)
        d_layout.setContentsMargins(16, 16, 16, 16)
        d_layout.setSpacing(10)

        self.detail_meta = QLabel("Select an entry to view full details")
        self.detail_meta.setObjectName("mutedLabel")
        self.detail_meta.setFont(ThemeManager.get_ui_font(12))
        d_layout.addWidget(self.detail_meta)

        d_layout.addWidget(QLabel("Formatted Output:"))
        self.detail_formatted = QTextEdit()
        self.detail_formatted.setReadOnly(True)
        self.detail_formatted.setFont(ThemeManager.get_ui_font(13))
        d_layout.addWidget(self.detail_formatted, 2)

        d_layout.addWidget(QLabel("Raw Whisper Transcription:"))
        self.detail_raw = QTextEdit()
        self.detail_raw.setReadOnly(True)
        self.detail_raw.setFont(ThemeManager.get_mono_font(12))
        self.detail_raw.setFixedHeight(80)
        d_layout.addWidget(self.detail_raw, 1)

        copy_full_btn = QPushButton("Copy Formatted Text")
        copy_full_btn.setObjectName("primaryBtn")
        copy_full_btn.clicked.connect(self._copy_selected_history)
        d_layout.addWidget(copy_full_btn)

        splitter.addWidget(detail_card)
        splitter.setSizes([480, 360])
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
                if it.processed_text != it.raw_transcription and "inserted" in it.status:
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
        layout.setContentsMargins(36, 32, 36, 32)
        layout.setSpacing(24)

        # Header
        header = QLabel("Settings")
        header.setFont(ThemeManager.get_ui_font(20, weight=QFont.Weight.Bold))
        layout.addWidget(header)

        # Section 1: General & Shortcuts
        sec1, sec1_layout = self._create_settings_section("Trigger & General")
        s1_form = QFormLayout()
        s1_form.setSpacing(12)

        self.shortcut_combo = QComboBox()
        if sys.platform == "darwin":
            self.shortcut_combo.addItem("Function / Globe Key (Fn) [Recommended]", "fn")
            self.shortcut_combo.addItem("Right Option Key", "right_alt")
            self.shortcut_combo.addItem("Option + Space", "alt_space")
            self.shortcut_combo.addItem("Control + Shift + Space", "ctrl_shift_space")
        else:
            self.shortcut_combo.addItem("Right Alt Key [Recommended]", "right_alt")
            self.shortcut_combo.addItem("Alt + Space", "alt_space")
            self.shortcut_combo.addItem("Control + Shift + Space", "ctrl_shift_space")
        s1_form.addRow("Voice Shortcut:", self.shortcut_combo)

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

        self.device_combo = QComboBox()
        self._populate_audio_devices()
        s2_form.addRow("Microphone:", self.device_combo)

        self.tier_combo = QComboBox()
        for tier_id, info in TIERS.items():
            self.tier_combo.addItem(f"{info.display_name} — {info.speed_factor} ({info.disk_size_mb} MB)", tier_id)
        s2_form.addRow("Model Quality:", self.tier_combo)

        self.model_status_label = QLabel("")
        self.model_status_label.setObjectName("mutedLabel")
        s2_form.addRow("", self.model_status_label)

        self.download_btn = QPushButton("Download Model")
        self.download_btn.setObjectName("secondaryBtn")
        self.download_btn.clicked.connect(self._on_download_model)
        s2_form.addRow("Model Storage:", self.download_btn)

        sec2_layout.addLayout(s2_form)
        layout.addWidget(sec2)

        # Section 3: Hardened Gemini AI Formatting
        sec3, sec3_layout = self._create_settings_section("Gemini AI Formatting")

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
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        lbl = QLabel(title)
        lbl.setFont(ThemeManager.get_ui_font(14, weight=QFont.Weight.DemiBold))
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

    def _update_model_status(self) -> None:
        tier_id = self.tier_combo.currentData()
        downloaded = self.model_manager.is_model_downloaded(tier_id)
        if downloaded:
            self.model_status_label.setText("Status: Model downloaded and ready in cache.")
            self.download_btn.setText("Re-download Model")
        else:
            self.model_status_label.setText("Status: Not downloaded yet. Downloads automatically on first voice input.")
            self.download_btn.setText("Download Now")

    def _on_download_model(self) -> None:
        tier_id = self.tier_combo.currentData()
        self.model_status_label.setText("Downloading model weights... please wait.")
        self.download_btn.setEnabled(False)

        def progress(pct, msg):
            self.model_status_label.setText(f"{msg} ({int(pct)}%)")

        success = self.model_manager.download_model(tier_id, progress_callback=progress)
        self.download_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "Download Complete", "Speech model downloaded successfully!")
            self._update_model_status()
        else:
            QMessageBox.warning(self, "Download Failed", "Failed to download model. Check your internet connection.")

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

    def _on_save_settings(self) -> None:
        self.config.shortcut = self.shortcut_combo.currentData()
        self.config.push_to_talk = self.ptt_check.isChecked()
        self.config.history_retention_days = self.retention_combo.currentData()
        self.config.launch_at_startup = self.startup_check.isChecked()
        self.config.start_minimized = self.minimized_check.isChecked()
        self.config.audio_device_index = self.device_combo.currentData()
        self.config.model_tier = self.tier_combo.currentData()
        self.config.appearance = self.theme_combo.currentData()
        self.config.save()

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
