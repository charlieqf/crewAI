"""
LLM Router - Route requests to different LLM providers.

Supports OpenAI, Gemini, and xAI Grok with unified interface.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import requests


logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from LLM."""

    content: str
    model: str
    provider: str
    usage: dict | None = None


class LLMError(Exception):
    """Raised when LLM call fails."""

    pass


class LLMRouter:
    """Route requests to different LLM providers."""

    # Provider configurations
    PROVIDERS = {
        "openai": {
            "base_url": "https://api.openai.com/v1/chat/completions",
            "default_model": "gpt-4o",
            "env_key": "OPENAI_API_KEY",
        },
        "gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            "default_model": "gemini-1.5-pro",
            "env_key": "GEMINI_API_KEY",
        },
        "xai": {
            "base_url": "https://api.x.ai/v1/chat/completions",
            "default_model": "grok-beta",
            "env_key": "XAI_API_KEY",
        },
    }

    def __init__(
        self,
        openai_key: str | None = None,
        gemini_key: str | None = None,
        xai_key: str | None = None,
    ):
        """Initialize with API keys (from params or environment)."""
        self.keys = {
            "openai": openai_key or os.getenv("OPENAI_API_KEY"),
            "gemini": gemini_key or os.getenv("GEMINI_API_KEY"),
            "xai": xai_key or os.getenv("XAI_API_KEY"),
        }

    def chat(
        self,
        provider: str,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send chat completion request to specified provider.

        Args:
            provider: One of 'openai', 'gemini', 'xai'
            messages: List of message dicts with 'role' and 'content'
            model: Model name (uses default if not specified)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            LLMResponse with content and metadata
        """
        if provider not in self.PROVIDERS:
            raise LLMError(f"Unknown provider: {provider}")

        api_key = self.keys.get(provider)
        if not api_key:
            raise LLMError(f"API key not configured for {provider}")

        config = self.PROVIDERS[provider]
        model = model or config["default_model"]

        if provider == "gemini":
            return self._call_gemini(api_key, messages, model, max_tokens, temperature)
        else:
            # OpenAI-compatible API (OpenAI and xAI)
            return self._call_openai_compatible(
                provider,
                api_key,
                config["base_url"],
                messages,
                model,
                max_tokens,
                temperature,
            )

    def _call_openai_compatible(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        messages: list[dict],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Call OpenAI-compatible API (OpenAI, xAI)."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            response = requests.post(
                base_url, headers=headers, json=payload, timeout=60
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            raise LLMError(f"{provider} API error: {e}") from e

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage")

        logger.info(f"{provider} response: {len(content)} chars, model={model}")

        return LLMResponse(
            content=content,
            model=model,
            provider=provider,
            usage=usage,
        )

    def _call_gemini(
        self,
        api_key: str,
        messages: list[dict],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Call Google Gemini API."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        # Convert OpenAI-style messages to Gemini format
        # Gemini doesn't support 'system' role - merge into first user message
        system_content = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_content += msg["content"] + "\n"
            else:
                user_messages.append(msg)

        # If we have system content, prepend to first user message
        if system_content and user_messages:
            first_msg = user_messages[0]
            if first_msg["role"] == "user":
                user_messages[0] = {
                    "role": "user",
                    "content": system_content + first_msg["content"],
                }

        # Build Gemini contents, merging consecutive same-role messages
        contents: list[dict] = []
        for msg in user_messages:
            role = "user" if msg["role"] == "user" else "model"
            # Merge consecutive messages with same role (Gemini requirement)
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"][0]["text"] += "\n" + msg["content"]
            else:
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            raise LLMError(f"Gemini API error: {e}") from e

        content = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata")

        logger.info(f"Gemini response: {len(content)} chars, model={model}")

        return LLMResponse(
            content=content,
            model=model,
            provider="gemini",
            usage=usage,
        )

    def quick_chat(
        self, provider: str, user_message: str, system_prompt: str | None = None
    ) -> str:
        """
        Quick single-message chat.

        Args:
            provider: 'openai', 'gemini', or 'xai'
            user_message: The user's message
            system_prompt: Optional system prompt

        Returns:
            The assistant's response text
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        response = self.chat(provider, messages)
        return response.content


# Global singleton with thread-safe access
_router: LLMRouter | None = None
_router_lock = __import__("threading").Lock()


def get_router() -> LLMRouter:
    """Get or create global LLM router (thread-safe)."""
    global _router
    if _router is None:
        with _router_lock:
            # Double-check locking pattern
            if _router is None:
                _router = LLMRouter()
    return _router


def quick_chat(provider: str, message: str, system_prompt: str | None = None) -> str:
    """Convenience function for quick chat."""
    return get_router().quick_chat(provider, message, system_prompt)
