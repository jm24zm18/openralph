from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Iterator

from .base import LLMProvider, Message, ToolCall, ToolResult, StreamChunk

log = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """
    OpenAI-compatible provider that works with the OpenRalph proxy.

    The proxy translates between the backend LLM and OpenAI-compatible format,
    handling tool call extraction and response formatting.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:18889",
        api_key: str = "LOCAL_DGX",
        model: str = "chatgpt-oss",
        timeout: int = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def model_name(self) -> str:
        return self.model

    def _convert_messages(self, messages: list[Message], system: str | None) -> list[dict]:
        """Convert internal Message format to OpenAI API format."""
        result = []

        # Add system message if provided
        if system:
            result.append({"role": "system", "content": system})

        for m in messages:
            if m.role == "user":
                result.append({"role": "user", "content": m.content})

            elif m.role == "assistant":
                msg: dict = {"role": "assistant"}

                if m.content:
                    msg["content"] = m.content

                if m.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in m.tool_calls
                    ]

                result.append(msg)

            elif m.role == "tool" and m.tool_results:
                for tr in m.tool_results:
                    result.append({
                        "role": "tool",
                        "tool_call_id": tr.tool_call_id,
                        "content": tr.content,
                    })

        return result

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert tool definitions to OpenAI format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    def _parse_response(self, data: dict) -> Message:
        """Parse OpenAI API response to internal Message format."""
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})

        content = message.get("content") or ""
        tool_calls = None

        if message.get("tool_calls"):
            tool_calls = []
            for tc in message["tool_calls"]:
                func = tc.get("function", {})
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}

                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=args,
                ))

        return Message(
            role="assistant",
            content=content,
            tool_calls=tool_calls if tool_calls else None,
        )

    def chat(
        self,
        messages: list[Message],
        tools: list[dict],
        system: str | None = None,
    ) -> Message:
        """Make a chat completion request."""
        url = f"{self.base_url}/v1/chat/completions"

        payload = {
            "model": self.model,
            "messages": self._convert_messages(messages, system),
            "tools": self._convert_tools(tools),
            "tool_choice": "auto",
            "stream": False,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        body = json.dumps(payload).encode("utf-8")
        log.debug("Request to %s: %d bytes", url, len(body))

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                response_body = resp.read().decode("utf-8")
                data = json.loads(response_body)
                log.debug("Response: %d bytes", len(response_body))
                return self._parse_response(data)

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            log.error("HTTP %d: %s", e.code, error_body[:500])
            raise RuntimeError(f"LLM API error: HTTP {e.code}: {error_body[:200]}")

        except urllib.error.URLError as e:
            log.error("URL error: %s", e.reason)
            raise RuntimeError(f"LLM API connection error: {e.reason}")

        except json.JSONDecodeError as e:
            log.error("JSON decode error: %s", e)
            raise RuntimeError(f"LLM API returned invalid JSON: {e}")

    def stream(
        self,
        messages: list[Message],
        tools: list[dict],
        system: str | None = None,
    ) -> Iterator[StreamChunk]:
        """
        Streaming is not fully implemented - falls back to non-streaming.
        The proxy converts streaming requests to non-streaming anyway.
        """
        response = self.chat(messages, tools, system)

        if response.content:
            yield StreamChunk(text=response.content)

        if response.tool_calls:
            for tc in response.tool_calls:
                yield StreamChunk(tool_call=tc)

        yield StreamChunk(done=True)
