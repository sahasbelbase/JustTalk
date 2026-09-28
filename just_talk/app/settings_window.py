"""Native desktop Settings dialog with secure credential management and device testing."""

from __future__ import annotations

import sys
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..audio.recorder import AudioRecorder
from ..config import AppConfig
from ..security import CredentialManager
from ..stt.model_manager import TIERS, ModelManager


class SettingsWindow(QDialog):
    """User preferences window for Just Talk."""

    def __init__(
        self,
        config: AppConfig,
        model_manager: ModelManager,
        on_config_changed: Optional[Callable[[AppConfig], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config = config
        self.model_manager = model_manager
        self.on_config_changed = on_config_changed

        self.setWindowTitle("Just Talk — Settings")
        self.resize(560, 480)
        self.setMinimumSize(480, 400)
        self._setup_ui()
        self._load_values()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)

        self.tabs = QTabWidget()

        # Tab 1: General
        general_widget = QWidget()
        gen_layout = QFormLayout(general_widget)
        gen_layout.setSpacing(12)

        self.shortcut_combo = QComboBox()
        if sys.platform == "darwin":
            self.shortcut_combo.addItem("Function / Globe Key (Fn)", "fn")
            self.shortcut_combo.addItem("Option + Space", "alt_space")
            self.shortcut_combo.addItem("Control + Shift + Space", "ctrl_shift_space")
            self.shortcut_combo.addItem("Right Option Key", "right_alt")
        else:
            self.shortcut_combo.addItem("Right Alt Key (Recommended)", "right_alt")
            self.shortcut_combo.addItem("Alt + Space", "alt_space")
            self.shortcut_combo.addItem("Control + Shift + Space", "ctrl_shift_space")
        gen_layout.addRow("Voice Trigger Shortcut:", self.shortcut_combo)

        self.ptt_check = QCheckBox("Push-to-Talk (Hold shortcut to speak, release to finish)")
        gen_layout.addRow("Trigger Mode:", self.ptt_check)

        self.retention_combo = QComboBox()
        self.retention_combo.addItem("30 Days (Default)", 30)
        self.retention_combo.addItem("7 Days", 7)
        self.retention_combo.addItem("15 Days", 15)
        self.retention_combo.addItem("60 Days", 60)
        self.retention_combo.addItem("90 Days", 90)
        self.retention_combo.addItem("Never Delete", 0)
        gen_layout.addRow("History Retention:", self.retention_combo)

        self.startup_check = QCheckBox("Launch Just Talk automatically on system startup")
        gen_layout.addRow("Startup:", self.startup_check)

        self.minimized_check = QCheckBox("Start minimized in menu bar / system tray")
        gen_layout.addRow("Window State:", self.minimized_check)

        self.tabs.addTab(general_widget, "General")

        # Tab 2: Voice & STT
        voice_widget = QWidget()
        voice_layout = QFormLayout(voice_widget)
        voice_layout.setSpacing(12)

        self.device_combo = QComboBox()
        self._populate_audio_devices()
        voice_layout.addRow("Microphone:", self.device_combo)

        self.tier_combo = QComboBox()
        for tier_id, info in TIERS.items():
            self.tier_combo.addItem(f"{info.display_name} — {info.speed_factor} ({info.disk_size_mb} MB)", tier_id)
        voice_layout.addRow("Model Quality:", self.tier_combo)

        self.model_status_label = QLabel("")
        self.model_status_label.setStyleSheet("color: #888; font-size: 11px;")
        voice_layout.addRow("", self.model_status_label)

        self.download_btn = QPushButton("Download Model")
        self.download_btn.clicked.connect(self._on_download_model)
        voice_layout.addRow("Model Storage:", self.download_btn)

        self.tabs.addTab(voice_widget, "Voice & STT")

        # Tab 3: Gemini Formatting
        gemini_widget = QWidget()
        gem_layout = QFormLayout(gemini_widget)
        gem_layout.setSpacing(12)

        self.gemini_enabled_check = QCheckBox("Enable AI formatting via Google AI Studio")
        gem_layout.addRow("Gemini Layer:", self.gemini_enabled_check)

        api_key_box = QHBoxLayout()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Enter your Google AI Studio API key...")
        api_key_box.addWidget(self.api_key_input)

        self.toggle_key_btn = QPushButton("Show")
        self.toggle_key_btn.setFixedWidth(50)
        self.toggle_key_btn.clicked.connect(self._toggle_key_visibility)
        api_key_box.addWidget(self.toggle_key_btn)
        gem_layout.addRow("API Key:", api_key_box)

        test_key_box = QHBoxLayout()
        self.test_key_btn = QPushButton("Test Connection")
        self.test_key_btn.clicked.connect(self._on_test_gemini)
        test_key_box.addWidget(self.test_key_btn)
        self.test_status_label = QLabel("")
        test_key_box.addWidget(self.test_status_label)
        test_key_box.addStretch()
        gem_layout.addRow("", test_key_box)

        self.gemini_model_combo = QComboBox()
        self.gemini_model_combo.addItem("gemini-3.8-flash (Recommended)", "gemini-3.8-flash")
        self.gemini_model_combo.addItem("gemini-3.5-flash-lite (Ultra-fast)", "gemini-3.5-flash-lite")
        self.gemini_model_combo.addItem("gemini-2.5-flash", "gemini-2.5-flash")
        gem_layout.addRow("Gemini Model:", self.gemini_model_combo)

        self.prompt_style_combo = QComboBox()
        self.prompt_style_combo.addItem("Subtle (Invisible voice keyboard - keep user tone)", "subtle")
        self.prompt_style_combo.addItem("Formal (Polished professional business tone)", "formal")
        self.prompt_style_combo.addItem("Concise (Brief and punchy)", "concise")
        gem_layout.addRow("Writing Style:", self.prompt_style_combo)

        self.offline_check = QCheckBox("Pure Offline Mode (Never send text over internet)")
        gem_layout.addRow("Privacy:", self.offline_check)

        self.tabs.addTab(gemini_widget, "Gemini")

        main_layout.addWidget(self.tabs)

        # Bottom Buttons
        bottom_box = QHBoxLayout()
        bottom_box.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bottom_box.addWidget(cancel_btn)

        save_btn = QPushButton("Save Preferences")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        bottom_box.addWidget(save_btn)
        main_layout.addLayout(bottom_box)

        # Styling
        self.setStyleSheet("""
            QDialog {
                background-color: #18181c;
                color: #e4e4e7;
            }
            QTabWidget::pane {
                border: 1px solid #33333d;
                background-color: #202026;
                border-radius: 6px;
                padding: 12px;
            }
            QTabBar::tab {
                background-color: #18181c;
                color: #a1a1aa;
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background-color: #202026;
                color: #ffffff;
                font-weight: bold;
            }
            QLineEdit, QComboBox {
                background-color: #2a2a34;
                border: 1px solid #3f3f4e;
                border-radius: 6px;
                color: #f4f4f5;
                padding: 6px;
            }
            QPushButton {
                background-color: #3b82f6;
                border: none;
                border-radius: 6px;
                color: white;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)

    def _populate_audio_devices(self) -> None:
        self.device_combo.clear()
        self.device_combo.addItem("Default System Microphone", None)
        devices = AudioRecorder.get_input_devices()
        for dev in devices:
            self.device_combo.addItem(f"{dev.name} (Ch {dev.max_input_channels})", dev.index)

    def _load_values(self) -> None:
        # Shortcut
        idx = self.shortcut_combo.findData(self.config.shortcut)
        if idx >= 0:
            self.shortcut_combo.setCurrentIndex(idx)
        self.ptt_check.setChecked(self.config.push_to_talk)

        # Retention
        ret_idx = self.retention_combo.findData(self.config.history_retention_days)
        if ret_idx >= 0:
            self.retention_combo.setCurrentIndex(ret_idx)

        self.startup_check.setChecked(self.config.launch_at_startup)
        self.minimized_check.setChecked(self.config.start_minimized)

        # Audio device
        dev_idx = self.device_combo.findData(self.config.audio_device_index)
        if dev_idx >= 0:
            self.device_combo.setCurrentIndex(dev_idx)

        # Model tier
        tier_idx = self.tier_combo.findData(self.config.model_tier)
        if tier_idx >= 0:
            self.tier_combo.setCurrentIndex(tier_idx)
        self._update_model_status()

        # Gemini
        self.gemini_enabled_check.setChecked(self.config.gemini_enabled)
        stored_key = CredentialManager.get_api_key()
        if stored_key:
            self.api_key_input.setText(stored_key)

        gem_model_idx = self.gemini_model_combo.findData(self.config.gemini_model)
        if gem_model_idx >= 0:
            self.gemini_model_combo.setCurrentIndex(gem_model_idx)

        style_idx = self.prompt_style_combo.findData(self.config.prompt_style)
        if style_idx >= 0:
            self.prompt_style_combo.setCurrentIndex(style_idx)

        self.offline_check.setChecked(self.config.offline_mode)

    def _update_model_status(self) -> None:
        tier_id = self.tier_combo.currentData()
        downloaded = self.model_manager.is_model_downloaded(tier_id)
        if downloaded:
            self.model_status_label.setText("Status: Model downloaded and ready.")
            self.download_btn.setText("Re-download Model")
        else:
            self.model_status_label.setText("Status: Not downloaded yet. Will download automatically on first use.")
            self.download_btn.setText("Download Now")

    def _toggle_key_visibility(self) -> None:
        if self.api_key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_key_btn.setText("Hide")
        else:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_key_btn.setText("Show")

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
            QMessageBox.warning(self, "Download Failed", "Failed to download model. Check internet connection.")

    def _on_test_gemini(self) -> None:
        key = self.api_key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "No Key", "Please enter an API key to test.")
            return

        from ..ai.gemini import GeminiFormatter

        formatter = GeminiFormatter(
            api_key=key,
            model_name=self.gemini_model_combo.currentData(),
        )
        self.test_status_label.setText("Testing...")
        ok, msg = formatter.test_connection()
        if ok:
            self.test_status_label.setText("✓ Connected!")
            self.test_status_label.setStyleSheet("color: #10b981;")
        else:
            self.test_status_label.setText("✗ Failed")
            self.test_status_label.setStyleSheet("color: #ef4444;")
            QMessageBox.warning(self, "Connection Test", msg)

    def _on_save(self) -> None:
        # Update config
        self.config.shortcut = self.shortcut_combo.currentData()
        self.config.push_to_talk = self.ptt_check.isChecked()
        self.config.history_retention_days = self.retention_combo.currentData()
        self.config.launch_at_startup = self.startup_check.isChecked()
        self.config.start_minimized = self.minimized_check.isChecked()
        self.config.audio_device_index = self.device_combo.currentData()
        self.config.model_tier = self.tier_combo.currentData()
        self.config.gemini_enabled = self.gemini_enabled_check.isChecked()
        self.config.gemini_model = self.gemini_model_combo.currentData()
        self.config.prompt_style = self.prompt_style_combo.currentData()
        self.config.offline_mode = self.offline_check.isChecked()
        self.config.save()

        # Save secure credential
        key = self.api_key_input.text().strip()
        if key:
            CredentialManager.set_api_key(key)
        else:
            CredentialManager.delete_api_key()

        if self.on_config_changed:
            self.on_config_changed(self.config)

        self.accept()
