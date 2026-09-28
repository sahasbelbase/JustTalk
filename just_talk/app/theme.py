"""Single central theme module: design tokens, typography, QPalette, and QSS generator."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class ColorTokens:
    """Semantic color tokens for Light and Dark themes."""

    bg: str
    surface: str
    surface_raised: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_soft: str
    on_accent: str

    # Status colors
    listening: str
    action: str
    processing: str
    success: str
    warning: str
    clipboard: str


LIGHT_TOKENS = ColorTokens(
    bg="#FFFFFF",
    surface="#F5F5F7",
    surface_raised="#E8E8ED",
    border="rgba(0, 0, 0, 0.08)",
    text="#1D1D1F",
    text_muted="#6E6E73",
    accent="#007AFF",
    accent_hover="#0066D6",
    accent_soft="rgba(0, 122, 255, 0.10)",
    on_accent="#FFFFFF",
    listening="#FF3B30",
    action="#AF52DE",
    processing="#5AC8FA",
    success="#34C759",
    warning="#FF9500",
    clipboard="#007AFF",
)

DARK_TOKENS = ColorTokens(
    bg="#1C1C1E",
    surface="#2C2C2E",
    surface_raised="#3A3A3C",
    border="rgba(255, 255, 255, 0.08)",
    text="#F5F5F7",
    text_muted="#98989D",
    accent="#0A84FF",
    accent_hover="#409CFF",
    accent_soft="rgba(10, 132, 255, 0.16)",
    on_accent="#FFFFFF",
    listening="#FF453A",
    action="#BF5AF2",
    processing="#64D2FF",
    success="#30D158",
    warning="#FF9F0A",
    clipboard="#0A84FF",
)


class ThemeManager:
    """Central manager for fonts, color schemes, stylesheets, and OS theme sync."""

    _fonts_loaded = False
    _ui_font_family = "Inter"
    _display_font_family = "Instrument Serif"
    _mono_font_family = "JetBrains Mono"

    @classmethod
    def load_fonts(cls) -> None:
        """Load bundled variable fonts, falling back to system fonts on error."""
        if cls._fonts_loaded:
            return

        fonts_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
        font_files = {
            "ui": fonts_dir / "Inter-Variable.ttf",
            "display": fonts_dir / "InstrumentSerif-Regular.ttf",
            "mono": fonts_dir / "JetBrainsMono-Variable.ttf",
        }

        # 1. UI Font
        if font_files["ui"].exists():
            font_id = QFontDatabase.addApplicationFont(str(font_files["ui"]))
            if font_id >= 0:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    cls._ui_font_family = families[0]
            else:
                cls._ui_font_family = "SF Pro" if sys.platform == "darwin" else "Segoe UI Variable"
        else:
            cls._ui_font_family = "SF Pro" if sys.platform == "darwin" else "Segoe UI Variable"

        # 2. Display Font (Serif)
        if font_files["display"].exists():
            font_id = QFontDatabase.addApplicationFont(str(font_files["display"]))
            if font_id >= 0:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    cls._display_font_family = families[0]
            else:
                cls._display_font_family = "New York" if sys.platform == "darwin" else "Georgia"
        else:
            cls._display_font_family = "New York" if sys.platform == "darwin" else "Georgia"

        # 3. Monospace Font
        if font_files["mono"].exists():
            font_id = QFontDatabase.addApplicationFont(str(font_files["mono"]))
            if font_id >= 0:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    cls._mono_font_family = families[0]
            else:
                cls._mono_font_family = "SF Mono" if sys.platform == "darwin" else "Consolas"
        else:
            cls._mono_font_family = "SF Mono" if sys.platform == "darwin" else "Consolas"

        cls._fonts_loaded = True

    @classmethod
    def font(cls, size: int = 15, weight: QFont.Weight = QFont.Weight.Normal, family: str = "ui") -> QFont:
        """Construct a standardized font from the design system type scale."""
        cls.load_fonts()
        if family == "display":
            f_name = cls._display_font_family
        elif family == "mono":
            f_name = cls._mono_font_family
        else:
            f_name = cls._ui_font_family

        f = QFont(f_name, size)
        f.setWeight(weight)
        if size >= 28:
            f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98.0)  # Subtle negative tracking
        return f

    @classmethod
    def get_tokens(cls, is_dark: bool) -> ColorTokens:
        return DARK_TOKENS if is_dark else LIGHT_TOKENS

    @classmethod
    def is_dark(cls, appearance_setting: str = "system") -> bool:
        """Resolve active theme: explicit 'light'/'dark' or query OS."""
        if appearance_setting == "dark":
            return True
        elif appearance_setting == "light":
            return False

        # System auto-detection
        app = QApplication.instance()
        if app is not None and hasattr(app, "styleHints"):
            hints = app.styleHints()
            if hasattr(hints, "colorScheme"):
                return hints.colorScheme() == Qt.ColorScheme.Dark

        # Platform fallbacks
        if sys.platform == "darwin":
            try:
                from AppKit import NSApp

                if NSApp():
                    appr = NSApp().effectiveAppearance().name()
                    return "dark" in appr.lower()
            except Exception:
                pass
        elif sys.platform == "win32":
            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                )
                val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return val == 0
            except Exception:
                pass

        return True  # Default to soft graphite dark

    @classmethod
    def get_palette(cls, is_dark: bool) -> QPalette:
        """Generate a native QPalette matching the color tokens."""
        t = cls.get_tokens(is_dark)
        pal = QPalette()

        pal.setColor(QPalette.ColorRole.Window, QColor(t.bg))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(t.text))
        pal.setColor(QPalette.ColorRole.Base, QColor(t.surface))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(t.surface_raised))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.surface_raised))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor(t.text))
        pal.setColor(QPalette.ColorRole.Text, QColor(t.text))
        pal.setColor(QPalette.ColorRole.Button, QColor(t.surface_raised))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(t.text))
        pal.setColor(QPalette.ColorRole.BrightText, QColor(t.on_accent))
        pal.setColor(QPalette.ColorRole.Highlight, QColor(t.accent))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t.on_accent))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t.text_muted))
        return pal

    @classmethod
    def get_stylesheet(cls, is_dark: bool) -> str:
        """Generate central QSS stylesheet with WCAG AA contrast and semantic styling."""
        t = cls.get_tokens(is_dark)
        ui_font = cls._ui_font_family

        return f"""
        * {{
            font-family: "{ui_font}", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: 14px;
            color: {t.text};
            outline: none;
        }}

        QMainWindow, QDialog, QWidget#centralWidget {{
            background-color: {t.bg};
            border: none;
        }}

        /* Clean Flat Cards & Surfaces */
        QFrame#card, QFrame#surfaceCard {{
            background-color: {t.surface};
            border: 1px solid {t.border};
            border-radius: 12px;
            padding: 16px;
        }}

        QFrame#surfaceRaised {{
            background-color: {t.surface_raised};
            border: 1px solid {t.border};
            border-radius: 8px;
        }}

        /* Buttons */
        QPushButton {{
            background-color: {t.surface_raised};
            color: {t.text};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 7px 16px;
            font-weight: 500;
            min-height: 20px;
        }}

        QPushButton:hover {{
            background-color: {t.surface};
            border: 1px solid {t.accent};
        }}

        QPushButton:pressed {{
            background-color: {t.accent_soft};
        }}

        QPushButton:disabled {{
            opacity: 0.5;
            color: {t.text_muted};
            border-color: {t.border};
        }}

        QPushButton#primaryBtn {{
            background-color: {t.accent};
            color: {t.on_accent};
            border: none;
            font-weight: 600;
        }}

        QPushButton#primaryBtn:hover {{
            background-color: {t.accent_hover};
        }}

        QPushButton#dangerBtn {{
            background-color: {t.surface_raised};
            color: {t.listening};
            border: 1px solid {t.border};
        }}

        QPushButton#dangerBtn:hover {{
            background-color: rgba(229, 72, 77, 0.12);
            border-color: {t.listening};
        }}

        /* Inputs & Text Edits */
        QLineEdit, QTextEdit, QPlainTextEdit {{
            background-color: {t.surface};
            color: {t.text};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 8px 12px;
            selection-background-color: {t.accent};
            selection-color: {t.on_accent};
        }}

        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
            border: 2px solid {t.accent};
            background-color: {t.surface};
        }}

        /* Dropdowns */
        QComboBox {{
            background-color: {t.surface};
            color: {t.text};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 7px 12px;
            min-height: 20px;
        }}

        QComboBox:focus {{
            border: 2px solid {t.accent};
        }}

        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}

        QComboBox QAbstractItemView {{
            background-color: {t.surface};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 4px;
            selection-background-color: {t.accent_soft};
            selection-color: {t.accent};
        }}

        /* Checkboxes */
        QCheckBox {{
            spacing: 8px;
            color: {t.text};
        }}

        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 5px;
            border: 1px solid {t.border};
            background-color: {t.surface};
        }}

        QCheckBox::indicator:checked {{
            background-color: {t.accent};
            border-color: {t.accent};
        }}

        /* Tables & Lists */
        QTableWidget, QListView {{
            background-color: {t.surface};
            border: 1px solid {t.border};
            border-radius: 8px;
            gridline-color: {t.border};
            selection-background-color: {t.accent_soft};
            selection-color: {t.accent};
        }}

        QHeaderView::section {{
            background-color: {t.surface_raised};
            color: {t.text_muted};
            border: none;
            border-bottom: 1px solid {t.border};
            padding: 8px;
            font-size: 12px;
            font-weight: 600;
        }}

        /* Sidebar Navigation Item */
        QPushButton#navBtn {{
            background-color: transparent;
            color: {t.text_muted};
            border: none;
            border-radius: 8px;
            padding: 8px 14px;
            text-align: left;
            font-size: 14px;
            font-weight: 500;
        }}

        QPushButton#navBtn:hover {{
            background-color: {t.surface_raised};
            color: {t.text};
        }}

        QPushButton#navBtn:checked, QPushButton#navBtn[active="true"] {{
            background-color: {t.accent_soft};
            color: {t.accent};
            font-weight: 600;
        }}

        /* Scrollbars */
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 0px;
        }}

        QScrollBar::handle:vertical {{
            background: {t.border};
            border-radius: 4px;
            min-height: 24px;
        }}

        QScrollBar::handle:vertical:hover {{
            background: {t.text_muted};
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        """

    @classmethod
    def apply_theme(cls, app: QApplication, appearance_setting: str = "system") -> bool:
        """Apply active theme and palette across the entire application."""
        is_dark = cls.is_dark(appearance_setting)
        app.setPalette(cls.get_palette(is_dark))
        app.setStyleSheet(cls.get_stylesheet(is_dark))
        return is_dark
