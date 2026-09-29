"""System integrations: clipboard, text insertion, and permission checks."""

from .caret_locator import CaretLocator
from .clipboard import ClipboardManager
from .inserter import TextInserter
from .permissions import PermissionsManager

__all__ = ["CaretLocator", "ClipboardManager", "TextInserter", "PermissionsManager"]

