"""Action router and intent detector for secondary shortcut (Fn+Shift) mode."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

from .prompts import (
    SYSTEM_PROMPT_CONCISE,
    SYSTEM_PROMPT_FORMAL,
    SYSTEM_PROMPT_SUBTLE,
    SYSTEM_PROMPT_TRANSLATE,
)


@dataclass
class ActionIntent:
    """Parsed user intent from speech."""

    action_type: str  # "format", "translate", "rewrite", "summarize"
    target_payload: str
    target_language: Optional[str] = None
    system_instruction: str = SYSTEM_PROMPT_SUBTLE


class ActionRouter:
    """Routes voice input to specialized Gemini actions based on speech commands."""

    TRANSLATE_PATTERNS = [
        re.compile(r"^translate\s+(?:this\s+)?(?:in|into|to)\s+([a-zA-Z]+)[:,\s]+(.*)$", re.IGNORECASE),
        re.compile(r"^how\s+do\s+you\s+say\s+(.*)\s+in\s+([a-zA-Z]+)$", re.IGNORECASE),
    ]

    FORMAL_PATTERNS = [
        re.compile(r"^(?:rewrite\s+(?:this\s+)?(?:professionally|formally)|make\s+this\s+formal)[:,\s]+(.*)$", re.IGNORECASE),
    ]

    CONCISE_PATTERNS = [
        re.compile(r"^(?:summarize\s+(?:this)?|make\s+this\s+concise|shorten\s+this)[:,\s]+(.*)$", re.IGNORECASE),
    ]

    @classmethod
    def parse_intent(cls, raw_text: str, is_action_mode: bool = False) -> ActionIntent:
        """
        Parse raw speech into a structured ActionIntent.
        If is_action_mode is True, checks for command patterns first.
        """
        text = raw_text.strip()
        if not text:
            return ActionIntent(action_type="format", target_payload="")

        # 1. Check for Translation
        for pattern in cls.TRANSLATE_PATTERNS:
            match = pattern.match(text)
            if match:
                groups = match.groups()
                if len(groups) == 2:
                    if pattern.pattern.startswith("^how"):
                        payload, target_lang = groups[0].strip(), groups[1].strip()
                    else:
                        target_lang, payload = groups[0].strip(), groups[1].strip()

                    instruction = f"{SYSTEM_PROMPT_TRANSLATE}\nTarget language: {target_lang.capitalize()}."
                    return ActionIntent(
                        action_type="translate",
                        target_payload=payload if payload else text,
                        target_language=target_lang,
                        system_instruction=instruction,
                    )

        # 2. Check for Formal Rewrite
        for pattern in cls.FORMAL_PATTERNS:
            match = pattern.match(text)
            if match:
                payload = match.group(1).strip()
                return ActionIntent(
                    action_type="rewrite",
                    target_payload=payload if payload else text,
                    system_instruction=SYSTEM_PROMPT_FORMAL,
                )

        # 3. Check for Concise Summary
        for pattern in cls.CONCISE_PATTERNS:
            match = pattern.match(text)
            if match:
                payload = match.group(1).strip()
                return ActionIntent(
                    action_type="summarize",
                    target_payload=payload if payload else text,
                    system_instruction=SYSTEM_PROMPT_CONCISE,
                )

        # Default standard subtle cleanup
        return ActionIntent(
            action_type="format",
            target_payload=text,
            system_instruction=SYSTEM_PROMPT_SUBTLE,
        )
