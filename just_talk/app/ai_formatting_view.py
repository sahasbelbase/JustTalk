"""Reusable Multi-Provider AI Formatting component used in Settings and Onboarding."""

from __future__ import annotations

import sys
import threading
from typing import Callable, Optional, Union

from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QFont
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
from ..ai.providers import (
    AIProvider,
    MultiProviderFormatter,
    PROVIDER_REGISTRY,
    get_provider,
    get_provider_list,
)
from ..config import AppConfig
from ..security import CredentialManager
from .theme import ThemeManager
from .ui_thread import run_on_ui_thread


class AIFormattingView(QWidget):
    """
    Multi-Provider AI Formatting configuration & sandbox testing component.
    Supports Google Gemini, OpenAI, Anthropic Claude, xAI Grok, Groq,
    OpenRouter (Codex/multi-model), DeepSeek, and Custom OpenAI-compatible APIs.
    """

    test_completed = Signal(object)  # ConnectionTestResult
    formatting_test_completed = Signal(str, str)  # raw, formatted
    config_changed = Signal()

    def __init__(
        self,
        config: AppConfig,
        gemini: Union[GeminiFormatter, MultiProviderFormatter],
        parent: Optional[QWidget] = None,
        compact_mode: bool = False,
    ):
        super().__init__(parent)
        self.config = config
        self.formatter = gemini
        self.compact_mode = compact_mode

        self._testing_connection = False
        self._testing_formatting = False
        self._fetching_models = False

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

        self.enable_check = QCheckBox("Enable AI formatting (Auto-punctuation, filler removal, smart cleanup)")
        self.enable_check.toggled.connect(self._on_enable_toggled)
        toggles_layout.addWidget(self.enable_check)

        # Offline mode lives in Settings › Voice & Speech › Privacy Mode; a second checkbox
        # here for the same setting got out of sync with it.

        layout.addWidget(toggles_card)

        # 2. Provider Selection & Configuration Card
        provider_card = QFrame()
        provider_card.setObjectName("surfaceCard")
        provider_layout = QVBoxLayout(provider_card)
        provider_layout.setSpacing(12)

        # Provider Selector Row
        provider_row = QHBoxLayout()
        provider_row.setSpacing(10)
        provider_label = QLabel("AI Provider:")
        provider_label.setFont(ThemeManager.font(13, family="ui"))
        provider_row.addWidget(provider_label)

        self.provider_combo = QComboBox()
        for p in get_provider_list():
            self.provider_combo.addItem(p.display_name, p.id)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_row.addWidget(self.provider_combo, 1)

        provider_layout.addLayout(provider_row)

        # Custom Base URL row (shown for 'custom' provider, or optional override)
        self.custom_url_widget = QWidget()
        custom_url_layout = QHBoxLayout(self.custom_url_widget)
        custom_url_layout.setContentsMargins(0, 0, 0, 0)
        custom_url_layout.setSpacing(10)
        custom_url_lbl = QLabel("API Base URL:")
        custom_url_lbl.setFont(ThemeManager.font(12, family="ui"))
        custom_url_layout.addWidget(custom_url_lbl)

        self.custom_url_input = QLineEdit()
        self.custom_url_input.setPlaceholderText("https://api.openai.com/v1 or http://localhost:11434/v1")
        self.custom_url_input.returnPressed.connect(self._on_custom_url_changed)
        self.custom_url_input.editingFinished.connect(self._on_custom_url_changed)
        custom_url_layout.addWidget(self.custom_url_input, 1)
        provider_layout.addWidget(self.custom_url_widget)

        # API Key Header
        self.key_header = QLabel("API Key")
        self.key_header.setFont(ThemeManager.font(13, family="ui"))
        provider_layout.addWidget(self.key_header)

        # Input + Action Buttons
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("Paste your API key...")
        self.key_input.returnPressed.connect(self._save_key_from_input)
        self.key_input.editingFinished.connect(self._save_key_from_input)
        input_row.addWidget(self.key_input)

        self.show_btn = QPushButton("Show")
        self.show_btn.setMinimumWidth(70)
        self.show_btn.clicked.connect(self._toggle_show_key)
        input_row.addWidget(self.show_btn)

        self.paste_btn = QPushButton("Paste")
        self.paste_btn.setMinimumWidth(74)
        self.paste_btn.clicked.connect(self._paste_key)
        input_row.addWidget(self.paste_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setMinimumWidth(70)
        self.clear_btn.clicked.connect(self._clear_key)
        input_row.addWidget(self.clear_btn)

        provider_layout.addLayout(input_row)

        # Key Website Link / Hint
        key_meta_row = QHBoxLayout()
        self.storage_label = QLabel("Stored securely in private credentials (mode 0600).")
        self.storage_label.setStyleSheet("color: #888; font-size: 11px;")
        key_meta_row.addWidget(self.storage_label)

        key_meta_row.addStretch()
        self.get_key_link_btn = QPushButton("Get API key")
        self.get_key_link_btn.setObjectName("flatBtn")
        self.get_key_link_btn.setStyleSheet("font-size: 11px; color: #6C8EEF; border: none; background: transparent; padding: 0;")
        self.get_key_link_btn.clicked.connect(self._open_provider_website)
        key_meta_row.addWidget(self.get_key_link_btn)
        provider_layout.addLayout(key_meta_row)

        # Model selection and Test Connection row
        controls_row = QHBoxLayout()
        controls_row.setSpacing(10)

        controls_row.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)  # User can type any custom model ID!
        self.model_combo.setMinimumWidth(220)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        controls_row.addWidget(self.model_combo, 1)

        self.fetch_models_btn = QPushButton("Fetch models")
        self.fetch_models_btn.setToolTip("Fetch available models from the provider API")
        self.fetch_models_btn.setMinimumWidth(80)
        self.fetch_models_btn.clicked.connect(self.run_fetch_models)
        controls_row.addWidget(self.fetch_models_btn)

        self.test_btn = QPushButton("Test Connection")
        self.test_btn.setObjectName("primaryBtn")
        self.test_btn.clicked.connect(self.run_connection_test)
        controls_row.addWidget(self.test_btn)

        provider_layout.addLayout(controls_row)

        # Status Chip
        self.status_chip = QLabel("Not tested")
        self.status_chip.setStyleSheet("padding: 4px 10px; border-radius: 6px; font-size: 12px; background: rgba(148,151,161,0.12); color: #888;")
        provider_layout.addWidget(self.status_chip)

        layout.addWidget(provider_card)

        # 3. Test Formatting Sandbox (if not in compact mode)
        if not self.compact_mode:
            sandbox_card = QFrame()
            sandbox_card.setObjectName("surfaceCard")
            sandbox_layout = QVBoxLayout(sandbox_card)
            sandbox_layout.setSpacing(8)

            sandbox_header = QLabel("Test Formatting Sandbox")
            sandbox_header.setFont(ThemeManager.font(14, family="ui"))
            sandbox_layout.addWidget(sandbox_header)

            sandbox_desc = QLabel("Type or dictate a raw phrase to test cleaning and formatting with your selected AI model:")
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
        self.privacy_note = QLabel(
            "Privacy: speech is transcribed on your device. "
            "Only the transcribed text string is sent to the chosen AI provider when AI formatting is enabled."
        )
        self.privacy_note.setStyleSheet("color: #71717a; font-size: 11px;")
        self.privacy_note.setWordWrap(True)
        layout.addWidget(self.privacy_note)

    # -------------------------------------------------------------------------
    # State Loading & Provider Switching
    # -------------------------------------------------------------------------

    def _get_active_provider_id(self) -> str:
        return getattr(self.config, "ai_provider", "gemini") or "gemini"

    def _load_state(self) -> None:
        self.enable_check.setChecked(self.config.gemini_enabled)

        # Select provider
        active_pid = self._get_active_provider_id()
        idx = self.provider_combo.findData(active_pid)
        if idx >= 0:
            self.provider_combo.blockSignals(True)
            self.provider_combo.setCurrentIndex(idx)
            self.provider_combo.blockSignals(False)

        self._refresh_provider_ui(active_pid, initial_load=True)

    def _refresh_provider_ui(self, provider_id: str, initial_load: bool = False) -> None:
        provider = get_provider(provider_id)
        if not provider:
            provider = get_provider("gemini")
            provider_id = "gemini"

        # 1. Custom URL visibility
        if provider_id in ("custom", "ollama"):
            self.custom_url_widget.show()
            if provider_id == "ollama":
                custom_url = getattr(self.config, "ollama_base_url", "http://localhost:11434/v1") or "http://localhost:11434/v1"
                self.custom_url_input.setPlaceholderText("http://localhost:11434/v1")
            else:
                custom_url = getattr(self.config, "custom_api_base_url", "") or CredentialManager.get_custom_base_url() or ""
                self.custom_url_input.setPlaceholderText("https://api.openai.com/v1 or http://localhost:11434/v1")
            self.custom_url_input.setText(custom_url)
        else:
            self.custom_url_widget.hide()

        # 2. Header and Hint
        if provider_id == "ollama":
            self.key_header.setText("Ollama Local Instance (Zero API Key Needed)")
            self.key_input.setEnabled(False)
            self.key_input.setPlaceholderText("Local offline model · 100% on-device · Zero internet required")
            self.show_btn.hide()
            self.paste_btn.hide()
            self.clear_btn.hide()
            self.storage_label.setText("Runs locally via Ollama. No tokens, no account, completely private.")
        else:
            name = provider.display_name
            self.key_header.setText(f"{name} key" if name.endswith("API") else f"{name} API key")
            self.key_input.setEnabled(True)
            self.key_input.setPlaceholderText(f"Paste your {provider.display_name} key ({provider.key_prefix_hint})...")
            self.show_btn.show()
            self.paste_btn.show()
            self.clear_btn.show()
            self.storage_label.setText("Stored securely in private credentials (mode 0600).")

        # 3. Populate models
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in provider.popular_models:
            self.model_combo.addItem(m)

        # Active model selection
        saved_model = getattr(self.config, "ai_model", "")
        if not saved_model and provider_id == "gemini":
            saved_model = self.config.gemini_model
        if not saved_model and provider_id == "ollama":
            saved_model = getattr(self.config, "ollama_model", "")
        if not saved_model:
            saved_model = provider.default_model

        if saved_model:
            idx = self.model_combo.findText(saved_model)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            else:
                self.model_combo.setEditText(saved_model)

        self.model_combo.blockSignals(False)

        # 4. Load key for this provider
        key = CredentialManager.get_provider_api_key(provider_id)
        self.key_input.blockSignals(True)
        self.key_input.setText(key or "")
        self.key_input.blockSignals(False)

        # 5. Link button
        if provider.website_url:
            self.get_key_link_btn.show()
            if provider_id == "ollama":
                self.get_key_link_btn.setText("Download Ollama")
            else:
                self.get_key_link_btn.setText(f"Get {provider.display_name} key")
        else:
            self.get_key_link_btn.hide()

        # 6. Synchronize formatter instance
        if hasattr(self.formatter, "set_provider"):
            custom_url = self.custom_url_input.text().strip() if provider_id in ("custom", "ollama") else None
            self.formatter.set_provider(
                provider_id=provider_id,
                api_key=key,
                model_name=self.model_combo.currentText().strip() or provider.default_model,
                custom_base_url=custom_url,
            )

        if not initial_load:
            self.status_chip.setText("Not tested")
            self.status_chip.setStyleSheet("padding: 4px 10px; border-radius: 6px; font-size: 12px; background: rgba(148,151,161,0.12); color: #888;")

    def _open_provider_website(self) -> None:
        pid = self.provider_combo.currentData()
        provider = get_provider(pid)
        if provider and provider.website_url:
            QDesktopServices.openUrl(QUrl(provider.website_url))

    def _on_provider_changed(self, index: int) -> None:
        pid = self.provider_combo.itemData(index)
        self.config.ai_provider = pid
        self._refresh_provider_ui(pid)
        self.config.save()
        self.config_changed.emit()

    def _on_custom_url_changed(self) -> None:
        url = self.custom_url_input.text().strip()
        pid = self.provider_combo.currentData()
        if pid == "ollama":
            self.config.ollama_base_url = url
        else:
            self.config.custom_api_base_url = url
            CredentialManager.set_custom_base_url(url)
        if hasattr(self.formatter, "set_custom_base_url"):
            self.formatter.set_custom_base_url(url)
        self.config.save()
        self.config_changed.emit()

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
        pid = self.provider_combo.currentData()
        self.key_input.clear()
        CredentialManager.delete_provider_api_key(pid)
        if hasattr(self.formatter, "set_api_key"):
            self.formatter.set_api_key(None)
        self.status_chip.setText("Key cleared")
        self.status_chip.setStyleSheet("padding: 4px 10px; border-radius: 6px; font-size: 12px; background: rgba(148,151,161,0.12); color: #888;")
        self.config_changed.emit()

    def _save_key_from_input(self) -> None:
        pid = self.provider_combo.currentData()
        key = self.key_input.text().strip()
        if key:
            CredentialManager.set_provider_api_key(pid, key)
            if hasattr(self.formatter, "set_api_key"):
                self.formatter.set_api_key(key)
        else:
            CredentialManager.delete_provider_api_key(pid)
            if hasattr(self.formatter, "set_api_key"):
                self.formatter.set_api_key(None)
        self.config_changed.emit()

    def _on_enable_toggled(self, checked: bool) -> None:
        self.config.gemini_enabled = checked
        self.config.save()
        self.config_changed.emit()

    def _on_model_changed(self, text: str) -> None:
        model = text.strip()
        if model:
            self.config.ai_model = model
            active_pid = self._get_active_provider_id()
            if active_pid == "gemini":
                self.config.gemini_model = model
            elif active_pid == "ollama":
                self.config.ollama_model = model
            if hasattr(self.formatter, "set_model"):
                self.formatter.set_model(model)
            self.config.save()
            self.config_changed.emit()

    # -------------------------------------------------------------------------
    # Connection Testing & Model Fetching
    # -------------------------------------------------------------------------

    def run_fetch_models(self) -> None:
        """Fetch models from the provider API asynchronously."""
        if self._fetching_models:
            return

        self._save_key_from_input()
        pid = self.provider_combo.currentData()
        current_key = self.key_input.text().strip()
        custom_url = self.custom_url_input.text().strip() if pid in ("custom", "ollama") else None

        self._fetching_models = True
        self.fetch_models_btn.setEnabled(False)
        self.fetch_models_btn.setText("...")

        def worker():
            models = []
            if hasattr(self.formatter, "fetch_available_models"):
                models = self.formatter.fetch_available_models(api_key=current_key, custom_base_url=custom_url)

            def done():
                self._fetching_models = False
                self.fetch_models_btn.setEnabled(True)
                self.fetch_models_btn.setText("Fetch models")
                if models:
                    current_text = self.model_combo.currentText()
                    self.model_combo.blockSignals(True)
                    self.model_combo.clear()
                    for m in models:
                        self.model_combo.addItem(m)
                    if current_text:
                        idx = self.model_combo.findText(current_text)
                        if idx >= 0:
                            self.model_combo.setCurrentIndex(idx)
                        else:
                            self.model_combo.setEditText(current_text)
                    self.model_combo.blockSignals(False)

            run_on_ui_thread(done)

        threading.Thread(target=worker, daemon=True).start()

    def run_connection_test(self) -> None:
        """Probe the connection on a worker thread using the current field value."""
        if self._testing_connection:
            return

        self._save_key_from_input()
        pid = self.provider_combo.currentData()
        current_key = self.key_input.text().strip()
        current_model = self.model_combo.currentText().strip()
        custom_url = self.custom_url_input.text().strip() if pid in ("custom", "ollama") else None

        self._testing_connection = True
        self.test_btn.setEnabled(False)
        self.status_chip.setText("Testing connection...")
        self.status_chip.setStyleSheet("padding: 4px 10px; border-radius: 6px; font-size: 12px; background: rgba(108,142,239,0.12); color: #6C8EEF;")

        def worker():
            if hasattr(self.formatter, "test_connection"):
                res = self.formatter.test_connection(api_key=current_key, model=current_model, custom_base_url=custom_url)
            else:
                res = ConnectionTestResult(
                    success=False, status_code=0, latency_ms=0,
                    message="Formatter does not support connection test",
                    model_name=current_model, timestamp=0.0
                )
            self.test_completed.emit(res)

        threading.Thread(target=worker, daemon=True).start()

    def _on_connection_test_done(self, res: ConnectionTestResult) -> None:
        self._testing_connection = False
        self.test_btn.setEnabled(True)

        if res.success:
            self.status_chip.setText(f"{res.message} · {res.model_name}")
            self.status_chip.setStyleSheet("padding: 4px 10px; border-radius: 6px; font-size: 12px; background: rgba(48,209,88,0.12); color: #30D158;")
        else:
            self.status_chip.setText(res.message)
            self.status_chip.setStyleSheet("padding: 4px 10px; border-radius: 6px; font-size: 12px; background: rgba(255,69,58,0.10); color: #FF453A;")

    # -------------------------------------------------------------------------
    # Formatting Sandbox Test
    # -------------------------------------------------------------------------

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
            out, ok, msg = self.formatter.format_text(raw_text=raw_text, style=self.config.prompt_style)
            self.formatting_test_completed.emit(raw_text, out)

        threading.Thread(target=worker, daemon=True).start()

    def _on_formatting_test_done(self, raw: str, formatted: str) -> None:
        self._testing_formatting = False
        if hasattr(self, "format_btn"):
            self.format_btn.setEnabled(True)
        if hasattr(self, "formatted_output"):
            self.formatted_output.setPlainText(formatted)
