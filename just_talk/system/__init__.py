"""System integrations: clipboard, text insertion, and permission checks."""

from .audio_ducker import SystemAudioDucker
from .caret_locator import CaretLocator
from .clipboard import ClipboardManager
from .inserter import TextInserter
from .permissions import PermissionsManager

__all__ = ["SystemAudioDucker", "CaretLocator", "ClipboardManager", "TextInserter", "PermissionsManager"]

