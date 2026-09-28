"""Google AI Studio Gemini API client for subtle voice formatting."""

from __future__ import annotations

import sys
import time
from typing import Optional, Tuple

import httpx

from .prompts import (
    SYSTEM_PROMPT_CONCISE,
    SYSTEM_PROMPT_FORMAL,
    SYSTEM_PROMPT_SUBTLE,
    SYSTEM_PROMPT_TRANSLATE,
)


class GeminiFormatter:
    """Client for formatting speech via Google AI Studio Gemini API."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-3.8-flash",
        timeout: float = 2.5,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout

    def set_api_key(self, api_key: Optional[str]) -> None:
        self.api_key = api_key

    def set_model(self, model_name: str) -> None:
        self.model_name = model_name

    def get_prompt_for_style(self, style: str) -> str:
        if style == "formal":
            return SYSTEM_PROMPT_FORMAL
        elif style == "concise":
            return SYSTEM_PROMPT_CONCISE
        return SYSTEM_PROMPT_SUBTLE

    def test_connection(self, api_key: Optional[str] = None) -> Tuple[bool, str]:
        """Verify API key validity against Google AI Studio API."""
        key = api_key or self.api_key
        if not key:
            return False, "API key is not configured."

        url = f"{self.BASE_URL}/models/{self.model_name}:generateContent"
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": "Reply with one word: OK"}]}
            ],
            "generationConfig": {"maxOutputTokens": 5, "temperature": 0.0},
        }

        try:
            with httpx.Client(timeout=4.0) as client:
                resp = client.post(
                    url,
                    params={"key": key},
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

                if resp.status_code == 200:
                    return True, "Connected successfully to Google AI Studio!"
                elif resp.status_code == 400:
                    return False, f"Invalid API Key or Model (HTTP 400): {resp.text}"
                elif resp.status_code == 429:
                    return False, "Rate limit reached (HTTP 429). Please try again shortly."
                return False, f"API Error (HTTP {resp.status_code}): {resp.text}"
        except httpx.ConnectError:
            return False, "Network connection error. Check your internet connection."
        except httpx.TimeoutException:
            return False, "Connection timed out connecting to Google AI Studio."
        except Exception as e:
            return False, f"Unexpected error: {e}"

    def format_text(
        self,
        raw_text: str,
        style: str = "subtle",
        custom_system_instruction: Optional[str] = None,
    ) -> Tuple[str, bool, str]:
        """
        Format raw speech using Gemini.
        Returns:
            Tuple[processed_text, is_gemini_success, error_message]
            If Gemini fails, returns (raw_text, False, error_message)
            so the user's spoken words are never lost!
        """
        if not raw_text or not raw_text.strip():
            return "", True, ""

        if not self.api_key:
            return raw_text, False, "API key missing. Inserted raw transcript."

        system_instruction = custom_system_instruction or self.get_prompt_for_style(style)

        url = f"{self.BASE_URL}/models/{self.model_name}:generateContent"
        payload = {
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": raw_text}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,  # Low temperature for deterministic cleaning
                "maxOutputTokens": 1024,
            },
        }

        start_time = time.time()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    url,
                    params={"key": self.api_key},
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            out_text = parts[0].get("text", "").strip()
                            if out_text:
                                elapsed = int((time.time() - start_time) * 1000)
                                return out_text, True, f"Formatted in {elapsed}ms"

                    return raw_text, False, "Empty response from Gemini."
                else:
                    return raw_text, False, f"Gemini HTTP {resp.status_code}: {resp.text}"

        except httpx.TimeoutException:
            # Latency budget exceeded: return raw transcription instantly
            print(f"[Gemini] Timeout ({self.timeout}s). Falling back to raw text.", file=sys.stderr)
            return raw_text, False, "Timeout. Fell back to raw transcription."
        except Exception as e:
            print(f"[Gemini] Formatting error: {e}. Falling back to raw text.", file=sys.stderr)
            return raw_text, False, f"Error: {e}"
