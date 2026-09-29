"""Application desktop UI, tray, overlay, and main controller."""

from .main import JustTalkApp, main
from .main_window import MainWindow
from .onboarding_window import OnboardingWindow
from .overlay import FloatingPillOverlay
from .single_instance import SingleInstanceManager
from .theme import ThemeManager
from .tray import SystemTrayManager

__all__ = [
    "JustTalkApp",
    "main",
    "MainWindow",
    "OnboardingWindow",
    "FloatingPillOverlay",
    "SystemTrayManager",
    "SingleInstanceManager",
    "ThemeManager",
]
