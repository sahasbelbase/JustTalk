"""Global keyboard shortcuts and push-to-talk triggers module."""

from .fallback_hook import PynputHotkeyMonitor
from .mac_hook import MacFnKeyMonitor
from .manager import ShortcutManager

__all__ = ["ShortcutManager", "MacFnKeyMonitor", "PynputHotkeyMonitor"]
