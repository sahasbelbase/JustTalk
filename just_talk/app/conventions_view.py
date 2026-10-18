"""Writing Conventions configuration panel.

A new nav tab that lets the user configure how their spoken text is formatted
for SQL, Python, JavaScript, and other contexts. Ships with sensible defaults
(PEP 8, Google JS, Microsoft .NET, gofmt, rustfmt, PSR-12) and a live
before/after preview that updates as the user changes settings.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from . import icons


# ── Option Descriptions ───────────────────────────────────────────────────
_OPTION_DESCRIPTIONS: Dict[str, str] = {
    "keyword_case": "Capitalization style for statements, clauses, and built-ins.",
    "naming_style": "Default entity identifier casing for tables, variables, and identifiers.",
    "schema_prefix": "Include default object schema in table references (e.g. dbo.).",
    "aliases": "Auto-generate concise mnemonic aliases in queries and join clauses.",
    "dialect": "Database syntax dialect for keyword variations and function calls.",
    "indent_width": "Number of spaces per code clause or block nesting level.",
    "quote_style": "Default quotation marks for string literals.",
    "type_hints": "Add explicit type annotations to arguments and returns.",
    "docstring_style": "Documentation convention for functions and classes.",
    "semicolons": "Terminate statements with explicit semicolons.",
    "trailing_commas": "Include trailing commas in multiline objects and arrays.",
    "strict": "Enforce strict compiler type checks in declarations.",
    "brace_style": "Placement convention for opening and closing curly braces.",
    "var_keyword": "Use var keyword for type inference where appropriate.",
    "indent_char": "Character used for block indentation.",
    "style": "Overall tone and formatting style for plain prose.",
    "no_em_dash": "Avoid inserting em-dashes (—) in transcribed speech.",
    "no_filler_openers": "Strip disfluencies and conversational filler openings.",
}


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
        self._rule_widgets: list[tuple[str, QFrame]] = []

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
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(14)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("Writing Conventions")
        title.setFont(ThemeManager.get_display_font(24, weight=QFont.Weight.Bold))
        hdr.addWidget(title)

        syntax_pill = QLabel("Syntax Engine")
        syntax_pill.setObjectName("secondaryPill")
        syntax_pill.setFont(ThemeManager.get_mono_font(10, weight=QFont.Weight.Bold))
        hdr.addWidget(syntax_pill)

        hdr.addStretch()

        reset_btn = QPushButton("Reset to Default")
        reset_btn.setObjectName("secondaryBtn")
        reset_btn.setIcon(icons.icon("refresh", size=13))
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_current)
        hdr.addWidget(reset_btn)
        root.addLayout(hdr)

        sub = QLabel(
            "Spoken text is formatted according to these rules when Just Talk detects the matching context."
        )
        sub.setObjectName("mutedLabel")
        sub.setFont(ThemeManager.get_ui_font(12))
        sub.setWordWrap(True)
        root.addWidget(sub)

        # Filter bar: Context Dropdown + Auto-Detect Pill + Rule Search
        filter_bar = QFrame()
        filter_bar.setObjectName("surfaceCard")
        filter_bar.setStyleSheet("""
            QFrame#surfaceCard {
                border-radius: 10px;
                padding: 4px 8px;
            }
        """)
        fb_layout = QHBoxLayout(filter_bar)
        fb_layout.setContentsMargins(12, 8, 12, 8)
        fb_layout.setSpacing(12)

        lang_lbl = QLabel("Context / Language:")
        lang_lbl.setFont(ThemeManager.get_ui_font(12, weight=QFont.Weight.DemiBold))
        fb_layout.addWidget(lang_lbl)

        self._lang_combo = QComboBox()
        for ctx_id, label in _CONTEXT_LABELS:
            self._lang_combo.addItem(label, ctx_id)
        self._lang_combo.setFixedWidth(160)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        fb_layout.addWidget(self._lang_combo)

        autodetect_pill = QLabel("✦ Auto-detect enabled")
        autodetect_pill.setObjectName("statusPill")
        autodetect_pill.setFont(ThemeManager.get_mono_font(10, weight=QFont.Weight.Medium))
        fb_layout.addWidget(autodetect_pill)

        fb_layout.addStretch()

        # Rule search input
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Filter rules...")
        self._search_input.setFixedWidth(180)
        self._search_input.textChanged.connect(self._filter_rules)
        fb_layout.addWidget(self._search_input)

        root.addWidget(filter_bar)

        # Body: options card + live preview side by side
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

        body.addWidget(options_scroll, 7)

        # ── Preview card ───────────────────────────────────────────────
        preview_card = QFrame()
        preview_card.setObjectName("card")
        preview_card.setMinimumWidth(380)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(18, 16, 18, 16)
        preview_layout.setSpacing(10)

        # Preview header
        p_hdr = QHBoxLayout()
        p_hdr.setSpacing(8)
        self.preview_title = QLabel("Live Preview: SQL Context")
        self.preview_title.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        p_hdr.addWidget(self.preview_title)

        p_hdr.addStretch()

        active_pill = QLabel("● Active Format")
        active_pill.setObjectName("statusPill")
        active_pill.setFont(ThemeManager.get_mono_font(10, weight=QFont.Weight.Medium))
        p_hdr.addWidget(active_pill)
        preview_layout.addLayout(p_hdr)

        # "You say:" header
        in_hdr = QHBoxLayout()
        in_lbl = QLabel("YOU SAY")
        in_lbl.setObjectName("mutedLabel")
        in_lbl.setFont(ThemeManager.get_mono_font(10, weight=QFont.Weight.Bold))
        in_hdr.addWidget(in_lbl)
        in_hdr.addStretch()
        preview_layout.addLayout(in_hdr)

        self._preview_input = QPlainTextEdit()
        self._preview_input.setReadOnly(True)
        self._preview_input.setFixedHeight(64)
        self._preview_input.setFont(ThemeManager.get_ui_font(11))
        self._preview_input.setStyleSheet("""
            QPlainTextEdit {
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 6px;
            }
        """)
        preview_layout.addWidget(self._preview_input)

        # Downward transform indicator
        arrow_row = QHBoxLayout()
        arrow_row.addStretch()
        arrow_icon_lbl = QLabel("↓")
        arrow_icon_lbl.setObjectName("mutedLabel")
        arrow_icon_lbl.setFont(ThemeManager.get_mono_font(13, weight=QFont.Weight.Bold))
        arrow_row.addWidget(arrow_icon_lbl)
        arrow_row.addStretch()
        preview_layout.addLayout(arrow_row)

        # "Just Talk outputs:" header + Copy button
        out_hdr = QHBoxLayout()
        out_lbl = QLabel("JUST TALK OUTPUTS")
        out_lbl.setObjectName("mutedLabel")
        out_lbl.setFont(ThemeManager.get_mono_font(10, weight=QFont.Weight.Bold))
        out_hdr.addWidget(out_lbl)
        out_hdr.addStretch()

        self.copy_preview_btn = QPushButton("Copy")
        self.copy_preview_btn.setObjectName("secondaryBtn")
        self.copy_preview_btn.setIcon(icons.icon("copy", size=12))
        self.copy_preview_btn.setFont(ThemeManager.get_ui_font(10, weight=QFont.Weight.Medium))
        self.copy_preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_preview_btn.clicked.connect(self._copy_preview_output)
        out_hdr.addWidget(self.copy_preview_btn)
        preview_layout.addLayout(out_hdr)

        self._preview_output = QPlainTextEdit()
        self._preview_output.setReadOnly(True)
        self._preview_output.setFont(ThemeManager.get_mono_font(11))
        self._preview_output.setStyleSheet("""
            QPlainTextEdit {
                background-color: #14161A;
                color: #F3F4F6;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 8px;
            }
        """)
        preview_layout.addWidget(self._preview_output, 1)

        preview_note = QLabel("An example of how your current settings shape dictated code.")
        preview_note.setObjectName("mutedLabel")
        preview_note.setFont(ThemeManager.get_ui_font(10))
        preview_note.setWordWrap(True)
        preview_layout.addWidget(preview_note)

        body.addWidget(preview_card, 5)
        root.addLayout(body, 1)

    # ── Context loading ──────────────────────────────────────────────────

    def _on_lang_changed(self, idx: int) -> None:
        ctx = self._lang_combo.itemData(idx)
        if ctx:
            self._load_context(ctx)

    def _load_context(self, ctx: str) -> None:
        self._current_ctx = ctx
        label_text = dict(_CONTEXT_LABELS).get(ctx, ctx.upper())
        self.preview_title.setText(f"Live Preview: {label_text} Context")
        options = self._conventions.get(ctx, _DEFAULTS.get(ctx, {}))

        # Clear options panel
        while self._options_layout.count():
            item = self._options_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._rule_widgets = []
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
        row_layout.setContentsMargins(14, 10, 14, 10)
        row_layout.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        label = QLabel(_friendly_label(key))
        label.setFont(ThemeManager.get_ui_font(13, weight=QFont.Weight.DemiBold))
        text_layout.addWidget(label)

        desc = QLabel(_OPTION_DESCRIPTIONS.get(key, ""))
        desc.setObjectName("mutedLabel")
        desc.setFont(ThemeManager.get_ui_font(11))
        desc.setWordWrap(True)
        text_layout.addWidget(desc)

        row_layout.addLayout(text_layout, 1)

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
            choices = _get_choices_for_key(key, self._current_ctx)
            if choices:
                widget = QComboBox()
                for c in choices:
                    widget.addItem(c)
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

        self._rule_widgets.append((key, row_frame))
        self._options_layout.addWidget(row_frame)

    def _filter_rules(self, query: str) -> None:
        q = (query or "").strip().lower()
        for key, frame in self._rule_widgets:
            label = _friendly_label(key).lower()
            desc = _OPTION_DESCRIPTIONS.get(key, "").lower()
            visible = (q in label) or (q in desc) if q else True
            frame.setVisible(visible)

    def _on_option_changed(self, key: str, value: Any) -> None:
        self._conventions[self._current_ctx][key] = value
        self._update_preview()
        self._auto_save()

    def _update_preview(self) -> None:
        ctx = self._current_ctx
        self._preview_input.setPlainText(_SAMPLE_INPUTS.get(ctx, ""))
        options = self._conventions.get(ctx, {})
        formatted = self._generate_preview_output(ctx, options)
        self._preview_output.setPlainText(formatted)

    def _generate_preview_output(self, ctx: str, options: dict) -> str:
        if ctx == "sql":
            kw = options.get("keyword_case", "upper")
            schema = "dbo." if options.get("schema_prefix", True) else ""
            aliases = options.get("aliases", True)
            indent = " " * options.get("indent_width", 4)

            sel = "SELECT *" if kw == "upper" else ("Select *" if kw == "title" else "select *")
            frm = "FROM" if kw == "upper" else ("From" if kw == "title" else "from")
            inn = "INNER JOIN" if kw == "upper" else ("Inner Join" if kw == "title" else "inner join")
            as_kw = "AS" if kw == "upper" else ("As" if kw == "title" else "as")
            on_kw = "ON" if kw == "upper" else ("On" if kw == "title" else "on")

            if aliases:
                return (
                    f"{sel}\n"
                    f"{frm} {schema}EmailProfile {as_kw} e\n"
                    f"{inn} {schema}PersonEmailProfile {as_kw} pe\n"
                    f"{indent}{on_kw} pe.EmailProfileId = e.EmailProfileId;"
                )
            else:
                return (
                    f"{sel}\n"
                    f"{frm} {schema}EmailProfile\n"
                    f"{inn} {schema}PersonEmailProfile\n"
                    f"{indent}{on_kw} {schema}PersonEmailProfile.EmailProfileId = {schema}EmailProfile.EmailProfileId;"
                )
        elif ctx == "python":
            naming = options.get("naming_style", "snake_case")
            fn_name = "calculate_discount" if naming == "snake_case" else ("calculateDiscount" if naming == "camelCase" else "CalculateDiscount")
            hints = options.get("type_hints", True)
            indent = " " * options.get("indent_width", 4)
            sig = f"def {fn_name}(price: float, rate: float) -> float:" if hints else f"def {fn_name}(price, rate):"
            return f"{sig}\n{indent}return round(price * (1 - rate), 2)"
        elif ctx in ("javascript", "typescript"):
            naming = options.get("naming_style", "camelCase")
            fn_name = "fetchUser" if naming == "camelCase" else "fetch_user"
            semi = ";" if options.get("semicolons", True) else ""
            quotes = options.get("quote_style", "single")
            q = "'" if quotes == "single" else ('"' if quotes == "double" else "`")
            indent = " " * options.get("indent_width", 2)
            if ctx == "typescript" and options.get("strict", True):
                return (
                    f"interface User {{\n{indent}id: number{semi}\n{indent}name: string{semi}\n{indent}email: string{semi}\n}}\n\n"
                    f"const {fn_name} = async (id: number): Promise<User> => {{\n"
                    f"{indent}const res = await fetch({q}/api/users/${{id}}{q}){semi}\n"
                    f"{indent}return res.json(){semi}\n"
                    f"}}{semi}"
                )
            return (
                f"const {fn_name} = async (id) => {{\n"
                f"{indent}const res = await fetch({q}/api/users/${{id}}{q}){semi}\n"
                f"{indent}return res.json(){semi}\n"
                f"}}{semi}"
            )
        elif ctx == "text":
            if options.get("no_filler_openers", True):
                return "We need to improve the deployment pipeline and make sure tests pass before merging."
            else:
                return "Um, so basically what I was trying to say is that we need to improve the deployment pipeline and make sure tests pass before merging."
        return _SAMPLE_OUTPUTS.get(ctx, "")

    def _copy_preview_output(self) -> None:
        text = self._preview_output.toPlainText()
        if not text:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
        self.copy_preview_btn.setText("Copied!")
        self.copy_preview_btn.setIcon(icons.icon("check", active_color="#10B981", size=12))
        QTimer.singleShot(1500, self._revert_copy_btn)

    def _revert_copy_btn(self) -> None:
        self.copy_preview_btn.setText("Copy")
        self.copy_preview_btn.setIcon(icons.icon("copy", size=12))

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
