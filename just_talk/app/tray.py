"""System tray icon and menu manager."""

from __future__ import annotations

import sys
from typing import Callable, Optional

from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from ..config import AppConfig
from ..stt.model_manager import TIERS


class SystemTrayManager:
    """Manages the menu bar / system tray icon and context menu."""

    def __init__(
        self,
        config: AppConfig,
        icon: QIcon,
        on_open_history: Callable[[], None],
        on_open_settings: Callable[[], None],
        on_toggle_gemini: Callable[[bool], None],
        on_change_tier: Callable[[str], None],
        on_quit: Callable[[], None],
        parent: Optional[QWidget] = None,
    ):
        self.config = config
        self.icon = icon
        self.on_open_history = on_open_history
        self.on_open_settings = on_open_settings
        self.on_toggle_gemini = on_toggle_gemini
        self.on_change_tier = on_change_tier
        self.on_quit = on_quit

        self.tray_icon = QSystemTrayIcon(parent)
        self.tray_icon.setIcon(self.icon)
        self.tray_icon.setToolTip("Just Talk — Voice Keyboard")
        self._build_menu()

    def _build_menu(self) -> None:
        menu = QMenu()

        # Status header
        status_action = QAction("Just Talk — Ready", menu)
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

        # History and Settings
        history_action = QAction("History...", menu)
        history_action.triggered.connect(self.on_open_history)
        menu.addAction(history_action)

        settings_action = QAction("Settings...", menu)
        settings_action.triggered.connect(self.on_open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        # Quit
        quit_action = QAction("Quit Just Talk", menu)
        quit_action.triggered.connect(self.on_quit)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)

    def _on_gemini_toggled(self, checked: bool) -> None:
        self.config.gemini_enabled = checked
        self.config.save()
        self.on_toggle_gemini(checked)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.on_open_history()

    def show(self) -> None:
        self.tray_icon.show()

    def set_tooltip(self, tip: str) -> None:
        self.tray_icon.setToolTip(f"Just Talk — {tip}")
