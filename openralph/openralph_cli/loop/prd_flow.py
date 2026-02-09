from __future__ import annotations

from pathlib import Path

from ..agent import AgentConfig, run_agent
from ..paths import Paths
from ..prd import PRD_QA_QUESTIONS, build_prd_answers_prompt
from ..settings import OpenRalphSettings
from .agent_runner import _get_provider
from .helpers import _clear_human_exchange, _extract_json_from_response, _read_text


def _build_prd_handoff_prompt() -> str:
    lines = [
        "# PRD Q&A",
        "",
        "Please answer the following questions in JSON with keys matching the question ids.",
        "Example:",
        '{"project_name": "My Project", "problem": "..."}',
        "",
        "Questions:",
    ]
    for key, question in PRD_QA_QUESTIONS:
        lines.append(f"- {key}: {question}")
    return "\n".join(lines)


def _clear_prd_handoff_if_present(paths: Paths) -> None:
    if not paths.human_request.exists():
        return
    content = _read_text(paths.human_request, max_chars=2000)
    if "# PRD Q&A" in content:
        _clear_human_exchange(paths.human_request, paths.human_response)


def _generate_prd_answers_native(
    repo: Path,
    settings: OpenRalphSettings,
    paths: Paths,
    log,
    user_prompt: str = "",
) -> dict[str, str] | None:
    prompt = build_prd_answers_prompt(repo, user_prompt=user_prompt)
    log_file = paths.logs / "prd-qa-auto.log"
    result = run_agent(
        provider=_get_provider(settings, role="plan"),
        prompt=prompt,
        repo=repo,
        config=AgentConfig(
            max_turns=settings.agent_max_turns,
            system_prompt=(
                "You are a product manager. You may use tools if helpful, but your final response "
                "MUST be a single JSON object answering all questions. No markdown."
            ),
            timeout_default=settings.agent_timeout,
            max_output_chars=settings.agent_max_output,
        ),
    )
    output = result.final_text or ""
    log_content = (
        f"Prompt:\n{prompt}\n\n---\n\nOutput:\n{output}\n\n---\n\n"
        f"Tool calls: {result.tool_calls_made}\nCompleted: {result.completed}\n"
    )
    if result.error:
        log_content += f"Error: {result.error}\n"
    log_file.write_text(log_content, encoding="utf-8")
    return _extract_json_from_response(output.strip())
