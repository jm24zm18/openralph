from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    role: str  # "user" | "assistant" | "tool"
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_results: list[ToolResult] | None = None


@dataclass(frozen=True)
class StreamChunk:
    text: str | None = None
    tool_call: ToolCall | None = None
    done: bool = False


class LLMProvider(ABC):
    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[dict],
        system: str | None = None,
    ) -> Message:
        """Single completion with tool use support."""
        ...

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        tools: list[dict],
        system: str | None = None,
    ) -> Iterator[StreamChunk]:
        """Streaming completion."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier being used."""
        ...
