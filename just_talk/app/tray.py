"""System tray icon and menu manager."""

from __future__ import annotations

import sys
from typing import Callable, Optional

from PySide6.QtGui import QAction, QActionGroup, QFont, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from ..ai.gemini import GeminiFormatter
from ..config import AppConfig
from ..stt.model_manager import TIERS


class SystemTrayManager:
    """Manages the menu bar / system tray icon and context menu."""

    def __init__(
        self,
        config: AppConfig,
        icon: QIcon,
        on_open_main: Callable[[Optional[str]], None],
        on_toggle_gemini: Callable[[bool], None],
        on_change_tier: Callable[[str], None],
        on_quit: Callable[[], None],
        gemini: Optional[GeminiFormatter] = None,
        parent: Optional[QWidget] = None,
    ):
        self.config = config
        self.icon = icon
        self.on_open_main = on_open_main
        self.on_toggle_gemini = on_toggle_gemini
        self.on_change_tier = on_change_tier
        self.on_quit = on_quit
        self.gemini = gemini

        self.tray_icon = QSystemTrayIcon(parent)
        self.tray_icon.setIcon(self.icon)
        self.tray_icon.setToolTip("Just Talk — Voice Keyboard")
        self._build_menu()

    def _build_menu(self) -> None:
        menu = QMenu()

        # Primary Action: Open Full App Window
        open_action = QAction("Open Just Talk", menu)
        font = open_action.font()
        font.setBold(True)
        open_action.setFont(font)
        open_action.triggered.connect(lambda: self.on_open_main("home"))
        menu.addAction(open_action)

        # Circuit Breaker warning badge item if paused
        if self.gemini and self.gemini.circuit_breaker.is_paused:
            rem = self.gemini.circuit_breaker.remaining_cooldown_sec
            cb_action = QAction(f"⚠️ AI formatting paused ({rem}s). Click to fix", menu)
            cb_action.triggered.connect(lambda: self.on_open_main("settings"))
            menu.addAction(cb_action)

        menu.addSeparator()

        # Status header
        status_action = QAction("Status: Ready to transcribe", menu)
        status_action.setEnabled(False)
        menu.addAction(status_action)
        menu.addSeparator()

        # Quick Toggle: Gemini AI Formatting
        self.gemini_action = QAction("Enable Gemini AI Formatting", menu)
        self.gemini_action.setCheckable(True)
        self.gemini_action.setChecked(self.config.gemini_enabled)
        self.gemini_action.toggled.connect(self._on_gemini_toggled)
        menu.addAction(self.gemini_action)

        # Quick Model Tier submenu
        tier_menu = menu.addMenu("Speech Model Quality")
        tier_group = QActionGroup(tier_menu)
        tier_group.setExclusive(True)

        for tier_id, info in TIERS.items():
            act = QAction(f"{info.display_name} ({info.disk_size_mb} MB)", tier_menu)
            act.setCheckable(True)
            act.setData(tier_id)
            if self.config.model_tier == tier_id:
                act.setChecked(True)
            act.triggered.connect(lambda checked, t=tier_id: self.on_change_tier(t))
            tier_group.addAction(act)
            tier_menu.addAction(act)

        menu.addSeparator()

        # History and Settings navigation
        history_action = QAction("History...", menu)
        history_action.triggered.connect(lambda: self.on_open_main("history"))
        menu.addAction(history_action)

        settings_action = QAction("Settings...", menu)
        settings_action.triggered.connect(lambda: self.on_open_main("settings"))
        menu.addAction(settings_action)

        menu.addSeparator()

        # Quit
        quit_action = QAction("Quit Just Talk", menu)
        quit_action.triggered.connect(self.on_quit)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)

    def refresh_menu(self) -> None:
        """Re-render menu to update dynamic circuit breaker state."""
        self._build_menu()

    def _on_gemini_toggled(self, checked: bool) -> None:
        self.config.gemini_enabled = checked
        self.config.save()
        self.on_toggle_gemini(checked)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self.on_open_main("home")

    def show(self) -> None:
        self.tray_icon.show()

    def set_tooltip(self, tip: str) -> None:
        self.tray_icon.setToolTip(f"Just Talk — {tip}")
