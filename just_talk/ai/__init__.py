"""AI processing, formatting, and action routing module."""

from .actions import ActionIntent, ActionRouter
from .gemini import CircuitBreaker, ConnectionTestResult, GeminiFormatter
from .nvidia_fallback import NvidiaFallbackFormatter
from .prompts import (
    SYSTEM_PROMPT_CONCISE,
    SYSTEM_PROMPT_FORMAL,
    SYSTEM_PROMPT_SUBTLE,
    SYSTEM_PROMPT_TRANSLATE,
    build_prompt,
)
from .providers import (
    AIProvider,
    MultiProviderFormatter,
    PROVIDER_REGISTRY,
    get_provider,
    get_provider_list,
)

__all__ = [
    "AIProvider",
    "CircuitBreaker",
    "ConnectionTestResult",
    "GeminiFormatter",
    "MultiProviderFormatter",
    "NvidiaFallbackFormatter",
    "PROVIDER_REGISTRY",
    "get_provider",
    "get_provider_list",
    "ActionRouter",
    "ActionIntent",
    "SYSTEM_PROMPT_SUBTLE",
    "SYSTEM_PROMPT_FORMAL",
    "SYSTEM_PROMPT_CONCISE",
    "SYSTEM_PROMPT_TRANSLATE",
    "build_prompt",
]
