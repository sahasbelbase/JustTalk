"""Reusable AI Formatting component used in Settings and Onboarding."""

from __future__ import annotations

import sys
import threading
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..ai.gemini import ConnectionTestResult, GeminiFormatter
from ..config import AppConfig
from ..security import CredentialManager
from .theme import ThemeManager


class AIFormattingView(QWidget):
    """
    Hardened AI Formatting configuration & testing component.
    Reused in Settings > AI Formatting and Onboarding Step 1.
    """

    test_completed = Signal(object)  # ConnectionTestResult
    formatting_test_completed = Signal(str, str)  # raw, formatted
    config_changed = Signal()

    def __init__(
        self,
        config: AppConfig,
        gemini: GeminiFormatter,
        parent: Optional[QWidget] = None,
        compact_mode: bool = False,
    ):
        super().__init__(parent)
        self.config = config
        self.gemini = gemini
        self.compact_mode = compact_mode

        self._testing_connection = False
        self._testing_formatting = False
        self._available_models = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]

        self._setup_ui()
        self._load_state()

        # Connect signals from worker threads
        self.test_completed.connect(self._on_connection_test_done)
        self.formatting_test_completed.connect(self._on_formatting_test_done)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # 1. Enable / Offline Toggles
        toggles_card = QFrame()
        toggles_card.setObjectName("surfaceCard")
        toggles_layout = QVBoxLayout(toggles_card)
        toggles_layout.setSpacing(8)

        self.enable_check = QCheckBox("Enable AI formatting (powered by Google AI Studio)")
        self.enable_check.toggled.connect(self._on_enable_toggled)
        toggles_layout.addWidget(self.enable_check)

        self.offline_check = QCheckBox("Pure Offline Mode (Keep all speech & text strictly on-device)")
        self.offline_check.toggled.connect(self._on_offline_toggled)
        toggles_layout.addWidget(self.offline_check)

        layout.addWidget(toggles_card)

        # 2. API Key Section
        key_card = QFrame()
        key_card.setObjectName("surfaceCard")
        key_layout = QVBoxLayout(key_card)
        key_layout.setSpacing(10)

        key_header = QLabel("Google AI Studio API Key")
        key_header.setFont(ThemeManager.font(14, family="ui"))
        key_layout.addWidget(key_header)

        # Input + Action Buttons
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("Paste your API key (AIzaSy...)")
        # Save key on Enter or Focus Out (blur), not on every single keystroke!
        self.key_input.returnPressed.connect(self._save_key_from_input)
        self.key_input.editingFinished.connect(self._save_key_from_input)
        input_row.addWidget(self.key_input)

        self.show_btn = QPushButton("Show")
        self.show_btn.setFixedWidth(54)
        self.show_btn.clicked.connect(self._toggle_show_key)
        input_row.addWidget(self.show_btn)

        self.paste_btn = QPushButton("Paste")
        self.paste_btn.setFixedWidth(58)
        self.paste_btn.clicked.connect(self._paste_key)
        input_row.addWidget(self.paste_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setFixedWidth(54)
        self.clear_btn.clicked.connect(self._clear_key)
        input_row.addWidget(self.clear_btn)

        key_layout.addLayout(input_row)

        # Key storage notice
        self.storage_label = QLabel("")
        self.storage_label.setStyleSheet("color: #888; font-size: 11px;")
        key_layout.addWidget(self.storage_label)

        # Model selection and Test Connection row
        controls_row = QHBoxLayout()
        controls_row.setSpacing(10)

        controls_row.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        controls_row.addWidget(self.model_combo)

        self.test_btn = QPushButton("Test Connection")
        self.test_btn.setObjectName("primaryBtn")
        self.test_btn.clicked.connect(self.run_connection_test)
        controls_row.addWidget(self.test_btn)

        key_layout.addLayout(controls_row)

        # Status Chip
        self.status_chip = QLabel("Not tested")
        self.status_chip.setStyleSheet("padding: 4px 10px; border-radius: 6px; font-size: 12px; background: rgba(148,151,161,0.12); color: #888;")
        key_layout.addWidget(self.status_chip)

        layout.addWidget(key_card)

        # 3. Test Formatting Sandbox (if not in compact mode)
        if not self.compact_mode:
            sandbox_card = QFrame()
            sandbox_card.setObjectName("surfaceCard")
            sandbox_layout = QVBoxLayout(sandbox_card)
            sandbox_layout.setSpacing(8)

            sandbox_header = QLabel("Test Formatting Sandbox")
            sandbox_header.setFont(ThemeManager.font(14, family="ui"))
            sandbox_layout.addWidget(sandbox_header)

            sandbox_desc = QLabel("Type or dictate a raw phrase to test subtle cleaning and grammar correction:")
            sandbox_desc.setStyleSheet("color: #888; font-size: 12px;")
            sandbox_layout.addWidget(sandbox_desc)

            self.test_input = QLineEdit()
            self.test_input.setPlaceholderText("e.g. hey um can we meet at four pm actually make that five")
            self.test_input.setText("hey um can we meet at four pm actually make that five")
            sandbox_layout.addWidget(self.test_input)

            test_run_row = QHBoxLayout()
            self.format_btn = QPushButton("Run Formatting Test")
            self.format_btn.clicked.connect(self.run_formatting_test)
            test_run_row.addWidget(self.format_btn)
            test_run_row.addStretch()
            sandbox_layout.addLayout(test_run_row)

            self.formatted_output = QTextEdit()
            self.formatted_output.setReadOnly(True)
            self.formatted_output.setMaximumHeight(65)
            self.formatted_output.setPlaceholderText("Formatted result will appear here...")
            sandbox_layout.addWidget(self.formatted_output)

            layout.addWidget(sandbox_card)

        # 4. Privacy Disclaimer
        privacy_note = QLabel("🔒 Privacy: Speech is transcribed locally on your machine. Only the text string is sent to Google AI Studio when AI formatting is enabled.")
        privacy_note.setStyleSheet("color: #71717a; font-size: 11px;")
        privacy_note.setWordWrap(True)
        layout.addWidget(privacy_note)

    def _load_state(self) -> None:
        self.enable_check.setChecked(self.config.gemini_enabled)
        self.offline_check.setChecked(self.config.offline_mode)

        # Populate models
        self.model_combo.clear()
        for m in self._available_models:
            self.model_combo.addItem(m)

        idx = self.model_combo.findText(self.config.gemini_model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)

        # Key from keychain
        key = CredentialManager.get_api_key()
        if key:
            self.key_input.setText(key)

        # Update storage label
        if CredentialManager.is_keychain_available():
            self.storage_label.setText("✓ Stored securely in OS Keychain / Credential Vault.")
        else:
            self.storage_label.setText("⚠️ No OS Keychain available. Stored in memory for this session only.")

    def _toggle_show_key(self) -> None:
        if self.key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_btn.setText("Hide")
        else:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_btn.setText("Show")

    def _paste_key(self) -> None:
        from ..system.clipboard import ClipboardManager

        clip = ClipboardManager.get_text().strip()
        if clip:
            self.key_input.setText(clip)
            self._save_key_from_input()

    def _clear_key(self) -> None:
        self.key_input.clear()
        CredentialManager.delete_api_key()
        self.gemini.set_api_key(None)
        self.status_chip.setText("Key cleared")
        self.status_chip.setStyleSheet("padding: 4px 10px; border-radius: 6px; font-size: 12px; background: rgba(148,151,161,0.12); color: #888;")
        self.config_changed.emit()

    def _save_key_from_input(self) -> None:
        """Save API key upon paste, Enter, or blur (NOT per keystroke)."""
        key = self.key_input.text().strip()
        if key:
            CredentialManager.set_api_key(key)
            self.gemini.set_api_key(key)
        else:
            CredentialManager.delete_api_key()
            self.gemini.set_api_key(None)
        self.config_changed.emit()

    def _on_enable_toggled(self, checked: bool) -> None:
        self.config.gemini_enabled = checked
        self.config.save()
        self.config_changed.emit()

    def _on_offline_toggled(self, checked: bool) -> None:
        self.config.offline_mode = checked
        if checked:
            self.enable_check.setChecked(False)
        self.config.save()
        self.config_changed.emit()

    def _on_model_changed(self, index: int) -> None:
        model = self.model_combo.currentText()
        if model:
            self.config.gemini_model = model
            self.gemini.set_model(model)
            self.config.save()
            self.config_changed.emit()

    def run_connection_test(self) -> None:
        """Probe the connection on a worker thread using the current field value."""
        if self._testing_connection:
            return

        self._save_key_from_input()
        current_key = self.key_input.text().strip()
        current_model = self.model_combo.currentText()

        self._testing_connection = True
        self.test_btn.setEnabled(False)
        self.status_chip.setText("Testing connection...")
        self.status_chip.setStyleSheet("padding: 4px 10px; border-radius: 6px; font-size: 12px; background: rgba(10,147,176,0.15); color: #0A93B0;")

        def worker():
            res = self.gemini.test_connection(api_key=current_key, model=current_model)
            self.test_completed.emit(res)

        threading.Thread(target=worker, daemon=True).start()

    def _on_connection_test_done(self, res: ConnectionTestResult) -> None:
        self._testing_connection = False
        self.test_btn.setEnabled(True)

        if res.success:
            self.status_chip.setText(f"✓ {res.message} — {res.model_name}")
            self.status_chip.setStyleSheet("padding: 4px 10px; border-radius: 6px; font-size: 12px; background: rgba(31,169,113,0.15); color: #1FA971;")
        else:
            self.status_chip.setText(f"✗ {res.message}")
            self.status_chip.setStyleSheet("padding: 4px 10px; border-radius: 6px; font-size: 12px; background: rgba(229,72,77,0.15); color: #E5484D;")

    def run_formatting_test(self) -> None:
        """Run an end-to-end formatting test using the configured prompt."""
        if self._testing_formatting or self.compact_mode:
            return

        self._save_key_from_input()
        raw_text = self.test_input.text().strip()
        if not raw_text:
            return

        self._testing_formatting = True
        self.format_btn.setEnabled(False)
        self.formatted_output.setPlainText("Formatting...")

        def worker():
            out, ok, msg = self.gemini.format_text(raw_text=raw_text, style=self.config.prompt_style)
            self.formatting_test_completed.emit(raw_text, out)

        threading.Thread(target=worker, daemon=True).start()

    def _on_formatting_test_done(self, raw: str, formatted: str) -> None:
        self._testing_formatting = False
        if hasattr(self, "format_btn"):
            self.format_btn.setEnabled(True)
        if hasattr(self, "formatted_output"):
            self.formatted_output.setPlainText(formatted)
