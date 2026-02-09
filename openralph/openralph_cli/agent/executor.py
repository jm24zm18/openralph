from __future__ import annotations

from pathlib import Path
from typing import Callable
from dataclasses import dataclass, field
import json
import logging

from .providers.base import LLMProvider, Message, ToolResult
from ..logging import raw_log
from .tools import (
    TOOLS,
    ToolContext,
    execute_tool,
    _normalize_tool_args,
    _resolve_tool_alias,
    _unknown_tool_error,
)

log = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    max_turns: int = 50
    system_prompt: str = ""
    timeout_default: int = 120
    timeout_max: int = 600
    max_output_chars: int = 50000
    allowed_tools: set[str] | None = None
    sandbox_enabled: bool = True
    sandbox_mode: str = "docker"
    sandbox_docker_image: str = "python:3.12-slim"
    sandbox_network: str = "bridge"
    sandbox_fail_closed: bool = True
    sandbox_env_allowlist: list[str] = field(default_factory=lambda: ["OLLAMA_HOST", "EMBED_MODEL", "BRAVE_API_KEY"])


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
        allowed_tools=config.allowed_tools,
        sandbox_enabled=config.sandbox_enabled,
        sandbox_mode=config.sandbox_mode,
        sandbox_docker_image=config.sandbox_docker_image,
        sandbox_network=config.sandbox_network,
        sandbox_fail_closed=config.sandbox_fail_closed,
        sandbox_env_allowlist=config.sandbox_env_allowlist,
    )

    messages: list[Message] = [Message(role="user", content=prompt)]
    tool_calls_made = 0
    last_text = ""
    tool_cache: dict[str, str] = {}
    tool_repeat_count: dict[str, int] = {}
    recent_tools: list[str] = []
    llm_failures = 0

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
            llm_failures += 1
            msg = str(e).lower()
            is_timeout = "timed out" in msg or "timeout" in msg
            if is_timeout and llm_failures <= 2:
                log.warning("LLM call timed out on turn %d; retrying (%d/2)", turn, llm_failures)
                continue
            log.error("LLM call failed: %s", e)
            return AgentResult(
                final_text=last_text,
                messages=messages,
                tool_calls_made=tool_calls_made,
                completed=False,
                error=f"LLM call failed: {e}",
            )
        llm_failures = 0

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
            recent_tools.append(tc.name)
            if len(recent_tools) > 20:
                recent_tools = recent_tools[-20:]
            cache_key = f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True)}"
            tool_repeat_count[cache_key] = tool_repeat_count.get(cache_key, 0) + 1
            repeat_count = tool_repeat_count[cache_key]
            tool_names = {t["name"] for t in TOOLS}
            use_cache = tc.name != "bash"

            noisy_tools = {"list_dir", "search", "glob", "read_file"}
            mutating_tools = {"write_file", "edit_file", "bash"}
            if (
                tc.name in noisy_tools
                and len(recent_tools) >= 12
                and sum(1 for name in recent_tools[-12:] if name in noisy_tools) >= 10
                and sum(1 for name in recent_tools[-12:] if name in mutating_tools) == 0
            ):
                result_text = (
                    "Error: tool loop detected (repeated discovery/search calls without edits). "
                    "Stop listing/searching and proceed by editing files or running a focused bash command."
                )
                is_error = True
                raw_log("tools", f"RESULT turn={turn} tool={tc.name} error={is_error}\nresult={result_text}")
                if on_tool_result:
                    on_tool_result(tc.name, result_text, is_error)
                results.append(ToolResult(
                    tool_call_id=tc.id,
                    content=result_text,
                    is_error=is_error,
                ))
                continue

            if use_cache and cache_key in tool_cache and tool_repeat_count[cache_key] > 1:
                if repeat_count >= 4:
                    result_text = (
                        f"Error: repeated identical tool call blocked for '{tc.name}' "
                        f"after {repeat_count - 1} repeats. Use a different tool, "
                        "different arguments, or proceed with available results."
                    )
                    is_error = True
                    log.debug("Blocking repeated tool call: %s", tc.name)
                else:
                    result_text = (
                        f"[Cached — you already called {tc.name} with these arguments. "
                        f"Previous result:]\n{tool_cache[cache_key]}"
                    )
                    is_error = False
                    log.debug("Returning cached result for repeated tool call: %s", tc.name)
            else:
                log.debug("Executing tool: %s(%s)", tc.name, tc.arguments)

                if on_tool_call:
                    on_tool_call(tc.name, tc.arguments)
                raw_log("tools", f"CALL turn={turn} tool={tc.name}\nargs={json.dumps(tc.arguments, ensure_ascii=False)}")

                norm_name, norm_args = _normalize_tool_args(tc.name, tc.arguments)
                alias = _resolve_tool_alias(norm_name, norm_args)
                if norm_name not in tool_names and not alias:
                    result_text = _unknown_tool_error(norm_name)
                    is_error = True
                else:
                    result_text, is_error = execute_tool(tc.name, tc.arguments, ctx)

                log.debug("Tool result (error=%s): %s", is_error, result_text[:200])

                if use_cache and not is_error:
                    tool_cache[cache_key] = result_text

            raw_log("tools", f"RESULT turn={turn} tool={tc.name} error={is_error}\nresult={result_text}")

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
