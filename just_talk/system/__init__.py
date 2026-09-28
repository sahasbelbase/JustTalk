"""System integrations: clipboard, text insertion, and permission checks."""

from .clipboard import ClipboardManager
from .inserter import TextInserter
from .permissions import PermissionsManager

__all__ = ["ClipboardManager", "TextInserter", "PermissionsManager"]
