from __future__ import annotations

from pathlib import Path
from typing import Callable
from dataclasses import dataclass, field
import logging

from .providers.base import LLMProvider, Message, ToolResult
from .tools import TOOLS, ToolContext, execute_tool

log = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    max_turns: int = 50
    system_prompt: str = ""
    timeout_default: int = 120
    timeout_max: int = 600
    max_output_chars: int = 50000


@dataclass
class AgentResult:
    final_text: str
    messages: list[Message]
    tool_calls_made: int
    completed: bool = True
    error: str | None = None


def run_agent(
    provider: LLMProvider,
    prompt: str,
    repo: Path,
    config: AgentConfig | None = None,
    on_tool_call: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str, bool], None] | None = None,
    on_text: Callable[[str], None] | None = None,
    on_turn: Callable[[int], None] | None = None,
) -> AgentResult:
    """
    Run an agentic loop until the model stops calling tools or max_turns is reached.

    Args:
        provider: LLM provider to use for completions
        prompt: Initial user prompt
        repo: Repository path for tool execution context
        config: Agent configuration options
        on_tool_call: Callback when a tool is invoked (name, args)
        on_tool_result: Callback when a tool returns (name, result, is_error)
        on_text: Callback for text output from the model
        on_turn: Callback at the start of each turn (turn_number)

    Returns:
        AgentResult with final text, message history, and stats
    """
    config = config or AgentConfig()
    ctx = ToolContext(
        repo=repo.resolve(),
        timeout_default=config.timeout_default,
        timeout_max=config.timeout_max,
        max_output_chars=config.max_output_chars,
    )

    messages: list[Message] = [Message(role="user", content=prompt)]
    tool_calls_made = 0
    last_text = ""

    log.debug("Starting agent loop: repo=%s, max_turns=%d", repo, config.max_turns)

    for turn in range(1, config.max_turns + 1):
        if on_turn:
            on_turn(turn)

        log.debug("Turn %d: calling LLM", turn)

        try:
            response = provider.chat(
                messages=messages,
                tools=TOOLS,
                system=config.system_prompt or None,
            )
        except Exception as e:
            log.error("LLM call failed: %s", e)
            return AgentResult(
                final_text=last_text,
                messages=messages,
                tool_calls_made=tool_calls_made,
                completed=False,
                error=f"LLM call failed: {e}",
            )

        messages.append(response)

        if response.content:
            last_text = response.content
            if on_text:
                on_text(response.content)

        # If no tool calls, we're done
        if not response.tool_calls:
            log.debug("No tool calls, agent complete after %d turns", turn)
            return AgentResult(
                final_text=response.content,
                messages=messages,
                tool_calls_made=tool_calls_made,
                completed=True,
            )

        # Execute tool calls
        results: list[ToolResult] = []
        for tc in response.tool_calls:
            tool_calls_made += 1
            log.debug("Executing tool: %s(%s)", tc.name, tc.arguments)

            if on_tool_call:
                on_tool_call(tc.name, tc.arguments)

            result_text, is_error = execute_tool(tc.name, tc.arguments, ctx)

            log.debug("Tool result (error=%s): %s", is_error, result_text[:200])

            if on_tool_result:
                on_tool_result(tc.name, result_text, is_error)

            results.append(ToolResult(
                tool_call_id=tc.id,
                content=result_text,
                is_error=is_error,
            ))

        # Add tool results to conversation
        messages.append(Message(role="tool", content="", tool_results=results))

    # Max turns reached
    log.warning("Max turns (%d) reached without completion", config.max_turns)
    return AgentResult(
        final_text=last_text,
        messages=messages,
        tool_calls_made=tool_calls_made,
        completed=False,
        error=f"Max turns ({config.max_turns}) reached",
    )


def format_conversation(messages: list[Message]) -> str:
    """Format a conversation for logging/display."""
    parts = []
    for m in messages:
        if m.role == "user":
            parts.append(f"[USER]\n{m.content[:500]}")
        elif m.role == "assistant":
            text = m.content[:300] if m.content else ""
            tools = ""
            if m.tool_calls:
                tools = "\n  Tools: " + ", ".join(tc.name for tc in m.tool_calls)
            parts.append(f"[ASSISTANT]\n{text}{tools}")
        elif m.role == "tool":
            if m.tool_results:
                for tr in m.tool_results:
                    status = "ERROR" if tr.is_error else "OK"
                    parts.append(f"[TOOL {status}]\n{tr.content[:200]}")
    return "\n\n".join(parts)
