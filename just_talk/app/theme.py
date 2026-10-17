"""Single central theme module: design tokens, typography, QPalette, and QSS generator."""

from __future__ import annotations

import re
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
    border_subtle: str
    text: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_soft: str
    on_accent: str

    # Sidebar
    sidebar_bg: str
    sidebar_separator: str

    # Status colors
    listening: str
    action: str
    processing: str
    success: str
    warning: str
    clipboard: str


LIGHT_TOKENS = ColorTokens(
    bg="#F8F9FA",
    surface="#FFFFFF",
    surface_raised="#F0F2F5",
    border="rgba(0, 0, 0, 0.08)",
    border_subtle="rgba(0, 0, 0, 0.04)",
    text="#111318",
    text_secondary="#5F6368",
    text_muted="#80868B",
    accent="#3B82F6",
    accent_hover="#2563EB",
    accent_soft="rgba(59, 130, 246, 0.12)",
    on_accent="#FFFFFF",
    sidebar_bg="#F0F2F5",
    sidebar_separator="rgba(0, 0, 0, 0.06)",
    listening="#EF4444",
    action="#8B5CF6",
    processing="#3B82F6",
    success="#10B981",
    warning="#F59E0B",
    clipboard="#3B82F6",
)

DARK_TOKENS = ColorTokens(
    bg="#0F1115",
    surface="#16181D",
    surface_raised="#1E2229",
    border="#2A2E37",
    border_subtle="#21252E",
    text="#F9FAFB",
    text_secondary="#9CA3AF",
    text_muted="#6B7280",
    accent="#3B82F6",
    accent_hover="#60A5FA",
    accent_soft="rgba(59, 130, 246, 0.15)",
    on_accent="#FFFFFF",
    sidebar_bg="#0C0E13",
    sidebar_separator="#21252E",
    listening="#EF4444",
    action="#A855F7",
    processing="#38BDF8",
    success="#10B981",
    warning="#F59E0B",
    clipboard="#3B82F6",
)


class ThemeManager:
    """Central manager for fonts, color schemes, stylesheets, and OS theme sync."""

    LIGHT_TOKENS = LIGHT_TOKENS
    DARK_TOKENS = DARK_TOKENS

    _fonts_loaded = False
    _ui_font_family = "Lato"
    _display_font_family = "Lato"
    _mono_font_family = "JetBrains Mono"

    @classmethod
    def load_fonts(cls) -> None:
        """Load bundled Lato font family + JetBrains Mono, falling back to system fonts."""
        if cls._fonts_loaded:
            return

        fonts_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"

        # 1. Lato (UI + Display font) — load all weights
        lato_files = [
            fonts_dir / "Lato-Light.ttf",
            fonts_dir / "Lato-Regular.ttf",
            fonts_dir / "Lato-Bold.ttf",
            fonts_dir / "Lato-Black.ttf",
        ]
        lato_loaded = False
        for lato_path in lato_files:
            if lato_path.exists():
                font_id = QFontDatabase.addApplicationFont(str(lato_path))
                if font_id >= 0 and not lato_loaded:
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    if families:
                        cls._ui_font_family = families[0]
                        cls._display_font_family = families[0]
                        lato_loaded = True

        if not lato_loaded:
            cls._ui_font_family = "SF Pro" if sys.platform == "darwin" else "Segoe UI"
            cls._display_font_family = cls._ui_font_family

        # 2. Monospace Font
        mono_path = fonts_dir / "JetBrainsMono-Variable.ttf"
        if mono_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(mono_path))
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
        f = QFont(f_name)
        f.setPixelSize(size)  # pixels, like the stylesheet, so sizes match on macOS and Windows
        f.setWeight(weight)
        if size >= 28:
            f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98.0)  # Subtle negative tracking
        return f

    @classmethod
    def get_ui_font(cls, size: int = 14, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        return cls.font(size=size, weight=weight, family="ui")

    @classmethod
    def get_display_font(cls, size: int = 24, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        return cls.font(size=size, weight=weight, family="display")

    @classmethod
    def get_mono_font(cls, size: int = 12, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        return cls.font(size=size, weight=weight, family="mono")

    @staticmethod
    def qcolor(value: str) -> QColor:
        """
        Convert a design-token colour to QColor. QColor can't parse CSS ``rgba(r, g, b, a)``
        strings (it silently returns black), and several tokens use that form.
        """
        m = re.fullmatch(r"\s*rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)\s*", value)
        if m:
            r, g, b = (int(float(x)) for x in m.groups()[:3])
            a = float(m.group(4)) if m.group(4) is not None else 1.0
            return QColor(r, g, b, int(round(a * 255)))
        return QColor(value)

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

        return True  # Default to dark

    @classmethod
    def get_palette(cls, is_dark: bool) -> QPalette:
        """Generate a native QPalette matching the color tokens."""
        t = cls.get_tokens(is_dark)
        pal = QPalette()

        pal.setColor(QPalette.ColorRole.Window, cls.qcolor(t.bg))
        pal.setColor(QPalette.ColorRole.WindowText, cls.qcolor(t.text))
        pal.setColor(QPalette.ColorRole.Base, cls.qcolor(t.bg))
        pal.setColor(QPalette.ColorRole.AlternateBase, cls.qcolor(t.surface))
        pal.setColor(QPalette.ColorRole.ToolTipBase, cls.qcolor(t.surface_raised))
        pal.setColor(QPalette.ColorRole.ToolTipText, cls.qcolor(t.text))
        pal.setColor(QPalette.ColorRole.Text, cls.qcolor(t.text))
        pal.setColor(QPalette.ColorRole.Button, cls.qcolor(t.surface_raised))
        pal.setColor(QPalette.ColorRole.ButtonText, cls.qcolor(t.text))
        pal.setColor(QPalette.ColorRole.BrightText, cls.qcolor(t.on_accent))
        pal.setColor(QPalette.ColorRole.Highlight, cls.qcolor(t.accent))
        pal.setColor(QPalette.ColorRole.HighlightedText, cls.qcolor(t.on_accent))
        pal.setColor(QPalette.ColorRole.PlaceholderText, cls.qcolor(t.text_muted))
        return pal

    @classmethod
    def get_stylesheet(cls, is_dark: bool) -> str:
        """Generate central QSS stylesheet — Typeless-inspired dark minimal aesthetic."""
        t = cls.get_tokens(is_dark)

        # Pre-compute solid color equivalents
        if is_dark:
            surface_solid = "#16181D"
            surface_raised_solid = "#1E2229"
            border_solid = "#2A2E37"
            border_subtle_solid = "#21252E"
            text_secondary_solid = "#9CA3AF"
            text_muted_solid = "#6B7280"
        else:
            surface_solid = "#FFFFFF"
            surface_raised_solid = "#F0F2F5"
            border_solid = "rgba(0, 0, 0, 0.08)"
            border_subtle_solid = "rgba(0, 0, 0, 0.04)"
            text_secondary_solid = "#5F6368"
            text_muted_solid = "#80868B"

        check_icon = (Path(__file__).resolve().parent.parent / "assets" / "check.svg").as_posix()

        return f"""
        /* ===== Global Reset ===== */
        /* No font-family/font-size here: a "*" font rule overrides every setFont() call, which
           flattened all headings to body size. The base font is set with QApplication.setFont(). */
        * {{
            color: {t.text};
            outline: none;
        }}

        QMainWindow, QDialog {{
            background-color: {t.bg};
            border: none;
        }}

        QWidget#centralWidget {{
            background-color: {t.bg};
            border: none;
        }}

        /* ===== Sidebar ===== */
        QWidget#sidebar {{
            background-color: {t.sidebar_bg};
            border: none;
        }}

        QFrame#hairline {{
            background-color: {t.sidebar_separator};
            border: none;
            max-width: 1px;
        }}

        /* ===== Cards & Surfaces ===== */
        QFrame#card, QFrame#surfaceCard {{
            background-color: {surface_solid};
            border: 1px solid {border_solid};
            border-radius: 12px;
            padding: 16px;
        }}

        QFrame#surfaceRaised {{
            background-color: {surface_raised_solid};
            border: 1px solid {border_subtle_solid};
            border-radius: 8px;
        }}

        /* Bento Stat Cards */
        QFrame#bentoCard {{
            background-color: {surface_solid};
            border: 1px solid {border_solid};
            border-radius: 12px;
            padding: 14px 16px;
        }}

        QFrame#bentoCard:hover {{
            border-color: {"#3E4452" if is_dark else "#C4C8D0"};
        }}

        QLabel#statMetric {{
            color: {t.text};
            font-size: 24px;
            font-weight: 700;
        }}

        QLabel#statTrend {{
            color: {t.success};
            font-size: 11px;
            font-weight: 600;
        }}

        /* ===== Labels ===== */
        QLabel {{
            background: transparent;
            border: none;
            padding: 0px;
        }}

        QLabel#mutedLabel {{
            color: {text_muted_solid};
            background: transparent;
        }}

        QLabel#cardTitle {{
            color: {t.text};
        }}

        QLabel#cardStatus {{
            color: {text_secondary_solid};
        }}

        /* ===== Keycap Badges (Physical Mechanical Look) ===== */
        QLabel#keycap {{
            background-color: {surface_raised_solid};
            border: 1px solid {border_solid};
            border-bottom: 2px solid {"#323843" if is_dark else "#D1D5DB"};
            border-radius: 6px;
            padding: 3px 8px;
            color: {t.text};
            font-weight: 600;
            min-width: 18px;
            qproperty-alignment: AlignCenter;
        }}

        QLabel#heroKeycap {{
            background-color: {surface_raised_solid};
            border: 1px solid {border_solid};
            border-bottom: 3px solid {"#373D49" if is_dark else "#C8CCD0"};
            border-radius: 8px;
            padding: 6px 14px;
            color: {t.text};
            font-weight: 700;
            font-size: 15px;
            min-width: 28px;
            qproperty-alignment: AlignCenter;
        }}

        /* ===== Status Pills & Badges ===== */
        QLabel#statusPill {{
            background-color: {"rgba(16, 185, 129, 0.12)" if is_dark else "rgba(16, 185, 129, 0.10)"};
            color: {t.success};
            border: 1px solid {"rgba(16, 185, 129, 0.25)" if is_dark else "rgba(16, 185, 129, 0.20)"};
            border-radius: 10px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: 600;
        }}

        QLabel#accentPill {{
            background-color: {t.accent_soft};
            color: {t.accent};
            border: 1px solid {"rgba(59, 130, 246, 0.25)" if is_dark else "rgba(59, 130, 246, 0.20)"};
            border-radius: 10px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: 600;
        }}

        QLabel#secondaryPill {{
            background-color: {"rgba(255, 255, 255, 0.06)" if is_dark else "rgba(0, 0, 0, 0.05)"};
            color: {text_secondary_solid};
            border: 1px solid {border_solid};
            border-radius: 10px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: 500;
        }}

        QLabel#shortcutBadge {{
            color: {text_muted_solid};
            background: transparent;
        }}

        /* ===== Badge (app name pills) ===== */
        QLabel#badge {{
            background-color: {t.accent_soft};
            color: {t.accent};
            border-radius: 4px;
            padding: 2px 7px;
            font-size: 11px;
        }}

        /* ===== Buttons ===== */
        QPushButton {{
            background-color: {surface_raised_solid};
            color: {t.text};
            border: 1px solid {border_solid};
            border-radius: 7px;
            padding: 5px 14px;
            font-weight: 500;
            font-size: 13px;
            min-height: 22px;
        }}

        QPushButton:hover {{
            background-color: {"#303030" if is_dark else "#E0E0E2"};
            border-color: {"#3A3A3A" if is_dark else "rgba(0,0,0,0.10)"};
        }}

        QPushButton:pressed {{
            background-color: {"#383838" if is_dark else "#D5D5D8"};
        }}

        QPushButton:disabled {{
            opacity: 0.4;
            color: {text_muted_solid};
        }}

        /* Primary Button */
        QPushButton#primaryBtn {{
            background-color: {t.accent};
            color: {t.on_accent};
            border: none;
            border-radius: 7px;
            font-weight: 600;
            padding: 6px 18px;
        }}

        QPushButton#primaryBtn:hover {{
            background-color: {t.accent_hover};
        }}

        QPushButton#primaryBtn:pressed {{
            background-color: {"#5A7CE0" if is_dark else "#0055BB"};
        }}

        /* Secondary Button */
        QPushButton#secondaryBtn {{
            background-color: {surface_raised_solid};
            color: {t.text};
            border: 1px solid {border_solid};
            border-radius: 7px;
            font-weight: 500;
            padding: 5px 12px;
        }}

        QPushButton#secondaryBtn:hover {{
            background-color: {"#303030" if is_dark else "#E0E0E2"};
        }}

        /* Danger Button */
        QPushButton#dangerBtn {{
            background-color: transparent;
            color: {t.listening};
            border: 1px solid {border_solid};
        }}

        QPushButton#dangerBtn:hover {{
            background-color: {"rgba(255,69,58,0.08)" if is_dark else "rgba(255,59,48,0.08)"};
            border-color: {t.listening};
        }}

        /* Flat / Ghost Button */
        QFrame#historyCard {{
            background-color: {surface_solid};
            border: 1px solid {border_solid};
            border-radius: 12px;
        }}

        QFrame#diffRawPanel {{
            background-color: {"#0D0E12" if is_dark else "#F9FAFB"};
            border: 1px solid {"rgba(239, 68, 68, 0.3)" if is_dark else "rgba(239, 68, 68, 0.2)"};
            border-radius: 8px;
        }}

        QFrame#diffFormattedPanel {{
            background-color: {surface_raised_solid};
            border: 1px solid {"rgba(59, 130, 246, 0.35)" if is_dark else "rgba(59, 130, 246, 0.25)"};
            border-radius: 8px;
        }}

        QPushButton#deleteBtn {{
            background: transparent;
            border: none;
            border-radius: 6px;
            padding: 4px;
        }}

        QPushButton#deleteBtn:hover {{
            background-color: rgba(255, 69, 58, 0.16);
        }}

        QPushButton#flatBtn {{
            background-color: transparent;
            color: {text_secondary_solid};
            border: none;
            font-weight: 500;
            padding: 5px 8px;
        }}

        QPushButton#flatBtn:hover {{
            color: {t.text};
        }}

        /* Chip / Filter Toggle Button */
        QPushButton#chipBtn {{
            background-color: transparent;
            color: {text_secondary_solid};
            border: none;
            border-radius: 12px;
            padding: 4px 12px;
            font-size: 12px;
            font-weight: 500;
            min-height: 18px;
        }}

        QPushButton#chipBtn:hover {{
            color: {t.text};
            background-color: {"rgba(255,255,255,0.05)" if is_dark else "rgba(0,0,0,0.04)"};
        }}

        QPushButton#chipBtn:checked {{
            background-color: {surface_raised_solid};
            color: {t.text};
            border: none;
        }}

        /* ===== Sidebar Navigation Buttons ===== */
        QPushButton#navBtn {{
            background-color: transparent;
            color: {text_secondary_solid};
            border: none;
            border-radius: 7px;
            padding: 8px 12px;
            text-align: left;
            font-size: 13px;
            font-weight: 500;
        }}

        QPushButton#navBtn:hover {{
            background-color: {"rgba(255,255,255,0.05)" if is_dark else "rgba(0,0,0,0.04)"};
            color: {t.text};
        }}

        QPushButton#navBtn:checked, QPushButton#navBtn[active="true"] {{
            background-color: {surface_raised_solid};
            color: {t.accent};
            font-weight: 600;
            border: 1px solid {border_solid};
        }}

        /* ===== Settings Sub-Navigation Rail Buttons ===== */
        QPushButton#subnavBtn {{
            background-color: transparent;
            color: {text_secondary_solid};
            border: none;
            border-radius: 7px;
            padding: 7px 10px;
            text-align: left;
            font-size: 12px;
            font-weight: 500;
        }}

        QPushButton#subnavBtn:hover {{
            background-color: {"rgba(255,255,255,0.04)" if is_dark else "rgba(0,0,0,0.04)"};
            color: {t.text};
        }}

        QPushButton#subnavBtn:checked {{
            background-color: {surface_raised_solid};
            color: {t.accent};
            font-weight: 600;
            border: 1px solid {border_subtle_solid};
        }}

        /* ===== Inputs & Text Edits ===== */
        QLineEdit, QTextEdit, QPlainTextEdit {{
            background-color: {"#1A1A1A" if is_dark else "#F5F5F7"};
            color: {t.text};
            border: 1px solid {border_solid};
            border-radius: 7px;
            padding: 6px 10px;
            font-size: 13px;
            selection-background-color: {t.accent};
            selection-color: {t.on_accent};
        }}

        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
            border: 1px solid {"#444" if is_dark else t.accent};
        }}

        QLineEdit:disabled, QTextEdit:disabled {{
            opacity: 0.4;
            color: {text_muted_solid};
        }}

        /* ===== Dropdowns / ComboBox ===== */
        QComboBox {{
            background-color: {surface_raised_solid};
            color: {t.text};
            border: 1px solid {border_solid};
            border-radius: 7px;
            padding: 5px 10px;
            font-size: 13px;
            min-height: 22px;
        }}

        QComboBox:focus {{
            border: 1px solid {"#444" if is_dark else t.accent};
        }}

        QComboBox::drop-down {{
            border: none;
            width: 22px;
            padding-right: 4px;
        }}

        QComboBox QAbstractItemView {{
            background-color: {"#252525" if is_dark else "#FFFFFF"};
            border: 1px solid {border_solid};
            border-radius: 8px;
            padding: 4px;
            selection-background-color: {t.accent_soft};
            selection-color: {t.text};
            outline: none;
        }}

        QComboBox QAbstractItemView::item {{
            padding: 5px 10px;
            border-radius: 5px;
            min-height: 22px;
        }}

        QComboBox QAbstractItemView::item:selected {{
            background-color: {t.accent_soft};
        }}

        /* ===== Checkboxes ===== */
        QCheckBox {{
            spacing: 8px;
            color: {t.text};
            font-size: 13px;
        }}

        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 1.5px solid {"#5A5A5A" if is_dark else "#AAA"};
            background-color: transparent;
        }}

        QCheckBox::indicator:hover {{
            border-color: {t.accent};
        }}

        QCheckBox::indicator:checked {{
            background-color: {t.accent};
            border-color: {t.accent};
            image: url("{check_icon}");
        }}

        /* ===== Radio Buttons ===== */
        QRadioButton {{
            spacing: 8px;
            color: {t.text};
        }}

        QRadioButton::indicator {{
            width: 13px;
            height: 13px;
            border-radius: 8px;
            border: 1.5px solid {"#5A5A5A" if is_dark else "#AAA"};
            background-color: transparent;
        }}

        QRadioButton::indicator:hover {{
            border-color: {t.accent};
        }}

        QRadioButton::indicator:checked {{
            width: 8px;
            height: 8px;
            border: 4px solid {t.accent};
            background-color: {t.on_accent};
        }}

        /* ===== Spin Boxes ===== */
        QAbstractSpinBox {{
            background-color: {surface_raised_solid};
            color: {t.text};
            border: 1px solid {border_solid};
            border-radius: 7px;
            padding: 5px 8px;
            min-height: 22px;
            min-width: 64px;
            font-size: 13px;
        }}

        QAbstractSpinBox:focus {{
            border: 1px solid {"#444" if is_dark else t.accent};
        }}

        /* ===== Settings Page ===== */
        QFrame#settingsSection {{
            background-color: {surface_solid};
            border: 1px solid {border_solid};
            border-radius: 12px;
        }}

        QFrame#sectionHeader {{
            border: none;
            background: transparent;
            border-radius: 8px;
        }}

        QFrame#sectionHeader:hover {{
            background-color: {surface_raised_solid};
        }}

        QLabel#sectionChevron {{
            color: {text_secondary_solid};
            font-size: 20px;
            padding-right: 4px;
        }}

        QFrame#sectionDivider {{
            background-color: {border_solid};
            border: none;
            max-height: 1px;
            min-height: 1px;
        }}

        QLabel#sectionBadge {{
            background-color: {t.accent_soft};
            color: {t.accent};
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
            padding: 1px 6px;
        }}

        QFrame#searchField {{
            background-color: {"#1A1A1A" if is_dark else "#FFFFFF"};
            border: 1px solid {border_solid if is_dark else "rgba(0, 0, 0, 0.14)"};
            border-radius: 9px;
        }}

        QFrame#searchField QLineEdit {{
            border: none;
            background: transparent;
            padding: 6px 0px;
            font-size: 13px;
        }}

        QPushButton#searchClear {{
            border: none;
            border-radius: 10px;
            background-color: {surface_raised_solid};
            color: {text_secondary_solid};
            font-size: 10px;
            font-weight: bold;
        }}

        QFrame#infoCard {{
            background-color: {surface_raised_solid};
            border: none;
            border-radius: 8px;
        }}

        QLabel#helpText {{
            color: {text_secondary_solid};
            font-size: 12px;
        }}

        QLabel#savedIndicator {{
            color: {t.success};
            font-size: 12px;
        }}

        /* ===== Tables & Lists ===== */
        QTableWidget, QListView {{
            background-color: {surface_solid};
            border: 1px solid {border_solid};
            border-radius: 10px;
            gridline-color: transparent;
            selection-background-color: {t.accent_soft};
            selection-color: {t.text};
            font-size: 13px;
            alternate-background-color: {"#1C1C1C" if is_dark else "#FAFAFA"};
        }}

        QTableWidget::item {{
            padding: 8px 10px;
            border: none;
            border-bottom: 1px solid {border_subtle_solid};
        }}

        QTableWidget::item:selected {{
            background-color: {t.accent_soft};
        }}

        QHeaderView::section {{
            background-color: {surface_solid};
            color: {text_muted_solid};
            border: none;
            border-bottom: 1px solid {border_solid};
            padding: 6px 10px;
            font-size: 11px;
            font-weight: 600;
        }}

        /* ===== Splitter Handle ===== */
        QSplitter::handle {{
            background-color: {t.sidebar_separator};
            width: 1px;
        }}

        /* ===== Scroll Areas ===== */
        QScrollArea {{
            background-color: transparent;
            border: none;
        }}

        QScrollArea > QWidget > QWidget {{
            background-color: transparent;
        }}

        /* ===== Scrollbars ===== */
        QScrollBar:vertical {{
            background: transparent;
            width: 5px;
            margin: 4px 1px 4px 0px;
            border: none;
        }}

        QScrollBar::handle:vertical {{
            background: {"rgba(255,255,255,0.10)" if is_dark else "rgba(0,0,0,0.12)"};
            border-radius: 2px;
            min-height: 28px;
        }}

        QScrollBar::handle:vertical:hover {{
            background: {"rgba(255,255,255,0.22)" if is_dark else "rgba(0,0,0,0.22)"};
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}

        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent;
        }}

        QScrollBar:horizontal {{
            background: transparent;
            height: 5px;
            margin: 0px 4px 1px 4px;
            border: none;
        }}

        QScrollBar::handle:horizontal {{
            background: {"rgba(255,255,255,0.10)" if is_dark else "rgba(0,0,0,0.12)"};
            border-radius: 2px;
            min-width: 28px;
        }}

        QScrollBar::handle:horizontal:hover {{
            background: {"rgba(255,255,255,0.22)" if is_dark else "rgba(0,0,0,0.22)"};
        }}

        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}

        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: transparent;
        }}

        /* ===== QProgressBar ===== */
        QProgressBar {{
            background-color: {surface_solid};
            border: none;
            border-radius: 3px;
            height: 5px;
            text-align: center;
            font-size: 0px;
        }}

        QProgressBar::chunk {{
            background-color: {t.accent};
            border-radius: 3px;
        }}

        /* ===== Form Layout Labels ===== */
        QFormLayout QLabel {{
            color: {text_secondary_solid};
            font-size: 13px;
        }}

        /* ===== Tooltips ===== */
        QToolTip {{
            background-color: {"#2A2A2A" if is_dark else "#F5F5F7"};
            color: {t.text};
            border: 1px solid {border_solid};
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 12px;
        }}

        /* ===== Message Box ===== */
        QMessageBox {{
            background-color: {t.bg};
        }}

        QMessageBox QLabel {{
            color: {t.text};
            font-size: 13px;
        }}

        QMessageBox QPushButton {{
            min-width: 72px;
        }}

        /* ===== Type roles (onboarding and anywhere a clear hierarchy is needed) ===== */
        QLabel#h1 {{
            font-size: 30px;
            font-weight: 700;
            color: {t.text};
        }}

        QLabel#lead {{
            font-size: 15px;
            color: {text_secondary_solid};
        }}

        QLabel#eyebrow {{
            font-size: 11px;
            font-weight: 700;
            color: {text_muted_solid};
        }}

        QLabel#caption {{
            font-size: 12px;
            color: {text_muted_solid};
        }}

        QLabel#rowTitle {{
            font-size: 14px;
            font-weight: 600;
            color: {t.text};
        }}

        QLabel#statusOk {{
            font-size: 12px;
            font-weight: 600;
            color: {t.success};
        }}

        QLabel#statusWarn {{
            font-size: 12px;
            font-weight: 600;
            color: {t.warning};
        }}

        QLabel#bigNumber {{
            font-size: 34px;
            font-weight: 700;
            color: {t.text};
        }}

        /* ===== Onboarding controls ===== */
        QFrame#hairRow {{
            background: transparent;
            border: none;
            border-bottom: 1px solid {border_solid};
        }}

        QFrame#choiceCard {{
            background-color: {surface_solid};
            border: 1px solid {border_solid};
            border-radius: 12px;
        }}

        QFrame#choiceCard:hover {{
            border-color: {"#3A3A3A" if is_dark else "rgba(0, 0, 0, 0.16)"};
        }}

        QFrame#choiceCard[checked="true"] {{
            background-color: {t.accent_soft};
            border: 1px solid {t.accent};
        }}

        QPushButton#chip {{
            background-color: {surface_solid};
            color: {t.text};
            border: 1px solid {border_solid};
            border-radius: 15px;
            padding: 6px 14px;
            font-size: 13px;
            font-weight: 500;
            min-height: 18px;
        }}

        QPushButton#chip:hover {{
            border-color: {"#3A3A3A" if is_dark else "rgba(0, 0, 0, 0.16)"};
        }}

        QPushButton#chip:checked {{
            background-color: {t.accent_soft};
            border-color: {t.accent};
            color: {t.accent};
        }}

        QPushButton#linkBtn {{
            background: transparent;
            border: none;
            color: {text_secondary_solid};
            padding: 4px 2px;
            font-weight: 500;
        }}

        QPushButton#linkBtn:hover {{
            color: {t.text};
        }}

        QPushButton#primaryBtn[size="large"], QPushButton#secondaryBtn[size="large"] {{
            padding: 9px 22px;
            border-radius: 9px;
            font-size: 14px;
        }}
        """

    @classmethod
    def apply_theme(cls, app: QApplication, appearance_setting: str = "system") -> bool:
        """Apply active theme and palette across the entire application."""
        is_dark = cls.is_dark(appearance_setting)
        app.setFont(cls.font(13))
        app.setPalette(cls.get_palette(is_dark))
        app.setStyleSheet(cls.get_stylesheet(is_dark))
        return is_dark
