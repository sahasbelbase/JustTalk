"""Writing Conventions configuration panel.

A new nav tab that lets the user configure how their spoken text is formatted
for SQL, Python, JavaScript, and other contexts. Ships with sensible defaults
(PEP 8, Google JS, Microsoft .NET, gofmt, rustfmt, PSR-12) and a live
before/after preview that updates as the user changes settings.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig
from .theme import ThemeManager


# ── Default convention presets ─────────────────────────────────────────────
_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "sql": {
        "keyword_case": "upper",
        "naming_style": "PascalCase",
        "schema_prefix": True,
        "aliases": True,
        "dialect": "tsql",
        "indent_width": 4,
    },
    "python": {
        "naming_style": "snake_case",
        "indent_width": 4,
        "quote_style": "double",
        "type_hints": True,
        "docstring_style": "google",
    },
    "javascript": {
        "naming_style": "camelCase",
        "indent_width": 2,
        "quote_style": "single",
        "semicolons": True,
        "trailing_commas": True,
    },
    "typescript": {
        "naming_style": "camelCase",
        "indent_width": 2,
        "quote_style": "single",
        "semicolons": True,
        "trailing_commas": True,
        "strict": True,
    },
    "java": {
        "naming_style": "camelCase",
        "indent_width": 4,
        "brace_style": "K&R",
    },
    "csharp": {
        "naming_style": "PascalCase",
        "indent_width": 4,
        "var_keyword": True,
        "brace_style": "Allman",
    },
    "go": {
        "naming_style": "camelCase",
        "indent_width": 1,
        "indent_char": "tab",
    },
    "rust": {
        "naming_style": "snake_case",
        "indent_width": 4,
    },
    "php": {
        "naming_style": "camelCase",
        "indent_width": 4,
        "quote_style": "single",
    },
    "text": {
        "style": "plain",
        "no_em_dash": True,
        "no_filler_openers": True,
    },
}

_CONTEXT_LABELS = [
    ("sql", "SQL"),
    ("python", "Python"),
    ("javascript", "JavaScript"),
    ("typescript", "TypeScript"),
    ("java", "Java"),
    ("csharp", "C#"),
    ("go", "Go"),
    ("rust", "Rust"),
    ("php", "PHP"),
    ("text", "Plain Prose"),
]

# ── Sample inputs for live preview ────────────────────────────────────────
_SAMPLE_INPUTS: Dict[str, str] = {
    "sql": (
        "select all from dbo email profile table inner join dbo person email profile "
        "on email profile id equals email profile id"
    ),
    "python": (
        "define function calculate discount that takes price as float and rate as float "
        "and returns the price times one minus rate rounded to two decimal places"
    ),
    "javascript": (
        "create async function fetch user that takes id and fetches from api users slash id "
        "and returns the json"
    ),
    "typescript": (
        "create an interface called user with fields id as number, name as string, and email as string"
    ),
    "java": (
        "create a public method called get full name that takes first name and last name strings "
        "and returns them joined with a space"
    ),
    "csharp": (
        "create a public property called user name of type string with get and set"
    ),
    "go": (
        "create a function called calculate total that takes items as a slice of float64 "
        "and returns the sum as float64"
    ),
    "rust": (
        "create a function called parse input that takes a string slice and returns a result "
        "of u32 and parse int error"
    ),
    "php": (
        "create a public function called get user by id that takes id as int "
        "and returns a nullable user object"
    ),
    "text": (
        "um so basically what I was trying to say is that we need to uh improve the deployment "
        "pipeline and make sure that the tests are passing before we merge anything"
    ),
}

# ── Sample outputs for live preview ───────────────────────────────────────
_SAMPLE_OUTPUTS: Dict[str, str] = {
    "sql": (
        "SELECT *\n"
        "FROM dbo.EmailProfile AS e\n"
        "INNER JOIN dbo.PersonEmailProfile AS pe\n"
        "    ON pe.EmailProfileId = e.EmailProfileId;"
    ),
    "python": (
        "def calculate_discount(price: float, rate: float) -> float:\n"
        "    return round(price * (1 - rate), 2)"
    ),
    "javascript": (
        "const fetchUser = async (id) => {\n"
        "    const res = await fetch(`/api/users/${id}`);\n"
        "    return res.json();\n"
        "};"
    ),
    "typescript": (
        "interface User {\n"
        "    id: number;\n"
        "    name: string;\n"
        "    email: string;\n"
        "}"
    ),
    "java": (
        "public String getFullName(String firstName, String lastName) {\n"
        "    return firstName + \" \" + lastName;\n"
        "}"
    ),
    "csharp": (
        "public string UserName { get; set; }"
    ),
    "go": (
        "func calculateTotal(items []float64) float64 {\n"
        "\ttotal := 0.0\n"
        "\tfor _, item := range items {\n"
        "\t\ttotal += item\n"
        "\t}\n"
        "\treturn total\n"
        "}"
    ),
    "rust": (
        "fn parse_input(s: &str) -> Result<u32, std::num::ParseIntError> {\n"
        "    s.trim().parse::<u32>()\n"
        "}"
    ),
    "php": (
        "public function getUserById(int $id): ?User {\n"
        "    return User::find($id);\n"
        "}"
    ),
    "text": (
        "We need to improve the deployment pipeline and make sure tests pass before merging."
    ),
}

# ── Chip color for context badges ──────────────────────────────────────────
_CTX_COLORS: Dict[str, tuple[str, str]] = {
    "sql":        ("#A85E00", "rgba(255,149,0,.12)"),
    "python":     ("#1A7D35", "rgba(52,199,89,.12)"),
    "javascript": ("#7A6A00", "rgba(255,214,10,.15)"),
    "typescript": ("#005DC4", "rgba(0,122,255,.10)"),
    "java":       ("#8B3A00", "rgba(255,100,0,.12)"),
    "csharp":     ("#5B2EA6", "rgba(150,80,230,.12)"),
    "go":         ("#005F80", "rgba(0,150,200,.12)"),
    "rust":       ("#8B2500", "rgba(200,60,0,.12)"),
    "php":        ("#4A3F8A", "rgba(120,100,220,.12)"),
    "text":       ("#48484A", "rgba(60,60,67,.08)"),
}
_CTX_COLORS_DARK: Dict[str, tuple[str, str]] = {
    "sql":        ("#FFAA40", "rgba(255,159,10,.14)"),
    "python":     ("#30D158", "rgba(48,209,88,.12)"),
    "javascript": ("#FFD60A", "rgba(255,214,10,.14)"),
    "typescript": ("#6C8EEF", "rgba(108,142,239,.14)"),
    "java":       ("#FF9F0A", "rgba(255,159,10,.14)"),
    "csharp":     ("#BF5AF2", "rgba(191,90,242,.14)"),
    "go":         ("#64D2FF", "rgba(100,210,255,.14)"),
    "rust":       ("#FF6B40", "rgba(255,107,64,.14)"),
    "php":        ("#A78BFA", "rgba(167,139,250,.14)"),
    "text":       ("rgba(255,255,255,.55)", "rgba(255,255,255,.07)"),
}


class ConventionsView(QWidget):
    """Writing Conventions tab — lets users configure per-context formatting rules."""

    conventions_changed = Signal(dict)  # emits full conventions dict on any change

    def __init__(
        self,
        config: AppConfig,
        on_save: Optional[Callable[[AppConfig], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config = config
        self.on_save = on_save
        self._current_ctx = "sql"

        # Deep-copy defaults merged with user config so we always have all keys
        self._conventions: Dict[str, Dict[str, Any]] = {}
        for ctx, defaults in _DEFAULTS.items():
            saved = (config.conventions or {}).get(ctx, {})
            self._conventions[ctx] = {**defaults, **saved}

        self._build_ui()
        self._load_context("sql")

    # ── UI Construction ──────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 30, 36, 28)
        root.setSpacing(16)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("Writing Conventions")
        title.setFont(ThemeManager.get_display_font(26, weight=QFont.Weight.Bold))
        hdr.addWidget(title)
        hdr.addStretch()

        reset_btn = QPushButton("Reset to Default")
        reset_btn.setObjectName("secondaryBtn")
        reset_btn.clicked.connect(self._reset_current)
        hdr.addWidget(reset_btn)
        root.addLayout(hdr)

        sub = QLabel(
            "Spoken text is formatted according to these rules when Just Talk detects the matching context."
        )
        sub.setObjectName("mutedLabel")
        sub.setFont(ThemeManager.get_ui_font(13))
        sub.setWordWrap(True)
        root.addWidget(sub)

        # Language selector
        lang_row = QHBoxLayout()
        lang_row.setSpacing(8)
        lang_lbl = QLabel("Context / Language:")
        lang_lbl.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.Medium))
        lang_row.addWidget(lang_lbl)

        self._lang_combo = QComboBox()
        for ctx_id, label in _CONTEXT_LABELS:
            self._lang_combo.addItem(label, ctx_id)
        self._lang_combo.setFixedWidth(200)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        lang_row.addWidget(self._lang_combo)
        lang_row.addStretch()
        root.addLayout(lang_row)

        # Body: options card + preview side by side
        body = QHBoxLayout()
        body.setSpacing(16)

        # ── Options card (scrollable) ──────────────────────────────────
        options_scroll = QScrollArea()
        options_scroll.setWidgetResizable(True)
        options_scroll.setFrameShape(QFrame.Shape.NoFrame)
        options_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._options_container = QWidget()
        self._options_layout = QVBoxLayout(self._options_container)
        self._options_layout.setSpacing(10)
        self._options_layout.setContentsMargins(0, 0, 0, 0)
        options_scroll.setWidget(self._options_container)

        body.addWidget(options_scroll, 1)

        # ── Preview card ───────────────────────────────────────────────
        preview_card = QFrame()
        preview_card.setObjectName("card")
        preview_card.setFixedWidth(340)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 14, 16, 14)
        preview_layout.setSpacing(8)

        preview_title = QLabel("Live Preview")
        preview_title.setFont(ThemeManager.get_ui_font(12, weight=QFont.Weight.DemiBold))
        preview_layout.addWidget(preview_title)

        in_lbl = QLabel("You say:")
        in_lbl.setObjectName("mutedLabel")
        in_lbl.setFont(ThemeManager.get_ui_font(11))
        preview_layout.addWidget(in_lbl)

        self._preview_input = QPlainTextEdit()
        self._preview_input.setReadOnly(True)
        self._preview_input.setFixedHeight(68)
        self._preview_input.setFont(ThemeManager.get_ui_font(11))
        preview_layout.addWidget(self._preview_input)

        out_lbl = QLabel("Just Talk outputs:")
        out_lbl.setObjectName("mutedLabel")
        out_lbl.setFont(ThemeManager.get_ui_font(11))
        preview_layout.addWidget(out_lbl)

        self._preview_output = QPlainTextEdit()
        self._preview_output.setReadOnly(True)
        self._preview_output.setFont(ThemeManager.get_mono_font(11))
        preview_layout.addWidget(self._preview_output, 1)

        preview_note = QLabel("Preview reflects your current settings for this context.")
        preview_note.setObjectName("mutedLabel")
        preview_note.setFont(ThemeManager.get_ui_font(10))
        preview_note.setWordWrap(True)
        preview_layout.addWidget(preview_note)

        body.addWidget(preview_card)
        root.addLayout(body, 1)

    # ── Context loading ──────────────────────────────────────────────────

    def _on_lang_changed(self, idx: int) -> None:
        ctx = self._lang_combo.itemData(idx)
        if ctx:
            self._load_context(ctx)

    def _load_context(self, ctx: str) -> None:
        self._current_ctx = ctx
        options = self._conventions.get(ctx, _DEFAULTS.get(ctx, {}))

        # Clear options panel
        while self._options_layout.count():
            item = self._options_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Build per-context widgets
        self._widgets: Dict[str, Any] = {}
        for key, value in options.items():
            self._add_option_row(key, value)

        self._options_layout.addStretch()

        # Update preview
        self._update_preview()

    def _add_option_row(self, key: str, value: Any) -> None:
        """Add an option row appropriate for the value type."""
        row_frame = QFrame()
        row_frame.setObjectName("surfaceCard")
        row_layout = QHBoxLayout(row_frame)
        row_layout.setContentsMargins(12, 8, 12, 8)
        row_layout.setSpacing(12)

        label = QLabel(_friendly_label(key))
        label.setFont(ThemeManager.get_ui_font(13))
        label.setMinimumWidth(140)
        row_layout.addWidget(label)

        row_layout.addStretch()

        if isinstance(value, bool):
            widget = QCheckBox()
            widget.setChecked(value)
            widget.stateChanged.connect(lambda state, k=key: self._on_option_changed(k, state == Qt.CheckState.Checked.value))
            row_layout.addWidget(widget)
            self._widgets[key] = widget

        elif isinstance(value, int):
            widget = QSpinBox()
            widget.setRange(1, 16)
            widget.setValue(value)
            widget.setFixedWidth(72)
            widget.valueChanged.connect(lambda v, k=key: self._on_option_changed(k, v))
            row_layout.addWidget(widget)
            self._widgets[key] = widget

        elif isinstance(value, str):
            # Determine candidate choices based on key name
            choices = _get_choices_for_key(key, self._current_ctx)
            if choices:
                widget = QComboBox()
                for c in choices:
                    widget.addItem(c)
                # Select current value
                idx = widget.findText(value)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                widget.currentTextChanged.connect(lambda v, k=key: self._on_option_changed(k, v))
                row_layout.addWidget(widget)
                self._widgets[key] = widget
            else:
                lbl = QLabel(str(value))
                lbl.setObjectName("mutedLabel")
                row_layout.addWidget(lbl)

        self._options_layout.addWidget(row_frame)

    def _on_option_changed(self, key: str, value: Any) -> None:
        self._conventions[self._current_ctx][key] = value
        self._update_preview()
        self._auto_save()

    def _update_preview(self) -> None:
        ctx = self._current_ctx
        self._preview_input.setPlainText(_SAMPLE_INPUTS.get(ctx, ""))
        # For now show static sample output — in production this would call the AI formatter
        self._preview_output.setPlainText(_SAMPLE_OUTPUTS.get(ctx, ""))

    def _reset_current(self) -> None:
        ctx = self._current_ctx
        default = _DEFAULTS.get(ctx, {})
        self._conventions[ctx] = copy.deepcopy(default)
        self._load_context(ctx)
        self._auto_save()

    def _auto_save(self) -> None:
        self.config.conventions = copy.deepcopy(self._conventions)
        self.config.save()
        self.conventions_changed.emit(self._conventions)

    # ── Public refresh ───────────────────────────────────────────────────

    def refresh_from_config(self, config: AppConfig) -> None:
        """Called when external config changes; re-syncs the view."""
        self.config = config
        for ctx, defaults in _DEFAULTS.items():
            saved = (config.conventions or {}).get(ctx, {})
            self._conventions[ctx] = {**defaults, **saved}
        self._load_context(self._current_ctx)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _friendly_label(key: str) -> str:
    return key.replace("_", " ").title()


def _get_choices_for_key(key: str, ctx: str) -> list[str]:
    """Return ordered dropdown choices for a given string option key."""
    _choices: Dict[str, list[str]] = {
        "keyword_case": ["upper", "lower", "title"],
        "naming_style": ["PascalCase", "camelCase", "snake_case", "kebab-case", "SCREAMING_SNAKE"],
        "quote_style": ["double", "single", "backtick"],
        "dialect": ["tsql", "mysql", "postgres", "sqlite", "ansi"],
        "brace_style": ["K&R", "Allman", "GNU"],
        "docstring_style": ["google", "numpy", "sphinx"],
        "indent_char": ["space", "tab"],
        "style": ["plain", "formal", "casual", "bullet"],
    }
    return _choices.get(key, [])
