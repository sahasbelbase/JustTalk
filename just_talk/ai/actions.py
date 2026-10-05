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
    build_prompt,
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
        re.compile(r"^translate(?:\s+this)?[:,\s]+(.*)$", re.IGNORECASE),
    ]

    FORMAL_PATTERNS = [
        re.compile(r"^(?:rewrite\s+(?:this\s+)?(?:professionally|formally)|make\s+this\s+formal)[:,\s]+(.*)$", re.IGNORECASE),
    ]

    CONCISE_PATTERNS = [
        re.compile(r"^(?:summarize\s+(?:this)?|make\s+this\s+concise|shorten\s+this)[:,\s]+(.*)$", re.IGNORECASE),
    ]

    @classmethod
    def parse_intent(
        cls,
        raw_text: str,
        is_action_mode: bool = False,
        context: str = "text",
        conventions: dict = None,
        nepali_mode: Optional[str] = None,
        romanized_style: str = "cha",
    ) -> ActionIntent:
        """
        Parse raw speech into a structured ActionIntent.
        If is_action_mode is True, checks for command patterns first.
        If nepali_mode is specified ('romanized', 'devanagari', 'english'), applies specialized prompt.
        """
        text = raw_text.strip()
        if not text:
            return ActionIntent(action_type="format", target_payload="")

        # 1. Check for Translation
        for pattern in cls.TRANSLATE_PATTERNS:
            match = pattern.match(text)
            if match:
                groups = match.groups()
                if len(groups) == 1:
                    target_lang = "English"
                    payload = groups[0].strip()
                elif len(groups) == 2:
                    if pattern.pattern.startswith("^how"):
                        payload, target_lang = groups[0].strip(), groups[1].strip()
                    else:
                        target_lang, payload = groups[0].strip(), groups[1].strip()
                else:
                    target_lang = "English"
                    payload = text

                instruction = build_prompt("translate", target_language=target_lang.capitalize(), context=context, conventions=conventions)
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
                    system_instruction=build_prompt("formal", context=context, conventions=conventions),
                )

        # 3. Check for Concise Summary
        for pattern in cls.CONCISE_PATTERNS:
            match = pattern.match(text)
            if match:
                payload = match.group(1).strip()
                return ActionIntent(
                    action_type="summarize",
                    target_payload=payload if payload else text,
                    system_instruction=build_prompt("concise", context=context, conventions=conventions),
                )

        # 4. Nepali-specific output modes (Nepglish Romanized, Devanagari, or English)
        if nepali_mode == "romanized":
            return ActionIntent(
                action_type="format",
                target_payload=text,
                system_instruction=build_prompt(
                    "nepglish",
                    romanized_style=romanized_style,
                    context=context,
                    conventions=conventions,
                ),
            )
        elif nepali_mode == "devanagari":
            return ActionIntent(
                action_type="format",
                target_payload=text,
                system_instruction=build_prompt(
                    "devanagari",
                    context=context,
                    conventions=conventions,
                ),
            )
        elif nepali_mode == "english":
            return ActionIntent(
                action_type="translate",
                target_payload=text,
                target_language="English",
                system_instruction=build_prompt(
                    "translate",
                    target_language="English",
                    context=context,
                    conventions=conventions,
                ),
            )

        # Default standard subtle cleanup
        return ActionIntent(
            action_type="format",
            target_payload=text,
            system_instruction=build_prompt("subtle", context=context, conventions=conventions),
        )

