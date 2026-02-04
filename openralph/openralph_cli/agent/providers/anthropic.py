from __future__ import annotations

# Placeholder - not used when proxy is enabled
# This file exists to satisfy imports but the OpenAI provider is used with the proxy

from .base import LLMProvider, Message, StreamChunk
from typing import Iterator


class AnthropicProvider(LLMProvider):
    """Placeholder for direct Anthropic API access (not used with proxy)."""

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514"):
        raise NotImplementedError(
            "Direct Anthropic provider not implemented. Use the proxy with OpenAI-compatible provider."
        )

    def chat(self, messages: list[Message], tools: list[dict], system: str | None = None) -> Message:
        raise NotImplementedError()

    def stream(self, messages: list[Message], tools: list[dict], system: str | None = None) -> Iterator[StreamChunk]:
        raise NotImplementedError()

    @property
    def model_name(self) -> str:
        return "anthropic-placeholder"
