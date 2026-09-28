"""Application desktop UI, tray, overlay, and main controller."""

from .history_window import HistoryWindow
from .main import JustTalkApp, main
from .overlay import FloatingPillOverlay
from .settings_window import SettingsWindow
from .tray import SystemTrayManager

__all__ = [
    "JustTalkApp",
    "main",
    "FloatingPillOverlay",
    "SystemTrayManager",
    "SettingsWindow",
    "HistoryWindow",
]
