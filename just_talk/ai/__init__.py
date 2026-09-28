"""AI processing, formatting, and action routing module."""

from .actions import ActionIntent, ActionRouter
from .gemini import GeminiFormatter
from .prompts import (
    SYSTEM_PROMPT_CONCISE,
    SYSTEM_PROMPT_FORMAL,
    SYSTEM_PROMPT_SUBTLE,
    SYSTEM_PROMPT_TRANSLATE,
)

__all__ = [
    "GeminiFormatter",
    "ActionRouter",
    "ActionIntent",
    "SYSTEM_PROMPT_SUBTLE",
    "SYSTEM_PROMPT_FORMAL",
    "SYSTEM_PROMPT_CONCISE",
    "SYSTEM_PROMPT_TRANSLATE",
]
